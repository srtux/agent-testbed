import os
from google.adk.agents import LlmAgent

from ..prompt import VALIDATOR_INSTRUCTION

DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

itinerary_validator = LlmAgent(
    name="ItineraryValidator",
    model=DEFAULT_FLASH_MODEL,
    description="Validate a travel itinerary for completeness and consistency before final booking.",
    static_instruction=VALIDATOR_INSTRUCTION,
)
