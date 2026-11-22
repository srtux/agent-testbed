from google.adk.agents import LlmAgent

from testbed_utils.llm import build_flash_model

from ..prompt import PAYMENT_INSTRUCTION

DEFAULT_FLASH_MODEL = build_flash_model()

payment_agent = LlmAgent(
    name="PaymentAgent",
    model=DEFAULT_FLASH_MODEL,
    description="Processes mock payments and applies processing fees.",
    static_instruction=PAYMENT_INSTRUCTION,
)
