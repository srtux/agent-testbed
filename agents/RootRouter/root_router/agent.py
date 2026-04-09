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

from testbed_utils.telemetry import setup_authenticated_transport
setup_authenticated_transport()

DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")
DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Specialist Tools ---

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
from opentelemetry.propagate import inject
import google.auth
import google.auth.transport.requests
from google.oauth2 import id_token

async def fetch_profile(member_id: str) -> dict:
    """Fetches user travel profile and preferences from Profile MCP in Cloud Run."""
    mcp_url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")
    audience = os.environ.get("PROFILE_MCP_AUDIENCE")
    logger.info(f"Fetching profile for {member_id} from {mcp_url}")
    
    headers = {}
    if audience:
        try:
            logger.info(f"Fetching OIDC token for audience: {audience}")
            auth_req = google.auth.transport.requests.Request()
            token = id_token.fetch_id_token(auth_req, audience)
            headers["Authorization"] = f"Bearer {token}"
            # Extract host from audience URL for Cloud Run routing via PSC
            host = audience.replace("https://", "").replace("http://", "").split("/")[0]
            headers["Host"] = host
            logger.info(f"Successfully fetched OIDC token for {audience}, set Host header to {host}")
        except Exception as e:
            logger.warning(f"Failed to fetch OIDC token for {audience}: {e}")
    
    # Standard MCP client call using sse_client
    try:
        async with sse_client(mcp_url, headers=headers) as (read, write):
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
    except Exception:
        logger.exception("FastMCP fetch_profile failed, using mock fallback")
        return {
            "home_airport": "SFO",
            "loyalty_tier": "Gold",
            "preferences": {"seat": "aisle"}
        }


async def extract_travel_intent(user_input: str) -> dict:
    """Analyzes the user's input to extract traveling fields (Destination, Dates).

    Returns a dict with 'destination' and 'dates' keys extracted from the input.
    The LLM calling this tool should provide the user_input verbatim so
    downstream routing can determine inspiration vs. planning paths.
    """
    import re

    # Simple heuristic extraction — the LLM can refine via IntentClassifier
    destination = None
    dates = None

    # Look for date-like patterns (YYYY-MM-DD, Month Day, etc.)
    date_pattern = re.findall(
        r'\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}',
        user_input, re.IGNORECASE
    )
    if date_pattern:
        dates = ", ".join(date_pattern)

    # Return what we found — LLM uses IntentClassifier for full classification
    return {"destination": destination, "dates": dates, "raw_input": user_input}


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
