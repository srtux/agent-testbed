# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_PRO_MODEL

setup_telemetry()
logger = setup_logging()

import os
import json
import uuid

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

async def calculate_nightly_rate(base_cost: float, destination: str) -> dict:
    """Calculate nightly hotel rate with destination-based adjustments."""
    premium = {"SFO": 1.4, "JFK": 1.5, "LHR": 1.6, "NRT": 1.3}
    multiplier = premium.get(destination.upper()[:3], 1.0)
    nightly = round(base_cost * multiplier, 2)
    return {"nightly_rate": nightly, "destination_multiplier": multiplier, "currency": "USD"}


# --- MCP Delegation Tool ---

async def fetch_hotel_inventory(user_id: str, destination: str, dates: str) -> dict:
    """Mock database check for hotels via GKE Inventory MCP."""
    logger.info(f"Checking hotel inventory for {destination} (User: {user_id})")

    inventory_mcp_url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8091/sse")

    if inventory_mcp_url.endswith("/mcp/call_tool"):
        inventory_mcp_url = inventory_mcp_url.replace("/mcp/call_tool", "/sse")

    # GKE -> GKE edge using FastMCP Session
    try:
        async with sse_client(inventory_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object

                res = await session.call_tool(
                    "get_hotel_inventory",
                    arguments={"destination": destination},
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        return json.loads(data)
                    return data
    except Exception as e:
        logger.warning(f"FastMCP call failed natively: {e}")
        return {"status": "available", "cost": 250, "hotel_name": "Cloud Suites"}

    return {"status": "available", "cost": 250, "hotel_name": "Cloud Suites"}


# --- A2A HTTP Delegation Tool ---

async def consult_car_rental(user_id: str, dates: str, destination: str) -> dict:
    """Delegates to the Car Rental Specialist."""
    logger.info(f"Delegating to CarRentalSpecialist for {user_id}")
    # GKE -> GKE Edge
    car_rental_url = os.environ.get("CAR_RENTAL_SPECIALIST_URL", "http://localhost:8085/chat")

    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "dates": dates, "destination": destination}
        res = await client.post(car_rental_url, json=payload, timeout=60.0)
        if res.status_code >= 400:
            return {"status": "mock_success", "car": "Toyota Camry"}
        return res.json()

# --- Agent ---
agent = LlmAgent(
    name="HotelSpecialist",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Hotel Specialist.
    1. Check hotel inventory via the MCP server.
    2. Calculate the nightly rate based on the destination using calculate_nightly_rate.
    3. Delegate to the Car Rental Specialist to secure a car.
    4. Return combined summary to the caller.""",
    tools=[calculate_nightly_rate, fetch_hotel_inventory, consult_car_rental],
)

# --- FastAPI App ---
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class HotelRequest(BaseModel):
    user_id: str
    destination: str
    dates: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: HotelRequest):
    logger.info(f"Hotel Specialist coordinating lodging at {request.destination}")
    prompt = f"Find a hotel at {request.destination} for {request.dates}. Ensure you coordinate with Car Rental. User: {request.user_id}."

    final_response = None
    async for event in runner.run_async(user_id=request.user_id, session_id=str(uuid.uuid4()), new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    return {"status": "complete", "hotel_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8084)
