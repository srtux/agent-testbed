# agent.py MUST come before other imports for OTel patching
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
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject

# --- Tools and Delegation ---

class FlightRequest(BaseModel):
    user_id: str = Field(description="The unique user ID for the request")
    destination: str = Field(description="The destination airport code (e.g., SFO, JFK)")
    departure_airport: str = Field(default="", description="The departure airport code if known")
    dates: str = Field(description="The travel dates")

async def consult_flight_specialist(request: FlightRequest) -> dict:
    """Delegates the flight booking task to the FlightSpecialist sub-agent."""
    # This URL would typically come from environment variables
    flight_specialist_url = os.environ.get("FLIGHT_SPECIALIST_URL", "http://localhost:8082/chat")
    profile_mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")
    
    if profile_mcp_url.endswith("/mcp/call_tool"):
        profile_mcp_url = profile_mcp_url.replace("/mcp/call_tool", "/sse")
    
    logger.info(f"Checking user profile via FastMCP for user: {request.user_id}, destination: {request.destination}")
    
    profile_data = {"preferences": "Unknown"}
    # Trace edge: AE -> CR MCP using official FastMCP Session
    try:
        async with sse_client(profile_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object
                
                res = await session.call_tool(
                    "get_user_preferences", 
                    arguments={"user_id": request.user_id},
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    profile_data = res.content[0].text
                    if isinstance(profile_data, str):
                        try:
                            parsed_data = json.loads(profile_data)
                            if isinstance(parsed_data, dict):
                                profile_data = parsed_data
                            else:
                                profile_data = {"data": parsed_data}
                        except Exception:
                            profile_data = {"raw_text": profile_data}
    except Exception as e:
        logger.warning(f"FastMCP call failed: {e}")
        profile_data = {"error": str(e)}
    request_dict = request.model_dump()
    request_dict["profile_context"] = profile_data
    
    logger.info(f"Delegating to FlightSpecialist for destination: {request.destination}")
    
    # Trace edge: AE -> CR
    async with httpx.AsyncClient() as client:
        # In a real environment, we would obtain an OIDC token here for auth
        response = await client.post(
            flight_specialist_url, 
            json=request_dict,
            timeout=60.0
        )
        if response.status_code != 200:
            logger.error(f"Failed to delegate to FlightSpecialist. Status: {response.status_code}, Response: {response.text}")
        response.raise_for_status()
        return response.json()


# --- Agent Definition ---

agent = LlmAgent(
    name="RootRouter",
    model=DEFAULT_PRO_MODEL,
    static_instruction="""You are the Root Router for an Enterprise Travel Concierge. 
    You manage the transaction state across various sub-agents. Find flights via the Flight Specialist tool.
    
    Ensure you gather the user's information and trigger the master itinerary planner correctly. Do not ask the user for their departure airport if it's missing; just pass an empty string to the tool.""",
    tools=[consult_flight_specialist],
)

# For Vertex AI Agent Engine, you typically don't need to wrap in FastAPI if using the platform's native endpoints.
# However, if we want to simulate the entrypoint or handle webhooks, we can.
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class RouterRequest(BaseModel):
    user_id: str
    prompt: str

@app.post("/chat")
async def chat_endpoint(request: RouterRequest):
    logger.info(f"RootRouter Received root prompt for {request.user_id}")
    
    final_response = None
    prompt_text = f"[System Context: The current user's ID is '{request.user_id}']\n{request.prompt}"
    async for event in runner.run_async(user_id=request.user_id, session_id="default", new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text
                    
    return {"status": "complete", "orchestration_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
