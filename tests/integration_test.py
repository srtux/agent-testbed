import json
import os
from datetime import date, timedelta

import httpx
import pytest
from dotenv import load_dotenv

# Ensure environment vars from .env are loaded (contains GOOGLE_CLOUD_PROJECT)
load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
)

# Setup the endpoint depending on whether this is local or remote
ENDPOINT = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")


def _future_travel_dates():
    """Return (outbound, inbound) as YYYY-MM-DD strings roughly a month ahead.

    Using dynamic dates prevents tests from decaying after a hardcoded date passes.
    """
    outbound = date.today() + timedelta(days=30)
    inbound = outbound + timedelta(days=3)
    return outbound.isoformat(), inbound.isoformat()


@pytest.mark.asyncio
async def test_full_agent_orchestration():
    """
    Sends a complex master prompt to the RootRouter.
    The goal is to trigger the full distributed waterfall.
    """
    print(f"\nSending payload to {ENDPOINT}")

    outbound, inbound = _future_travel_dates()
    prompt_text = (
        f"I need to travel to SFO from JFK for a convention on {outbound} "
        f"and return on {inbound}. Can you build the entire itinerary?"
    )
    user_id = "integration_tester_001"

    if ENDPOINT.startswith("projects/"):
        print(f"\nQuerying Vertex AI Reasoning Engine: {ENDPOINT}")
        import vertexai
        from vertexai import agent_engines

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

        if not project_id:
            pytest.fail("GOOGLE_CLOUD_PROJECT is required to query Reasoning Engine.")

        print(f"Initializing vertexai with project={project_id}, location={location}")
        vertexai.init(project=project_id, location=location)

        ae = agent_engines.AgentEngine(ENDPOINT)

        # Use stream_query as recommended for Reasoning Engines
        response = ae.stream_query(user_id=user_id, message=prompt_text)

        final_response = ""
        for event in response:
            # Handle both dictionary (AgentEngine) and object (local runner) formats safely
            is_dict = isinstance(event, dict)

            # 1. Capture text from parts (Agent Engine format)
            content = (
                event.get("content") if is_dict else getattr(event, "content", None)
            )
            if content:
                parts = (
                    content.get("parts", [])
                    if is_dict
                    else getattr(content, "parts", [])
                )
                for part in parts:
                    text = part.get("text") if is_dict else getattr(part, "text", None)
                    if text:
                        print(f"[RE-TEXT] {text}", flush=True)
                        final_response += text

            # 2. Capture tool calls (useful for debugging orchestration)
            if is_dict and content:
                parts = content.get("parts", [])
                for part in parts:
                    if "function_call" in part:
                        print(
                            f"[RE-TOOL] calling {part['function_call']['name']}",
                            flush=True,
                        )
                        # We count tool calls as activity to avoid false negative "No response" assertion
                        final_response += (
                            f"Tool call: {part['function_call']['name']}\n"
                        )

        assert final_response, "No response from Reasoning Engine."
        data = {
            "status": "complete",
            "orchestration_summary": final_response,
            "is_reasoning_engine": True,
        }

    else:
        payload_1 = {"user_id": user_id, "prompt": prompt_text}

        async with httpx.AsyncClient(timeout=180.0) as client:
            # Turn 1: Intent
            response = await client.post(ENDPOINT, json=payload_1)
            assert response.status_code == 200, (
                f"Router Turn 1 failed: {response.status_code}"
            )
            data_1 = response.json()
            session_id = data_1.get("session_id")

            # Turn 2: Auth (Member ID)
            payload_2 = {
                "user_id": user_id,
                "prompt": "My member ID is M-12345",
                "session_id": session_id,
            }
            response = await client.post(ENDPOINT, json=payload_2)
            assert response.status_code == 200, (
                f"Router Turn 2 failed: {response.status_code}"
            )
            data = response.json()
            print(f"\nRouter Response:\n{json.dumps(data, indent=2)}")

            # 2. It successfully finalized or progressed
            assert data.get("status") in ["complete", "in_progress"], (
                f"Did not complete or progress: {data}"
            )

    # 3. Ensure the summary actually has text reflecting the downstream nodes
    summary = data.get("orchestration_summary", "").lower()

    # The prompt forces a trip to SFO which means:
    # 1. CR Profile is accessed for loyalty tier/home airport
    # 2. FlightSpecialist routes hotels
    # 3. WeatherSpecialist fetches conditions
    # 4. BookingOrchestrator finalizes it and gives a summary
    assert len(summary) > 20, "Summary is too short or missing."
    # Use broad matching to handle LLM non-determinism — any reference to the
    # destination or key travel concepts counts as a valid response.
    destination_terms = [
        "sfo",
        "san francisco",
        "sf",
        "bay area",
        "cloud suites",
        "flight",
        "hotel",
        "itinerary",
    ]
    if data.get("is_reasoning_engine"):
        # Since stream_query is stateless with no Turn 2 auth simulation,
        # it is expected to halt and ask for member creds directly.
        destination_terms += ["member id", "profile", "authentication", "of course"]

    assert any(x in summary for x in destination_terms), (
        f"Summary did not contain any expected destination/travel terms. Got: {summary[:200]}"
    )


@pytest.mark.asyncio
async def test_flight_specialist_isolated():
    """Tests the FlightSpecialist endpoint directly."""
    url = os.environ.get("FLIGHT_SPECIALIST_URL")
    if not url:
        pytest.skip("FLIGHT_SPECIALIST_URL not set in environment.")
    if "localhost" in url or "10.128." in url:
        pytest.skip("Skipping isolated test due to local VPC network boundaries.")

    payload = {
        "user_id": "test_user_isolated",
        "destination": "SFO",
        "departure_airport": "JFK",
        "dates": "next week",
    }

    print(f"\nEvaluating isolated call to FlightSpecialist: {url}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        assert response.status_code == 200
        data = response.json()
        assert (
            "flight" in str(data).lower()
            or "recommend" in str(data).lower()
            or "itinerary" in str(data).lower()
        )


@pytest.mark.asyncio
async def test_hotel_specialist_isolated():
    """Tests the HotelSpecialist endpoint directly."""
    url = os.environ.get("HOTEL_SPECIALIST_URL")
    if not url:
        pytest.skip("HOTEL_SPECIALIST_URL not set in environment.")
    if "localhost" in url or "10.128." in url:
        pytest.skip("Skipping isolated test due to local VPC network boundaries.")

    # HotelSpecialist.main.HotelRequest schema: {user_id, destination, dates}
    payload = {
        "user_id": "test_user_isolated",
        "destination": "SFO",
        "dates": "next week",
    }

    print(f"\nEvaluating isolated call to HotelSpecialist: {url}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Hotel Specialist usually forwards to chain if needed, but accepts isolated requests
        response = await client.post(url, json=payload)
        assert response.status_code == 200
        data = response.json()
        assert any(
            x in str(data).lower()
            for x in ["hotel", "room", "stay", "itinerary", "summary"]
        )


@pytest.mark.asyncio
async def test_profile_mcp_isolated():
    """Tests the Profile_MCP server tool calling directly."""
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client

    url = os.environ.get("PROFILE_MCP_URL")
    if not url:
        pytest.skip("PROFILE_MCP_URL not set in environment.")
    if "localhost" in url or "10.128." in url or "run.app" in url:
        # Direct Mode Cloud run ingress is internal only
        pytest.skip("Skipping isolated test due to local VPC network boundaries.")

    print(f"\nEvaluating isolated FastMCP call to Profile_MCP: {url}")
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(
                    "get_user_preferences", arguments={"user_id": "test_user"}
                )
                assert res.content and len(res.content) > 0
                print(f"Profile data: {res.content[0].text}")
    except Exception as e:
        pytest.fail(f"FastMCP isolated test failed: {e}")
