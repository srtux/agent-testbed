import os
import logging
import json
import httpx
from datetime import datetime, date
from google.adk.agents import LlmAgent

# Relative imports from current package
from .prompt import FLIGHT_SPECIALIST_INSTRUCTION
from .sub_agents.seat_selector import seat_selector

logger = logging.getLogger(__name__)
DEFAULT_FLASH_MODEL = os.environ.get("FLASH_MODEL", "gemini-2.5-flash")

# --- Local Tools ---

async def validate_dates(dates: str) -> dict:
    """Parse and validate a travel date range string. Returns structured date info or error."""
    try:
        parts = [d.strip() for d in dates.replace(" to ", "-").replace("/", "-").split("-")]
        if len(parts) >= 6:
            start = date(int(parts[0]), int(parts[1]), int(parts[2]))
            end = date(int(parts[3]), int(parts[4]), int(parts[5]))
        elif len(parts) == 2:
            start = datetime.strptime(parts[0].strip(), "%Y-%m-%d").date()
            end = datetime.strptime(parts[1].strip(), "%Y-%m-%d").date()
        else:
            return {"valid": True, "days": 5, "note": "Could not parse dates precisely, assuming 5 days"}
        days = (end - start).days
        if days <= 0:
            return {"valid": False, "error": "End date must be after start date"}
        if days > 30:
            return {"valid": False, "error": "Trip duration exceeds 30-day maximum"}
        return {"valid": True, "days": days, "start": str(start), "end": str(end)}
    except Exception:
        return {"valid": True, "days": 5, "note": "Could not parse dates precisely, assuming 5 days"}


async def check_flight_availability(user_id: str, destination: str, dates: str) -> dict:
    """Check flight availability with fare calculation based on route and duration."""
    from testbed_utils.config import FARE_TABLE
    logger.info(f"Checking flights for {destination} on {dates} (User: {user_id})")
    base_fare = FARE_TABLE.get(destination.upper()[:3], 400)
    # Parse duration for surcharge
    days = 5
    try:
        parts = [d.strip() for d in dates.replace(" to ", "-").replace("/", "-").split("-")]
        if len(parts) >= 6:
            start = date(int(parts[0]), int(parts[1]), int(parts[2]))
            end = date(int(parts[3]), int(parts[4]), int(parts[5]))
            days = max(1, (end - start).days)
    except Exception:
        pass
    total = base_fare + (days * 15)
    return {"status": "available", "cost": total, "airline": "CloudAir", "days": days, "base_fare": base_fare}


# --- A2A HTTP Delegation Tools ---

async def delegate_to_hotel_specialist(user_id: str, destination: str, dates: str) -> dict:
    """Delegates to the Hotel Specialist on GKE."""
    logger.info(f"Delegating to HotelSpecialist for {user_id}")
    hotel_url = os.environ.get("HOTEL_SPECIALIST_URL", "http://localhost:8084/chat")

    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "destination": destination, "dates": dates}
        res = await client.post(hotel_url, json=payload, timeout=60.0)
        if res.status_code >= 400:
            return {"status": "mock_success", "hotel": "Fallback Inn"}
        return res.json()

async def delegate_to_weather_specialist(user_id: str, destination: str, itinerary_so_far: str) -> dict:
    """Delegates to the Weather Specialist to check conditions and pass on the itinerary."""
    logger.info(f"Delegating to WeatherSpecialist for {user_id}")
    weather_url = os.environ.get("WEATHER_SPECIALIST_URL", "http://localhost:8083/chat")

    async with httpx.AsyncClient() as client:
        payload = {"user_id": user_id, "destination": destination, "itinerary_so_far": itinerary_so_far}
        res = await client.post(weather_url, json=payload, timeout=60.0)
        if res.status_code >= 400:
            return {"status": "mock_success"}
        return res.json()


# --- Agent ---

agent = LlmAgent(
    name="FlightSpecialist",
    model=DEFAULT_FLASH_MODEL,
    static_instruction=FLIGHT_SPECIALIST_INSTRUCTION,
    tools=[validate_dates, check_flight_availability, delegate_to_hotel_specialist, delegate_to_weather_specialist],
    sub_agents=[seat_selector],
)
