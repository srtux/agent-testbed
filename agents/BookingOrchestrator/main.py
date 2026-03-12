from testbed_utils.telemetry import setup_authenticated_transport

setup_authenticated_transport()

import os
import json
import logging

from testbed_utils.config import DEFAULT_PRO_MODEL, DEFAULT_FLASH_MODEL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.agent_tool import AgentTool
from fastapi import FastAPI

from testbed_utils.mcp_client import call_mcp_tool
from testbed_utils.runner import run_agent


# --- Local Tools (real compute) ---

async def calculate_trip_cost(flight_cost: float, hotel_cost: float, car_cost: float, days: int, loyalty_tier: str) -> dict:
    """Aggregate costs from flight, hotel, and car rental. Apply loyalty discounts."""
    from testbed_utils.config import LOYALTY_DISCOUNTS
    subtotal = flight_cost + (hotel_cost * days) + (car_cost * days)
    discount_pct = LOYALTY_DISCOUNTS.get(loyalty_tier, 0)
    discount = subtotal * discount_pct
    total = subtotal - discount
    return {
        "subtotal": round(subtotal, 2),
        "loyalty_discount_pct": discount_pct * 100,
        "discount_amount": round(discount, 2),
        "total": round(total, 2),
        "currency": "USD",
    }


async def format_itinerary(user_id: str, destination: str, flight_details: str,
                           hotel_details: str, car_details: str, weather: str, total_cost: float) -> dict:
    """Build a structured itinerary summary document from all booking components."""
    itinerary = {
        "itinerary_id": f"ITIN-{hash(user_id + destination) % 100000:05d}",
        "traveler": user_id,
        "destination": destination,
        "sections": {
            "flight": flight_details,
            "accommodation": hotel_details,
            "ground_transport": car_details,
            "weather_advisory": weather,
        },
        "total_cost_usd": total_cost,
        "status": "pending_confirmation",
    }
    return itinerary


# --- In-Process Sub-Agent (AgentTool model) ---

itinerary_validator = LlmAgent(
    name="ItineraryValidator",
    model=DEFAULT_FLASH_MODEL,
    description="Validate a travel itinerary for completeness and consistency before final booking.",
    static_instruction="""You validate travel itineraries. Check that all required components
    are present: flight, hotel, car rental, dates, and total cost.
    Flag any missing or inconsistent information.
    Respond with whether the itinerary is valid, any issues found, and a brief summary.""",
)


# --- MCP Delegation Tool ---

class BookingRequest(BaseModel):
    user_id: str
    flight_id: str
    hotel_id: str
    car_id: str

async def finalize_bookings(request: BookingRequest) -> dict:
    """Finalizes all reservations using the GKE Inventory MCP server."""
    is_dict = isinstance(request, dict)
    user_id = request.get("user_id", "") if is_dict else getattr(request, "user_id", "")
    request_dict = request if is_dict else request.model_dump()

    logger.info(f"Finalizing bookings for user: {user_id}")
    inventory_mcp_url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8091/sse")

    return await call_mcp_tool(
        inventory_mcp_url, "commit_booking", request_dict,
        fallback={"status": "success", "confirmation": "CNF-12345"},
    )


agent = LlmAgent(
    name="BookingOrchestrator",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Booking Orchestrator.
    1. Calculate the total trip cost using the calculate_trip_cost tool.
    2. Format the itinerary using the format_itinerary tool.
    3. Validate the itinerary using the ItineraryValidator tool.
    4. If valid, finalize bookings using the finalize_bookings tool.
    5. Summarize the confirmation details back.""",
    tools=[calculate_trip_cost, format_itinerary, AgentTool(agent=itinerary_validator), finalize_bookings],
)

runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()


class OrchestrationRequest(BaseModel):
    user_id: str
    itinerary_details: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: OrchestrationRequest):
    logger.info(f"BookingOrchestrator received confirmed plans for user {request.user_id}")
    prompt = f"Please finalize the following itinerary and summarize: {request.itinerary_details} for user {request.user_id}"

    final_response = await run_agent(runner, request.user_id, prompt)

    # Log the complete prompt and response cycle to Cloud Logging
    logger.info(
        json.dumps({
            "action": "agent_interaction",
            "agent": "BookingOrchestrator",
            "user_id": request.user_id,
            "prompt": prompt,
            "response": final_response
        })
    )

    return {"status": "confirmed", "summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
