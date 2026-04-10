from testbed_utils import mock_llm  # noqa: F401 # Must be before ADK imports
from testbed_utils.logging import setup_logging
from testbed_utils.telemetry import setup_telemetry

setup_telemetry()
logger = setup_logging()

import json
import os
import sys
import uuid

from fastapi import FastAPI
from google.adk.runners import InMemoryRunner
from google.genai import types
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

# Add local directory to sys.path so 'flight_specialist' can be imported absolutely
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from flight_specialist.agent import agent

runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()

# Instrument FastAPI to automatically extract W3C `traceparent` headers
FastAPIInstrumentor.instrument_app(app)


class ChatRequest(BaseModel):
    user_id: str
    destination: str
    departure_airport: str | None = None
    dates: str
    profile_context: dict | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info(
        f"Received request to process flights for {request.destination} (User: {request.user_id})"
    )

    pref_context = json.dumps(request.profile_context or {})[:1000]
    prompt = f"User {request.user_id} wants a flight from {request.departure_airport} to {request.destination} for {request.dates}. Preferences context: {pref_context}. Coordinate with Hotel and Weather specialists."

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

    logger.info(
        f"Flight Specialist completed for user {request.user_id}. Response: {final_response}"
    )
    return {"agent_response": final_response}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8082)
