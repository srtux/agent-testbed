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
from pydantic import BaseModel, Field
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from fastapi import FastAPI, Request

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject


# --- Tools ---

class BookingRequest(BaseModel):
    user_id: str
    flight_id: str
    hotel_id: str
    car_id: str

async def finalize_bookings(request: BookingRequest) -> dict:
    """Finalizes all reservations using the GKE Inventory MCP server."""
    logger.info(f"Finalizing bookings for user: {request.user_id}")
    
    inventory_mcp_url = os.environ.get("INVENTORY_MCP_URL", "http://localhost:8091/sse")
    
    if inventory_mcp_url.endswith("/mcp/call_tool"):
        inventory_mcp_url = inventory_mcp_url.replace("/mcp/call_tool", "/sse")
    
    # Trace edge: BookingOrchestrator -> GKE MCP using official FastMCP Session
    try:
        async with sse_client(inventory_mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)  # Propagate W3C traceparent into the _meta object
                
                res = await session.call_tool(
                    "commit_booking", 
                    arguments=request.model_dump(),
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        return json.loads(data)
                    return data
    except Exception as e:
        logger.warning(f"FastMCP call failed, mocking response natively: {e}")
        return {"status": "success", "confirmation": "CNF-12345"}
    
    return {"status": "success", "confirmation": "CNF-12345"}

# --- Agent ---

agent = LlmAgent(
    name="BookingOrchestrator",
    model=DEFAULT_PRO_MODEL,
    static_instruction="You are the Booking Orchestrator. Finalize the plans by using the `finalize_bookings` tool, then summarize the confirmation details back.",
    tools=[finalize_bookings],
)

# For Vertex AI Agent Engine, we expose `agent`.
# If we want to simulate an A2A HTTP endpoint natively, we wrap it in FastAPI.
runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class OrchestrationRequest(BaseModel):
    user_id: str
    itinerary_details: str

@app.post("/chat")
async def chat_endpoint(request: OrchestrationRequest):
    logger.info(f"BookingOrchestrator received confirmed plans for user {request.user_id}")
    prompt = f"Please finalize the following itinerary and summarize: {request.itinerary_details} for user {request.user_id}"
    
    final_response = None
    async for event in runner.run_async(user_id=request.user_id, session_id="default", new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text
                    
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
    uvicorn.run(app, host="0.0.0.0", port=8080)
