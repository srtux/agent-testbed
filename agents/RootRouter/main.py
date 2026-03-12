from testbed_utils.telemetry import setup_authenticated_transport

setup_authenticated_transport()

import os
import re
import json
import logging
import uuid

DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")
DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

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

async def consult_flight_specialist(user_id: str, destination: str, dates: str, departure_airport: str = "") -> dict:
    """Delegates flight search, availability check, and booking tasks to the FlightSpecialist sub-agent."""
    flight_specialist_url = os.environ.get("FLIGHT_SPECIALIST_URL", "http://localhost:8082/chat")
    profile_mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")

    if profile_mcp_url.endswith("/mcp/call_tool"):
        profile_mcp_url = profile_mcp_url.replace("/mcp/call_tool", "/sse")

    logger.warning(f"[DEBUG_TOOL] consult_flight_specialist START. user_id={user_id}")
    # Create request_dict for downstream delegation upfront
    request_dict = {
        "user_id": user_id,
        "destination": destination,
        "dates": dates,
        "departure_airport": departure_airport
    }

    logger.info(f"Checking user profile via FastMCP for user: {user_id}, destination: {destination}")

    profile_data = {"preferences": "Unknown"}
    if user_id:
        try:
            async with sse_client(profile_mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    meta = {}
                    inject(meta)  # Propagate W3C traceparent into the _meta object

                    res = await session.call_tool(
                        "get_user_preferences",
                        arguments={"user_id": user_id},
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
            logger.warning(f"[DEBUG_TOOL] FastMCP call failed: {e}")
            profile_data = {"error": str(e)}
    logger.warning(f"[DEBUG_TOOL] Profile data gathered: {profile_data}")

    # request_dict already created above
    request_dict["profile_context"] = profile_data

    # OIDC tokens are injected automatically by the httpx request_hook
    # installed via setup_authenticated_transport().
    # --- FlightSpecialist Call Bypassed to isolate Profile_MCP ---
    logger.warning(f"[DEBUG_TOOL] Returning Profile data only, bypassing FlightSpecialist.")
    return {"profile_context": profile_data, "status": "mcp_isolated_test"}

async def consult_booking_orchestrator(user_id: str, itinerary_details: str) -> dict:
    """Delegates to the BookingOrchestrator to finalize and confirm the travel itinerary."""
    booking_orch_url = os.environ.get("BOOKING_ORCHESTRATOR_URL", "http://localhost:8081/chat")
    logger.info(f"Delegating confirmation to BookingOrchestrator for {user_id}")
    
    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "itinerary_details": itinerary_details}
        response = await client.post(booking_orch_url, json=payload, timeout=60.0)
    if response.status_code != 200:
        logger.error(f"Failed to delegate to BookingOrchestrator. Status: {response.status_code}, Response: {response.text}")
    response.raise_for_status()
    return response.json()


class DebugLlmAgent(LlmAgent):
    def stream_query(self, message: str, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"[DEBUG_AGENT] stream_query INVOKED. message: {message}, kwargs: {kwargs}")
        try:
            for event in super().stream_query(message=message, **kwargs):
                logger.warning(f"[DEBUG_AGENT] Yielding event type: {type(event)}")
                yield event
        except Exception as e:
            logger.warning(f"[DEBUG_AGENT] stream_query CRASHED: {e}")
            raise e
        logger.warning(f"[DEBUG_AGENT] stream_query FINISHED")



agent = DebugLlmAgent(
    name="RootRouter",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Root Router for an Enterprise Travel Concierge.
    1. First, extract the travel intent from the user's request using extract_travel_intent.
    2. Classify the request type using the IntentClassifier tool.
    3. For new bookings or flight search requests, delegate to the Flight Specialist via consult_flight_specialist.
    4. For finalizing bookings or confirming itineraries, delegate to the Booking Orchestrator via consult_booking_orchestrator.

    CRITICAL: You MUST use the exact user_id provided in the [System Context] for all tool calls (especially `consult_flight_specialist` and `consult_booking_orchestrator`).
    Do not ask the user for their departure airport if it's missing; just pass an empty string to the tool.
    DO NOT assume any tools exist other than the ones provided.""" ,
    tools=[extract_travel_intent, AgentTool(agent=intent_classifier), consult_flight_specialist, consult_booking_orchestrator],
)

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
    session_id = str(uuid.uuid4())
    prompt_text = f"[System Context: The current user's ID is '{request.user_id}']\n{request.prompt}"
    
    async for event in runner.run_async(user_id=request.user_id, session_id=session_id, new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    return {"status": "complete", "orchestration_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
