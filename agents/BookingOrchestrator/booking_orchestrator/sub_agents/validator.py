from google.adk.agents import LlmAgent

from testbed_utils.llm import build_flash_model

from ..prompt import VALIDATOR_INSTRUCTION

DEFAULT_FLASH_MODEL = build_flash_model()

itinerary_validator = LlmAgent(
    name="ItineraryValidator",
    model=DEFAULT_FLASH_MODEL,
    description="Validate a travel itinerary for completeness and consistency before final booking.",
    static_instruction=VALIDATOR_INSTRUCTION,
)
