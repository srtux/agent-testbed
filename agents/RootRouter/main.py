from testbed_utils.telemetry import setup_authenticated_transport

setup_authenticated_transport()

import os
import re
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

from testbed_utils.mcp_client import call_mcp_tool
from testbed_utils.runner import run_agent


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

    logger.info(f"consult_flight_specialist called for user_id={user_id}")
    request_dict = {
        "user_id": user_id,
        "destination": destination,
        "dates": dates,
        "departure_airport": departure_airport
    }

    logger.info(f"Checking user profile via MCP for user: {user_id}")
    profile_data = {"preferences": "Unknown"}
    if user_id:
        profile_data = await call_mcp_tool(
            profile_mcp_url, "get_user_preferences",
            {"user_id": user_id},
            fallback={"preferences": "Unknown"},
        )
    logger.info(f"Profile data gathered for user_id={user_id}")

    # request_dict already created above
    request_dict["profile_context"] = profile_data

    # OIDC tokens are injected automatically by the httpx request_hook
    # installed via setup_authenticated_transport().
    logger.info(f"Calling FlightSpecialist at {flight_specialist_url}")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            flight_specialist_url,
            json=request_dict,
            timeout=60.0
        )
    logger.info(f"FlightSpecialist response status: {response.status_code}")
    if response.status_code != 200:
        logger.error(f"Failed to delegate to FlightSpecialist. Status: {response.status_code}, Response: {response.text}")
    response.raise_for_status()
    return response.json()


agent = LlmAgent(
    name="RootRouter",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Root Router for an Enterprise Travel Concierge.
    1. First, extract the travel intent from the user's request using extract_travel_intent.
    2. Classify the request type using the IntentClassifier tool.
    3. For new bookings or flight search requests, delegate to the Flight Specialist via consult_flight_specialist.

    CRITICAL: You MUST use the exact user_id provided in the [System Context] for all tool calls (especially `consult_flight_specialist`).
    Do not ask the user for their departure airport if it's missing; just pass an empty string to the tool.
    DO NOT assume any tools exist other than the ones provided.""" ,
    tools=[extract_travel_intent, AgentTool(agent=intent_classifier), consult_flight_specialist],
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
    prompt_text = f"[System Context: The current user's ID is '{request.user_id}']\n{request.prompt}"
    final_response = await run_agent(runner, request.user_id, prompt_text)
    return {"status": "complete", "orchestration_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
