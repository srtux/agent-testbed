"""Pure local tools for BookingOrchestrator."""


async def calculate_trip_cost(
    flight_cost: float, hotel_cost: float, car_cost: float, days: int, loyalty_tier: str
) -> dict:
    """Aggregate costs from flight, hotel, and car rental. Apply loyalty discounts."""
    loyalty_discounts = {
        "Gold": 0.15,
        "Silver": 0.10,
        "Bronze": 0.05,
    }
    subtotal = flight_cost + (hotel_cost * days) + (car_cost * days)
    discount_pct = loyalty_discounts.get(loyalty_tier, 0)
    discount = subtotal * discount_pct
    total = subtotal - discount
    return {
        "subtotal": round(subtotal, 2),
        "loyalty_discount_pct": discount_pct * 100,
        "discount_amount": round(discount, 2),
        "total": round(total, 2),
        "currency": "USD",
    }


async def format_itinerary(
    user_id: str,
    destination: str,
    flight_details: str,
    hotel_details: str,
    car_details: str,
    weather: str,
    total_cost: float,
) -> dict:
    """Build a structured itinerary summary document from all booking components."""
    itinerary = {
        "itinerary_id": f"ITIN-{hash(user_id + destination) % 100000:05d}",
        "traveler": user_id,
        "destination": destination,
        "sections": {
            "flight": flight_details,
            "accommodation": hotel_details,
            "ground_transport": car_details,
            "weather_advisory": weather,
        },
        "total_cost_usd": total_cost,
        "status": "pending_confirmation",
    }
    return itinerary
