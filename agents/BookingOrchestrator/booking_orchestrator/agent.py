import os
import json
import logging
from pydantic import BaseModel
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

# Relative imports from current package
from .prompt import BOOKING_ORCHESTRATOR_INSTRUCTION
from .sub_agents.validator import itinerary_validator
from .sub_agents.payment import payment_agent

# MCP client imports
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject

logger = logging.getLogger(__name__)

from testbed_utils.telemetry import setup_authenticated_transport
setup_authenticated_transport()

DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Local Tools (real compute) ---

async def calculate_trip_cost(flight_cost: float, hotel_cost: float, car_cost: float, days: int, loyalty_tier: str) -> dict:
    """Aggregate costs from flight, hotel, and car rental. Apply loyalty discounts."""
    LOYALTY_DISCOUNTS = {
        "Gold": 0.15, "Silver": 0.10, "Bronze": 0.05,
    }
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


# --- MCP Delegation Tool ---

class BookingRequest(BaseModel):
    user_id: str
    flight_id: str = ""
    hotel_id: str = ""
    car_id: str = ""

async def finalize_bookings(request: BookingRequest) -> dict:
    """Finalizes all reservations using the GKE Inventory MCP server."""
    is_dict = isinstance(request, dict)
    user_id = request.get("user_id", "") if is_dict else getattr(request, "user_id", "")
    request_dict = request if is_dict else request.model_dump()

    logger.info(f"Finalizing bookings for user: {user_id}")

    inventory_mcp_url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8091/sse")

    try:
        async with sse_client(inventory_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object

                res = await session.call_tool(
                    "commit_booking",
                    arguments=request_dict,
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        data = json.loads(data)
                    logger.info(f"Inventory MCP response for {user_id}: {data}")
                    return data
    except Exception as e:
        logger.warning(f"FastMCP call failed, mocking response natively: {e}")
        mock_res = {"status": "success", "confirmation": "CNF-12345"}
        logger.info(f"Returning mock response for {user_id}: {mock_res}")
        return mock_res


agent = LlmAgent(
    name="BookingOrchestrator",
    model=DEFAULT_PRO_MODEL,
    static_instruction=BOOKING_ORCHESTRATOR_INSTRUCTION,
    tools=[
        calculate_trip_cost, 
        format_itinerary, 
        AgentTool(agent=itinerary_validator), 
        AgentTool(agent=payment_agent), 
        finalize_bookings
    ],
)
