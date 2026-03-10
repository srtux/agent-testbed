# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_FLASH_MODEL

setup_telemetry()
logger = setup_logging()

import os
import json

from fastapi import FastAPI
from pydantic import BaseModel
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
import httpx
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# --- Tools --
async def check_flight_availability(user_id: str, destination: str, dates: str) -> dict:
    """Mock database check for flights."""
    logger.info(f"Checking flights for {destination} on {dates} (User: {user_id})")
    return {"status": "available", "cost": 450, "airline": "CloudAir"}

async def delegate_to_hotel_specialist(user_id: str, destination: str, dates: str) -> dict:
    """Delegates to the Hotel Specialist on GKE."""
    logger.info(f"Delegating to HotelSpecialist for {user_id}")
    hotel_url = os.environ.get("HOTEL_SPECIALIST_URL", "http://localhost:8084/chat")
    
    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "destination": destination, "dates": dates}
        res = await client.post(hotel_url, json=payload, timeout=60.0)
        if res.status_code >= 400:
            return {"status": "mock_success", "hotel": "Fallback Inn"}
        return res.json()

async def delegate_to_weather_specialist(user_id: str, destination: str, itinerary_so_far: str) -> dict:
    """Delegates to the Weather Specialist to check conditions and pass on the itinerary."""
    logger.info(f"Delegating to WeatherSpecialist for {user_id}")
    weather_url = os.environ.get("WEATHER_SPECIALIST_URL", "http://localhost:8083/chat")
    
    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "destination": destination, "itinerary_so_far": itinerary_so_far}
        res = await client.post(weather_url, json=payload, timeout=60.0)
        if res.status_code >= 400:
            return {"status": "mock_success"}
        return res.json()

# --- Agent ---
agent = LlmAgent(
    name="FlightSpecialist",
    model=DEFAULT_FLASH_MODEL, 
    static_instruction="""You are the Flight Specialist. 
    1. Check flight availability.
    2. Delegate hotel booking coordination to the Hotel Specialist.
    3. Delegate the final weather check and onward orchestration to the Weather Specialist.
    Return the combined results to the caller.""",
    tools=[check_flight_availability, delegate_to_hotel_specialist, delegate_to_weather_specialist],
)

# --- FastAPI App ---
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()

# Instrument FastAPI to automatically extract W3C `traceparent` headers
FastAPIInstrumentor.instrument_app(app)

class ChatRequest(BaseModel):
    user_id: str
    destination: str
    departure_airport: str | None = None
    dates: str
    profile_context: dict | None = None

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Log with context
    logger.info(f"Received request to process flights for {request.destination} (User: {request.user_id})")
    
    prompt = f"User {request.user_id} wants a flight from {request.departure_airport} to {request.destination} for {request.dates}. Preferences context: {json.dumps(request.profile_context)}. Coordinate with Hotel and Weather specialists."
    
    # Run the agent over the prompt
    # The ADK run_async will create its own spans, appropriately as children
    # of the FastAPI HTTP Request span (which has the remote trace ID)
    final_response = None
    async for event in runner.run_async(user_id=request.user_id, session_id="default", new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text
                    
    return {"agent_response": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
