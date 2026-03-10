# main.py MUST come before other imports for OTel patching
# ruff: noqa: E402
from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_PRO_MODEL

setup_telemetry()
logger = setup_logging()
import os
import sys
import logging
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


# --- Tools --

async def check_loyalty_status(user_id: str) -> dict:
    """Check user's car rental loyalty status via CR Profile MCP."""
    logger.info(f"Checking car rental loyalty status for {user_id}")
    
    profile_mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")
    
    if profile_mcp_url.endswith("/mcp/call_tool"):
        profile_mcp_url = profile_mcp_url.replace("/mcp/call_tool", "/sse")
        
    # GKE -> CR Profile MCP edge over FastMCP Session
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
        
    return {"loyalty_tier": "Silver"}

# --- Agent ---
agent = LlmAgent(
    name="CarRentalSpecialist",
    model=DEFAULT_PRO_MODEL, 
    static_instruction="""You are the Car Rental Specialist. 
    1. Check the user's loyalty status.
    2. Propose a rental car based on the tier.
    3. Return the summary.""",
    tools=[check_loyalty_status],
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

@app.post("/chat")
async def chat_endpoint(request: CarRequest):
    logger.info(f"Car Rental Specialist securing a vehicle at {request.destination}")
    prompt = f"Find a rental car at {request.destination} for {request.dates}. User: {request.user_id}."
    
    final_response = None
    async for event in runner.run_async(user_id=request.user_id, session_id="default", new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text
                    
    return {"status": "complete", "car_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
