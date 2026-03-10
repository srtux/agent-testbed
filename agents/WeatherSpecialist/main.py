# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_PRO_MODEL

setup_telemetry()
logger = setup_logging()

import os
import json

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject


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

    if inventory_mcp_url.endswith("/mcp/call_tool"):
        inventory_mcp_url = inventory_mcp_url.replace("/mcp/call_tool", "/sse")

    # Simulates edge WeatherSpecialist -> GKE MCP Inventory over FastMCP Session
    try:
        async with sse_client(inventory_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object

                res = await session.call_tool(
                    "get_weather",
                    arguments={"location": location},
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        return json.loads(data)
                    return data
    except Exception as e:
        logger.warning(f"FastMCP mock weather failed natively due to: {e}")
        return {"condition": "Sunny", "temperature_c": 22}

    return {"condition": "Sunny", "temperature_c": 22}


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
    prompt = f"Check weather for {request.destination}. Current itinerary: {request.itinerary_so_far}. User: {request.user_id}. Finalize with Booking Orchestrator."

    final_response = None
    async for event in runner.run_async(user_id=request.user_id, session_id="default", new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    return {"status": "complete", "weather_agent_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)
