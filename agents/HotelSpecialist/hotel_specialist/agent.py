import os
import json
import logging
from google.adk.agents import LlmAgent

# Relative imports from current package
from .prompt import HOTEL_SPECIALIST_INSTRUCTION

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject

logger = logging.getLogger(__name__)

DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Local Tool ---

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

# --- Agent ---
agent = LlmAgent(
    name="HotelSpecialist",
    model=DEFAULT_PRO_MODEL,
    static_instruction=HOTEL_SPECIALIST_INSTRUCTION,
    tools=[calculate_nightly_rate, fetch_hotel_inventory],
)
