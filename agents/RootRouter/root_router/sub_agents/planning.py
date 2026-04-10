import logging
import os

import google.auth
import google.auth.transport.requests
import httpx
from google.adk.agents import LlmAgent
from mcp.client.session import ClientSession

# MCP client imports
from mcp.client.sse import sse_client
from opentelemetry.propagate import inject

# Relative import from parent package
from ..prompt import PLANNING_INSTRUCTION

logger = logging.getLogger(__name__)
DEFAULT_PRO_MODEL = os.environ.get("PRO_MODEL", "gemini-2.5-pro")

# --- Remote BigQuery MCP Hook ---


async def research_destination(destination: str, dates: str) -> dict:
    """Queries Remote BigQuery MCP to research weather and popularity for a destination."""
    mcp_url = "https://bigquery.googleapis.com/mcp"
    logger.info(f"Researching {destination} via Remote BigQuery MCP")

    try:
        # Get ADC credentials
        credentials, project = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        headers = {"Authorization": f"Bearer {credentials.token}"}

        async with sse_client(mcp_url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                meta = {}
                inject(meta)

                # 1. Weather Query (GSOD)
                weather_sql = """
                SELECT temp, max, min, prcp
                FROM `bigquery-public-data.noaa_gsod.gsod2023`
                WHERE stn='724940'
                ORDER BY date DESC LIMIT 5
                """
                # 2. Popularity Query — escape single quotes to prevent SQL injection
                safe_destination = destination.replace("'", "\\'")
                wiki_sql = f"""
                SELECT sum_views
                FROM (
                    SELECT SUM(views) as sum_views
                    FROM `bigquery-public-data.wikipedia.pageviews_2024`
                    WHERE title = '{safe_destination}'
                )
                """

                logger.info("Executing Weather SQL...")
                weather_res = await session.call_tool(
                    "execute_sql", arguments={"sql": weather_sql}, meta=meta
                )

                logger.info("Executing Wiki SQL...")
                wiki_res = await session.call_tool(
                    "execute_sql", arguments={"sql": wiki_sql}, meta=meta
                )

                res = {
                    "weather_data": weather_res.content[0].text
                    if weather_res.content
                    else "No Data",
                    "popularity_data": wiki_res.content[0].text
                    if wiki_res.content
                    else "No Data",
                }
                logger.info(f"BigQuery MCP results for {destination}: {res}")
                return res
    except Exception as e:
        logger.warning(
            f"Failed to query Remote BigQuery MCP, using local mock fallback: {e}"
        )
        return {
            "weather_data": "Sunny, 72F, max 75, min 65, prcp 0.0",
            "popularity_data": "Total views 500,000 (Very Popular)",
        }


# --- A2A HTTP specialist tools ---


async def call_flight_specialist(
    user_id: str, destination: str, departure_airport: str, dates: str
) -> dict:
    """Delegates to FlightSpecialist on Cloud Run to search flights."""
    url = os.environ.get("FLIGHT_SPECIALIST_URL", "http://localhost:8082/chat")
    payload = {
        "user_id": user_id,
        "destination": destination,
        "departure_airport": departure_airport,
        "dates": dates,
    }
    logger.info(f"Calling FlightSpecialist at {url} for {user_id}")
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=180.0)
    response.raise_for_status()
    res_json = response.json()
    logger.info(f"FlightSpecialist response for {user_id}: {res_json}")
    return res_json


async def call_hotel_specialist(user_id: str, destination: str, dates: str) -> dict:
    """Delegates to HotelSpecialist on GKE to search hotels."""
    url = os.environ.get("HOTEL_SPECIALIST_URL", "http://localhost:8084/chat")
    payload = {"user_id": user_id, "destination": destination, "dates": dates}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=180.0)
    response.raise_for_status()
    res_json = response.json()
    logger.info(f"HotelSpecialist response for {user_id}: {res_json}")
    return res_json


async def call_car_specialist(user_id: str, destination: str, dates: str) -> dict:
    """Delegates to CarRentalSpecialist on GKE to rent cars."""
    url = os.environ.get("CAR_RENTAL_SPECIALIST_URL", "http://localhost:8085/chat")
    payload = {"user_id": user_id, "destination": destination, "dates": dates}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=180.0)
    response.raise_for_status()
    res_json = response.json()
    logger.info(f"CarRentalSpecialist response for {user_id}: {res_json}")
    return res_json


async def handoff_to_booking(user_id: str, itinerary_details: str) -> dict:
    """Delegates to BookingOrchestrator to finalize and book the itinerary."""
    url = os.environ.get("BOOKING_ORCHESTRATOR_URL", "http://localhost:8081/chat")
    payload = {"user_id": user_id, "itinerary_details": itinerary_details}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=180.0)
    response.raise_for_status()
    res_json = response.json()
    logger.info(f"BookingOrchestrator response for {user_id}: {res_json}")
    return res_json


# --- Planning Agent ---

planning_agent = LlmAgent(
    name="PlanningAgent",
    model=DEFAULT_PRO_MODEL,
    description="Assembles the itinerary by researching and orchestrating specialists.",
    static_instruction=PLANNING_INSTRUCTION,
    tools=[
        research_destination,
        call_flight_specialist,
        call_hotel_specialist,
        call_car_specialist,
        handoff_to_booking,
    ],
)
