import os
import logging
import httpx
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

# Relative imports from current package
from .prompt import ROOT_ROUTER_INSTRUCTION
from .sub_agents.inspiration import inspiration_agent
from .sub_agents.planning import planning_agent

logger = logging.getLogger(__name__)

DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")
DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Specialist Tools ---

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject

async def fetch_profile(member_id: str) -> dict:
    """Fetches user travel profile and preferences from Profile MCP in Cloud Run."""
    mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")
    logger.info(f"Fetching profile for {member_id} from {mcp_url}")
    
    # Standard MCP client call using sse_client
    try:
        async with sse_client(mcp_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)

                res = await session.call_tool(
                    "get_user_preferences",
                    arguments={"user_id": member_id},
                    meta=meta
                )
                if res.content and len(res.content) > 0:
                    data = res.content[0].text
                    if isinstance(data, str):
                        import json
                        return json.loads(data)
                    return data
    except Exception as e:
        logger.warning(f"FastMCP fetch_profile failed, using mock fallback: {e}")
        return {
            "home_airport": "SFO",
            "loyalty_tier": "Gold",
            "preferences": {"seat": "aisle"}
        }

    return {
        "home_airport": "SFO",
        "loyalty_tier": "Gold",
        "preferences": {"seat": "aisle"}
    }


async def extract_travel_intent(user_input: str) -> dict:
    """Analyzes the user's input to extract traveling fields (Destination, Dates)."""
    # Simply delegates or returns structured keys
    return {"destination": None, "dates": None}


# --- Intent Classifier (Sub-Agent) ---

intent_classifier = LlmAgent(
    name="IntentClassifier",
    model=DEFAULT_FLASH_MODEL,
    description="Classifies if the user is looking for Inspiration or Planning.",
    static_instruction="""Analyze the travel request and return JSON format:
    { "type": "inspiration" | "planning", "destination": "city/country" | null }
    Use 'inspiration' if they don't have a destination yet."""
)


# --- RootRouter Agent ---

agent = LlmAgent(
    name="RootRouter",
    model=DEFAULT_PRO_MODEL,
    description="Primary travel concierge agent. Authenticates and dispatches traffic.",
    static_instruction=ROOT_ROUTER_INSTRUCTION,
    tools=[
        fetch_profile,
        extract_travel_intent,
        AgentTool(agent=intent_classifier),
        AgentTool(agent=inspiration_agent),
        AgentTool(agent=planning_agent)
    ]
)
