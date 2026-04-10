from testbed_utils import mock_llm  # noqa: F401 # Must be before ADK imports
from testbed_utils.logging import setup_logging
from testbed_utils.telemetry import setup_telemetry

setup_telemetry()
logger = setup_logging()

import os
import sys
import uuid

from fastapi import FastAPI
from google.adk.runners import InMemoryRunner
from google.genai import types
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

# Add local directory to sys.path so 'weather_specialist' can be imported absolutely
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from weather_specialist.agent import agent

runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)


class WeatherRequest(BaseModel):
    user_id: str
    destination: str
    itinerary_so_far: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat")
async def chat_endpoint(request: WeatherRequest):
    logger.info(
        f"Weather Specialist checking conditions for {request.destination} for user {request.user_id}"
    )
    itinerary_context = (request.itinerary_so_far or "")[:2000]
    prompt = f"Check weather for {request.destination}. Current itinerary: {itinerary_context}. User: {request.user_id}. Finalize with Booking Orchestrator."

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
        f"Weather Specialist completed for user {request.user_id}. Response: {final_response}"
    )
    return {"status": "complete", "weather_agent_summary": final_response}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8083)
