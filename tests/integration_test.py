import os
import pytest
import httpx
import json
from dotenv import load_dotenv

# Ensure environment vars from .env are loaded (contains GOOGLE_CLOUD_PROJECT)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Setup the endpoint depending on whether this is local or remote
ENDPOINT = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")

@pytest.mark.asyncio
async def test_full_agent_orchestration():
    """
    Sends a complex master prompt to the RootRouter.
    The goal is to trigger the full distributed waterfall.
    """
    print(f"\nSending payload to {ENDPOINT}")

    prompt_text = "I need to travel to SFO for a convention next Tuesday and return next Friday. Can you build the entire itinerary?"
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
        response = ae.stream_query(
            user_id=user_id,
            message=prompt_text
        )

        final_response = ""
        for event in response:
            # Handle both dictionary (AgentEngine) and object (local runner) formats safely
            is_dict = isinstance(event, dict)
            content = event.get("content") if is_dict else getattr(event, "content", None)

            if not content:
                continue
            parts = content.get("parts", []) if is_dict else getattr(content, "parts", [])
            if not parts:
                continue
            for part in parts:
                part_text = part.get("text") if is_dict else getattr(part, "text", None)
                if part_text:
                    print(part_text, end="", flush=True)
                    final_response += part_text

        assert final_response, "No response from Reasoning Engine."
        data = {"status": "complete", "orchestration_summary": final_response}

    else:
        payload = {
            "user_id": user_id,
            "prompt": prompt_text
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(ENDPOINT, json=payload)

            # 1. We successfully connected to the router
            assert response.status_code == 200, f"Router failed with status {response.status_code}: {response.text}"

            data = response.json()
            print(f"\nRouter Response:\n{json.dumps(data, indent=2)}")

            # 2. It successfully finalized
            assert data.get("status") == "complete", "Did not complete successfully."

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
        "sfo", "san francisco", "sf", "bay area",
        "cloud suites", "flight", "hotel", "itinerary",
    ]
    assert any(x in summary for x in destination_terms), (
        f"Summary did not contain any expected destination/travel terms. Got: {summary[:200]}"
    )


@pytest.mark.asyncio
async def test_flight_specialist_isolated():
    """Tests the FlightSpecialist endpoint directly."""
    url = os.environ.get("FLIGHT_SPECIALIST_URL")
    if not url:
        pytest.skip("FLIGHT_SPECIALIST_URL not set in environment.")

    payload = {
        "user_id": "test_user_isolated",
        "destination": "SFO",
        "departure_airport": "JFK",
        "dates": "next week"
    }

    print(f"\nEvaluating isolated call to FlightSpecialist: {url}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "flight" in str(data).lower() or "recommend" in str(data).lower() or "itinerary" in str(data).lower()


@pytest.mark.asyncio
async def test_hotel_specialist_isolated():
    """Tests the HotelSpecialist endpoint directly."""
    url = os.environ.get("HOTEL_SPECIALIST_URL")
    if not url:
        pytest.skip("HOTEL_SPECIALIST_URL not set in environment.")

    payload = {
        "user_id": "test_user_isolated",
        "prompt": "I need a luxury hotel in SFO"
    }

    print(f"\nEvaluating isolated call to HotelSpecialist: {url}")
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Hotel Specialist usually forwards to chain if needed, but accepts isolated requests
        response = await client.post(url, json=payload)
        assert response.status_code == 200
        data = response.json()
        assert any(x in str(data).lower() for x in ["hotel", "room", "stay", "itinerary", "summary"])


@pytest.mark.asyncio
async def test_profile_mcp_isolated():
    """Tests the Profile_MCP server tool calling directly."""
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession

    url = os.environ.get("PROFILE_MCP_URL")
    if not url:
        pytest.skip("PROFILE_MCP_URL not set in environment.")

    print(f"\nEvaluating isolated FastMCP call to Profile_MCP: {url}")
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool("get_user_preferences", arguments={"user_id": "test_user"})
                assert res.content and len(res.content) > 0
                print(f"Profile data: {res.content[0].text}")
    except Exception as e:
        pytest.fail(f"FastMCP isolated test failed: {e}")
