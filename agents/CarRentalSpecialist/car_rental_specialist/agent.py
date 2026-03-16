import os
import json
import logging
from google.adk.agents import LlmAgent

# Relative imports from current package
from .prompt import CAR_RENTAL_SPECIALIST_INSTRUCTION

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject

logger = logging.getLogger(__name__)

DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Local Tool ---

async def calculate_rental_price(car_class: str, days: int, loyalty_tier: str) -> dict:
    """Calculate rental price based on car class, duration, and loyalty tier."""
    from testbed_utils.config import CAR_RATE_TABLE, LOYALTY_DISCOUNTS
    daily_rate = CAR_RATE_TABLE.get(car_class.lower(), 70)
    subtotal = daily_rate * days
    discount_pct = LOYALTY_DISCOUNTS.get(loyalty_tier, 0)
    total = round(subtotal * (1 - discount_pct), 2)
    return {
        "car_class": car_class, "daily_rate": daily_rate, "days": days,
        "subtotal": subtotal, "loyalty_discount_pct": discount_pct * 100,
        "total": total,
    }


# --- MCP Delegation Tool ---

async def check_loyalty_status(user_id: str) -> dict:
    """Check user's car rental loyalty status via CR Profile MCP."""
    logger.info(f"Checking car rental loyalty status for {user_id}")

    profile_mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")

    try:
        async with sse_client(profile_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object

                res = await session.call_tool(
                    "get_user_preferences",
                    arguments={"user_id": user_id},
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        return json.loads(data)
                    return data
    except Exception as e:
        logger.warning(f"FastMCP call to user profile failed natively: {e}")
        return {"loyalty_tier": "Silver"}


# --- Agent ---

agent = LlmAgent(
    name="CarRentalSpecialist",
    model=DEFAULT_PRO_MODEL,
    static_instruction=CAR_RENTAL_SPECIALIST_INSTRUCTION,
    tools=[calculate_rental_price, check_loyalty_status],
)
