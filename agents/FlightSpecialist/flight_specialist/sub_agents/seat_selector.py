from google.adk.agents import LlmAgent

from testbed_utils.llm import build_flash_model

from ..prompt import SEAT_SELECTOR_INSTRUCTION

DEFAULT_FLASH_MODEL = build_flash_model()

seat_selector = LlmAgent(
    name="SeatSelector",
    model=DEFAULT_FLASH_MODEL,
    description="Select optimal seat based on user preferences and flight details.",
    static_instruction=SEAT_SELECTOR_INSTRUCTION,
)
