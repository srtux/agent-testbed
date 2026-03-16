from testbed_utils.telemetry import setup_authenticated_transport
from testbed_utils.logging import setup_logging
import os

setup_authenticated_transport()

# Agent Engine platform handles telemetry in production.
# For local dev / verification, we initialize it manually if not explicitly disabled/enabled by platform.
if os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "false").lower() != "true":
    from testbed_utils.telemetry import setup_telemetry
    setup_telemetry()

logger = setup_logging()


import sys
import json
import logging
import uuid
from fastapi import FastAPI
from pydantic import BaseModel
from google.genai import types

# Add local directory to sys.path so 'root_router' can be imported absolutely
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from root_router.agent import agent

from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class RouterRequest(BaseModel):
    user_id: str
    prompt: str
    session_id: str | None = None

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: RouterRequest):
    logger.info(f"RootRouter received message from user {request.user_id}")



    # Use existing session_id if provided, else generate new
    current_session = request.session_id or str(uuid.uuid4())

    final_response = None
    async for event in runner.run_async(
        user_id=request.user_id, 
        session_id=current_session, 
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=request.prompt)])
    ):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    # Log interaction
    logger.info(
        json.dumps({
            "action": "agent_interaction",
            "agent": "RootRouter",
            "user_id": request.user_id,
            "session_id": current_session,
            "prompt": request.prompt,
            "response": final_response
        })
    )

    return {
        "status": "complete" if "Itinerary" in (final_response or "") or "Finalized" in (final_response or "") else "in_progress",
        "orchestration_summary": final_response,
        "session_id": current_session
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
