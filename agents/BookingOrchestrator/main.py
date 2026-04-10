import os

from testbed_utils import mock_llm  # noqa: F401 # Must be before ADK imports
from testbed_utils.logging import setup_logging
from testbed_utils.telemetry import setup_authenticated_transport

setup_authenticated_transport()

# Agent Engine platform handles telemetry in production.

logger = setup_logging()


import json
import sys
import uuid

from fastapi import FastAPI
from google.genai import types
from pydantic import BaseModel

# Add local directory to sys.path so the 'booking_orchestrator' package can be imported absolutely
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from booking_orchestrator.agent import agent
from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)


class OrchestrationRequest(BaseModel):
    user_id: str
    itinerary_details: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat_endpoint(request: OrchestrationRequest):
    logger.info(
        f"BookingOrchestrator received confirmed plans for user {request.user_id}"
    )
    prompt = f"Please finalize the following itinerary and summarize: {request.itinerary_details} for user {request.user_id}"

    final_response = None
    async for event in runner.run_async(
        user_id=request.user_id,
        session_id=str(uuid.uuid4()),
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=prompt)]
        ),
    ):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    # Log the complete prompt and response cycle to Cloud Logging
    logger.info(
        json.dumps(
            {
                "action": "agent_interaction",
                "agent": "BookingOrchestrator",
                "user_id": request.user_id,
                "prompt": prompt,
                "response": final_response,
            }
        )
    )

    return {"status": "confirmed", "summary": final_response}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
