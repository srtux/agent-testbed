import os
import re
import json
import logging

from testbed_utils.config import DEFAULT_PRO_MODEL, DEFAULT_FLASH_MODEL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject


# --- Local Tool (real compute) ---

async def extract_travel_intent(prompt: str) -> dict:
    """Extract structured travel intent from a natural language prompt.
    Parses destination, dates, and preferences from free text."""
    intent = {"raw_prompt": prompt[:200]}

    # Extract airport codes (3 uppercase letters)
    codes = re.findall(r'\b([A-Z]{3})\b', prompt.upper())
    if codes:
        intent["detected_airports"] = codes

    # Extract dates (various formats)
    date_patterns = re.findall(r'\d{4}-\d{2}-\d{2}|\b\w+ \d{1,2},? \d{4}\b', prompt)
    if date_patterns:
        intent["detected_dates"] = date_patterns

    # Detect priority keywords
    if any(w in prompt.lower() for w in ["urgent", "emergency", "asap", "cancelled"]):
        intent["priority"] = "urgent"
    else:
        intent["priority"] = "normal"

    # Detect budget tier
    if any(w in prompt.lower() for w in ["budget", "cheap", "economy"]):
        intent["budget_tier"] = "economy"
    elif any(w in prompt.lower() for w in ["luxury", "first class", "premium"]):
        intent["budget_tier"] = "premium"
    else:
        intent["budget_tier"] = "standard"

    return intent


# --- In-Process Sub-Agent (AgentTool model) ---

intent_classifier = LlmAgent(
    name="IntentClassifier",
    model=DEFAULT_FLASH_MODEL,
    description="Classify user travel request type: new_booking, modification, inquiry, or cancellation.",
    static_instruction="""You classify travel requests into exactly one category:
    - new_booking: User wants to book a new trip
    - modification: User wants to change an existing booking
    - inquiry: User is asking questions about travel options
    - cancellation: User wants to cancel a booking

    Respond with just the category name and a one-sentence reason.""",
)


# --- A2A HTTP + MCP Delegation Tool ---

class FlightRequest(BaseModel):
    user_id: str = Field(description="The unique user ID for the request")
    destination: str = Field(description="The destination airport code (e.g., SFO, JFK)")
    departure_airport: str = Field(default="", description="The departure airport code if known")
    dates: str = Field(description="The travel dates")

async def consult_flight_specialist(request: FlightRequest) -> dict:
    """Delegates the flight booking task to the FlightSpecialist sub-agent."""
    flight_specialist_url = os.environ.get("FLIGHT_SPECIALIST_URL", "http://localhost:8082/chat")
    profile_mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")

    if profile_mcp_url.endswith("/mcp/call_tool"):
        profile_mcp_url = profile_mcp_url.replace("/mcp/call_tool", "/sse")

    logger.info(f"Checking user profile via FastMCP for user: {request.user_id}, destination: {request.destination}")

    profile_data = {"preferences": "Unknown"}
    # Trace edge: AE -> CR MCP using official FastMCP Session
    try:
        async with sse_client(profile_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object

                res = await session.call_tool(
                    "get_user_preferences",
                    arguments={"user_id": request.user_id},
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    profile_data = res.content[0].text
                    if isinstance(profile_data, str):
                        try:
                            parsed_data = json.loads(profile_data)
                            if isinstance(parsed_data, dict):
                                profile_data = parsed_data
                            else:
                                profile_data = {"data": parsed_data}
                        except Exception:
                            profile_data = {"raw_text": profile_data}
    except Exception as e:
        logger.warning(f"FastMCP call failed: {e}")
        profile_data = {"error": str(e)}
    request_dict = request.model_dump()
    request_dict["profile_context"] = profile_data

    logger.info(f"Delegating to FlightSpecialist for destination: {request.destination}")

    # Trace edge: AE -> CR
    async with httpx.AsyncClient() as client:
        response = await client.post(
            flight_specialist_url,
            json=request_dict,
            timeout=60.0
        )
        if response.status_code != 200:
            logger.error(f"Failed to delegate to FlightSpecialist. Status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()
        return response.json()


# --- Agent Definition ---
# When deployed to Agent Engine, the platform serializes `agent` via AdkApp(agent=agent).
# Agent Engine provides its own TracerProvider and telemetry pipeline via
# GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY env var — do NOT call setup_telemetry()
# or FastAPIInstrumentor at module level as it conflicts with the platform's instrumentation.

agent = LlmAgent(
    name="RootRouter",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Root Router for an Enterprise Travel Concierge.
    1. First, extract the travel intent from the user's request using extract_travel_intent.
    2. Classify the request type using the IntentClassifier tool.
    3. For new bookings, delegate to the Flight Specialist via consult_flight_specialist.

    Ensure you gather the user's information and trigger the master itinerary planner correctly.
    Do not ask the user for their departure airport if it's missing; just pass an empty string to the tool.""",
    tools=[extract_travel_intent, AgentTool(agent=intent_classifier), consult_flight_specialist],
)

# FastAPI wrapper for local development and A2A HTTP simulation.
# In Agent Engine, the platform uses AdkApp(agent=agent) directly — this is not used.
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()

class RouterRequest(BaseModel):
    user_id: str
    prompt: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: RouterRequest):
    logger.info(f"RootRouter Received root prompt for {request.user_id}")

    final_response = None
    prompt_text = f"[System Context: The current user's ID is '{request.user_id}']\n{request.prompt}"
    async for event in runner.run_async(user_id=request.user_id, session_id="default", new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    return {"status": "complete", "orchestration_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
