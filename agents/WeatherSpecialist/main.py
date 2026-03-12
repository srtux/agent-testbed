# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_PRO_MODEL

setup_telemetry()
logger = setup_logging()

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from testbed_utils.mcp_client import call_mcp_tool
from testbed_utils.runner import run_agent


# --- Local Tool (real compute) ---

async def suggest_packing(temperature_c: float, condition: str) -> dict:
    """Suggest packing items based on weather conditions."""
    items = ["passport", "phone charger", "toiletries"]
    if temperature_c < 10:
        items.extend(["warm jacket", "gloves", "scarf"])
    elif temperature_c < 20:
        items.extend(["light jacket", "layers"])
    else:
        items.extend(["sunscreen", "sunglasses", "light clothing"])
    if "rain" in condition.lower():
        items.extend(["umbrella", "waterproof jacket"])
    if "snow" in condition.lower():
        items.extend(["snow boots", "thermal underwear"])
    return {"suggested_items": items, "based_on": {"temp_c": temperature_c, "condition": condition}}


# --- MCP Delegation Tool ---

async def fetch_weather(user_id: str, location: str) -> dict:
    """Mock weather endpoint acting as an edge to GKE MCP Inventory."""
    logger.info(f"Checking weather for {location} (User: {user_id})")
    inventory_mcp_url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8091/sse")

    return await call_mcp_tool(
        inventory_mcp_url, "get_weather",
        {"location": location},
        fallback={"condition": "Sunny", "temperature_c": 22},
    )


# --- A2A HTTP Delegation Tool ---

async def delegate_to_booking_orchestrator(user_id: str, itinerary_details: str) -> dict:
    """Sends finalized travel plans to the Booking Orchestrator."""
    logger.info(f"Delegating final confirmation to Booking Orchestrator for {user_id}")
    # Simulates edge WeatherSpecialist -> BookingOrchestrator
    booking_orch_url = os.environ.get("BOOKING_ORCHESTRATOR_URL", "http://localhost:8081/chat")

    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "itinerary_details": itinerary_details}
        res = await client.post(booking_orch_url, json=payload, timeout=60.0)
        if res.status_code >= 400:
            return {"status": "mock_success", "summary": "Bookings finalized (fallback)."}
        return res.json()

# --- Agent ---
agent = LlmAgent(
    name="WeatherSpecialist",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Weather Specialist.
    1. Check the weather for the destination using fetch_weather.
    2. Based on the weather, suggest packing items using suggest_packing.
    3. Once weather is confirmed, delegate the combined itinerary to the Booking Orchestrator.""",
    tools=[suggest_packing, fetch_weather, delegate_to_booking_orchestrator],
)

# --- FastAPI App ---
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class WeatherRequest(BaseModel):
    user_id: str
    destination: str
    itinerary_so_far: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: WeatherRequest):
    logger.info(f"Weather Specialist checking conditions for {request.destination}")
    itinerary_context = (request.itinerary_so_far or "")[:2000]
    prompt = f"Check weather for {request.destination}. Current itinerary: {itinerary_context}. User: {request.user_id}. Finalize with Booking Orchestrator."

    final_response = await run_agent(runner, request.user_id, prompt)
    return {"status": "complete", "weather_agent_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
