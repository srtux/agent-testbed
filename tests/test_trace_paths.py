import os
import pytest
import httpx
import json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ENDPOINT = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")


@pytest.mark.asyncio
async def test_path1_profile_mcp():
    """Trace Path 1: Direct MCP SSE call to Profile_MCP."""
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession

    url = os.environ.get("PROFILE_MCP_URL", "http://localhost:8090/sse")
    if "run.app" in url:
        pytest.skip("Skipping — Cloud Run ingress is internal only.")

    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(
                    "get_user_preferences",
                    arguments={"user_id": "test_path1_user"}
                )
                assert res.content and len(res.content) > 0
                data = res.content[0].text
                assert data, "Profile MCP returned empty content"
                print(f"Profile data: {data}")
    except ConnectionError:
        pytest.skip("Profile_MCP not running locally.")


@pytest.mark.asyncio
async def test_path2_in_process_delegation():
    """Trace Path 2: Send planning prompt to RootRouter, verify planning terms in response."""
    payload = {
        "user_id": "test_path2_user",
        "prompt": "I want to plan a trip to Tokyo for next month."
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(ENDPOINT, json=payload)
            assert response.status_code == 200, f"RootRouter returned {response.status_code}"
            data = response.json()
            summary = data.get("agent_response", data.get("orchestration_summary", "")).lower()
            planning_terms = [
                "tokyo", "flight", "hotel", "itinerary", "plan",
                "travel", "trip", "book", "member", "id",
            ]
            assert any(x in summary for x in planning_terms), (
                f"Planning response missing expected terms. Got: {summary[:200]}"
            )
    except httpx.ConnectError:
        pytest.skip("RootRouter not running locally.")


@pytest.mark.asyncio
async def test_path3_bigquery_mcp():
    """Trace Path 3: Call research_destination directly (skip if no GCP creds)."""
    try:
        import google.auth
        google.auth.default()
    except Exception:
        pytest.skip("No GCP credentials available — skipping BigQuery MCP test.")

    from agents.RootRouter.root_router.sub_agents.planning import research_destination

    result = await research_destination("Tokyo", "2026-05-01 to 2026-05-10")
    assert "weather_data" in result
    assert "popularity_data" in result
    print(f"BigQuery MCP result: {json.dumps(result, indent=2)}")


@pytest.mark.asyncio
async def test_path4_flight_specialist_a2a():
    """Trace Path 4: POST directly to FlightSpecialist."""
    url = os.environ.get("FLIGHT_SPECIALIST_URL", "http://localhost:8082/chat")

    payload = {
        "user_id": "test_path4_user",
        "destination": "SFO",
        "departure_airport": "JFK",
        "dates": "2026-05-12 to 2026-05-15"
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            assert response.status_code == 200, f"FlightSpecialist returned {response.status_code}"
            data = response.json()
            response_text = str(data).lower()
            assert any(x in response_text for x in ["flight", "seat", "fare", "cost", "available"]), (
                f"FlightSpecialist response missing expected terms. Got: {response_text[:200]}"
            )
    except httpx.ConnectError:
        pytest.skip("FlightSpecialist not running locally.")


@pytest.mark.asyncio
async def test_path5_gke_specialists_a2a():
    """Trace Path 5: POST directly to Hotel + Car specialists."""
    hotel_url = os.environ.get("HOTEL_SPECIALIST_URL", "http://localhost:8084/chat")
    car_url = os.environ.get("CAR_RENTAL_SPECIALIST_URL", "http://localhost:8085/chat")

    hotel_payload = {
        "user_id": "test_path5_user",
        "destination": "SFO",
        "dates": "2026-05-12 to 2026-05-15"
    }
    car_payload = {
        "user_id": "test_path5_user",
        "destination": "SFO",
        "dates": "2026-05-12 to 2026-05-15"
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            hotel_resp = await client.post(hotel_url, json=hotel_payload)
            assert hotel_resp.status_code == 200, f"HotelSpecialist returned {hotel_resp.status_code}"
            hotel_data = str(hotel_resp.json()).lower()
            assert any(x in hotel_data for x in ["hotel", "room", "rate", "inventory", "stay"]), (
                f"HotelSpecialist response missing expected terms. Got: {hotel_data[:200]}"
            )

            car_resp = await client.post(car_url, json=car_payload)
            assert car_resp.status_code == 200, f"CarRentalSpecialist returned {car_resp.status_code}"
            car_data = str(car_resp.json()).lower()
            assert any(x in car_data for x in ["car", "rental", "vehicle", "rate", "economy"]), (
                f"CarRentalSpecialist response missing expected terms. Got: {car_data[:200]}"
            )
    except httpx.ConnectError:
        pytest.skip("Hotel/Car specialists not running locally.")


@pytest.mark.asyncio
async def test_path6_booking_orchestrator_a2a():
    """Trace Path 6: POST directly to BookingOrchestrator."""
    url = os.environ.get("BOOKING_ORCHESTRATOR_URL", "http://localhost:8081/chat")

    payload = {
        "user_id": "test_path6_user",
        "itinerary_details": json.dumps({
            "destination": "SFO",
            "flight": "CloudAir SFO-JFK $450",
            "hotel": "Cloud Suites $250/night",
            "car": "Economy $45/day",
            "days": 3,
            "loyalty_tier": "Gold"
        })
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            assert response.status_code == 200, f"BookingOrchestrator returned {response.status_code}"
            data = response.json()
            response_text = str(data).lower()
            assert any(x in response_text for x in [
                "booking", "confirm", "itinerary", "cost", "payment", "finalize"
            ]), (
                f"BookingOrchestrator response missing expected terms. Got: {response_text[:200]}"
            )
    except httpx.ConnectError:
        pytest.skip("BookingOrchestrator not running locally.")
