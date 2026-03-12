from testbed_utils.telemetry import setup_telemetry
from testbed_utils.logging import setup_logging
from testbed_utils.config import DEFAULT_PRO_MODEL

setup_telemetry()
logger = setup_logging()

import sys
import os
import json
import uuid
from fastapi import FastAPI
from pydantic import BaseModel
from google.genai import types
from google.adk.runners import InMemoryRunner
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Add local directory to sys.path so 'hotel_specialist' can be imported absolutely
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from hotel_specialist.agent import agent

runner = InMemoryRunner(agent=agent)
runner.auto_create_session = True
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)

class HotelRequest(BaseModel):
    user_id: str
    destination: str
    dates: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat_endpoint(request: HotelRequest):
    logger.info(f"Hotel Specialist coordinating lodging at {request.destination}")
    prompt = f"Find a hotel at {request.destination} for {request.dates}. Return hotel inventory and rate details. User: {request.user_id}."

    final_response = None
    async for event in runner.run_async(user_id=request.user_id, session_id=str(uuid.uuid4()), new_message=types.Content(role="user", parts=[types.Part.from_text(text=prompt)])):
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if part.text:
                    final_response = (final_response or "") + part.text

    return {"status": "complete", "hotel_summary": final_response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8084)
