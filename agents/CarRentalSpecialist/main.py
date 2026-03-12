# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_PRO_MODEL

setup_telemetry()
logger = setup_logging()

import os

from fastapi import FastAPI
from pydantic import BaseModel
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from testbed_utils.mcp_client import call_mcp_tool
from testbed_utils.runner import run_agent


# --- Local Tool (real compute) ---

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

    return await call_mcp_tool(
        profile_mcp_url, "get_user_preferences",
        {"user_id": user_id},
        fallback={"loyalty_tier": "Silver"},
    )

# --- Agent ---
agent = LlmAgent(
    name="CarRentalSpecialist",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Car Rental Specialist.
    1. Check the user's loyalty status via check_loyalty_status.
    2. Calculate the rental price using calculate_rental_price based on the loyalty tier.
    3. Propose a rental car based on the tier and calculated price.
    4. Return the summary.""",
    tools=[calculate_rental_price, check_loyalty_status],
)

# --- FastAPI App ---
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class CarRequest(BaseModel):
    user_id: str
    destination: str
    dates: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: CarRequest):
    logger.info(f"Car Rental Specialist securing a vehicle at {request.destination}")
    prompt = f"Find a rental car at {request.destination} for {request.dates}. User: {request.user_id}."

    final_response = await run_agent(runner, request.user_id, prompt)
    return {"status": "complete", "car_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)
