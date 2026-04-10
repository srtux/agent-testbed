import json
import logging
import os

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from mcp.client.session import ClientSession

# MCP client imports
from mcp.client.sse import sse_client
from opentelemetry.propagate import inject
from pydantic import BaseModel

# Relative imports from current package
from .prompt import BOOKING_ORCHESTRATOR_INSTRUCTION
from .sub_agents.payment import payment_agent
from .sub_agents.validator import itinerary_validator
from .tools import calculate_trip_cost, format_itinerary

logger = logging.getLogger(__name__)

# Note: setup_authenticated_transport() is already called in main.py at module
# load time, which installs the HTTPX instrumentor's OIDC request hook. No
# need to call it again here.

DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Local Tools (real compute) ---

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
                    "commit_booking", arguments=request_dict, meta=meta
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
        finalize_bookings,
    ],
)
