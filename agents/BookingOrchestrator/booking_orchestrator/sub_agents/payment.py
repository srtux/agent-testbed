import os

from google.adk.agents import LlmAgent

from ..prompt import PAYMENT_INSTRUCTION

DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

payment_agent = LlmAgent(
    name="PaymentAgent",
    model=DEFAULT_FLASH_MODEL,
    description="Processes mock payments and applies processing fees.",
    static_instruction=PAYMENT_INSTRUCTION,
)
