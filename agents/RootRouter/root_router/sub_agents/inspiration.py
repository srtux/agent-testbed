import os
import logging
from google.adk.agents import LlmAgent
from google.adk.tools import google_search

# Relative import from parent package
from ..prompt import INSPIRATION_INSTRUCTION

logger = logging.getLogger(__name__)
DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

place_agent = LlmAgent(
    name="PlaceAgent",
    model=DEFAULT_FLASH_MODEL,
    description="Describes the vibe and atmosphere of a destination.",
    static_instruction="""You are a travel writer describing the vibe, atmosphere, and local culture of a destination.
    Provide a rich, immersive descriptions. Highlight local spots and general 'feel' for the area.""",
)

poi_agent = LlmAgent(
    name="PoiAgent",
    model=DEFAULT_FLASH_MODEL,
    description="Describes points of interest (POI) and top attractions for a destination.",
    static_instruction="""You are a tour guide expert. Provide a prioritized list of top attractions,
    historical landmarks, and points of interest for the destination.""",
)

inspiration_agent = LlmAgent(
    name="InspirationAgent",
    model=DEFAULT_FLASH_MODEL,
    description="Helps users who don't have a destination decide on a vacation spot.",
    static_instruction=INSPIRATION_INSTRUCTION,
    tools=[google_search],
    sub_agents=[place_agent, poi_agent]
)
