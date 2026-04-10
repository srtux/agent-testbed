import logging
import os
from typing import AsyncGenerator

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

async def mock_generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
    logger.info(f"MOCK LLM called for model {self.model}")

    prompt = ""
    for content in llm_request.contents:
        for part in content.parts:
            if part.text:
                prompt += part.text

    logger.info(f"MOCK LLM prompt: {prompt[:100]}...")

    # Simple routing based on keywords in prompt
    if "m-12345" in prompt.lower() or "book" in prompt.lower() or "loyalty" in prompt.lower():
        resp_text = "Mock Response: Your Itinerary has been successfully booked. Confirmation: CNF-MOCK-123."
    elif "IntentClassifier" in str(llm_request) or "inspiration or planning" in prompt.lower():
        # The IntentClassifier expects a JSON response
        resp_text = '{"type": "planning", "destination": "SFO"}'
    elif "JFK" in prompt and "SFO" in prompt:
        resp_text = "Mock Response: Flight from JFK to SFO is available for $425. Hotel Cloud Suites available. Car SUV available."
    elif "weather" in prompt.lower():
        resp_text = "Mock Response: Weather in SFO is Sunny, 22C."
    else:
        resp_text = "Mock Response: Default fake response from FakeLLM."

    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text=resp_text)]
    )
    yield LlmResponse(content=content, partial=False)

if os.environ.get("USE_MOCK_LLM") == "true":
    logger.info("Monkeypatching Gemini.generate_content_async with FakeLLM")
    Gemini.generate_content_async = mock_generate_content_async
