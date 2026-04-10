import json
import logging
import os

import httpx
from google.adk.agents import LlmAgent
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from opentelemetry.propagate import inject

# Relative imports from current package
from .prompt import WEATHER_SPECIALIST_INSTRUCTION

logger = logging.getLogger(__name__)

DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Local Tool ---


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
    return {
        "suggested_items": items,
        "based_on": {"temp_c": temperature_c, "condition": condition},
    }


# --- MCP Delegation Tool ---


async def fetch_weather(user_id: str, location: str) -> dict:
    """Mock weather endpoint acting as an edge to GKE MCP Inventory."""
    logger.info(f"Checking weather for {location} (User: {user_id})")

    inventory_mcp_url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8091/sse")

    try:
        async with sse_client(inventory_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object

                res = await session.call_tool(
                    "get_weather", arguments={"location": location}, meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        return json.loads(data)
                    return data
    except Exception as e:
        logger.warning(f"FastMCP mock weather failed natively due to: {e}")
        return {"condition": "Sunny", "temperature_c": 22}


# --- A2A HTTP Delegation Tool ---


async def delegate_to_booking_orchestrator(
    user_id: str, itinerary_details: str
) -> dict:
    """Sends finalized travel plans to the Booking Orchestrator."""
    logger.info(f"Delegating final confirmation to Booking Orchestrator for {user_id}")
    booking_orch_url = os.environ.get(
        "BOOKING_ORCHESTRATOR_URL", "http://localhost:8081/chat"
    )

    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "itinerary_details": itinerary_details}
        res = await client.post(booking_orch_url, json=payload, timeout=60.0)
        return res.json()


# --- Agent ---
agent = LlmAgent(
    name="WeatherSpecialist",
    model=DEFAULT_PRO_MODEL,
    static_instruction=WEATHER_SPECIALIST_INSTRUCTION,
    tools=[suggest_packing, fetch_weather, delegate_to_booking_orchestrator],
)
