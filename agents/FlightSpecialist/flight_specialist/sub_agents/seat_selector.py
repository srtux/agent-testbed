import os

from google.adk.agents import LlmAgent

from ..prompt import SEAT_SELECTOR_INSTRUCTION

DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

seat_selector = LlmAgent(
    name="SeatSelector",
    model=DEFAULT_FLASH_MODEL,
    description="Select optimal seat based on user preferences and flight details.",
    static_instruction=SEAT_SELECTOR_INSTRUCTION,
)
