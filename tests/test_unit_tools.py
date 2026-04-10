import os
import sys

import pytest

# Add project root to path to ensure imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.BookingOrchestrator.booking_orchestrator.tools import calculate_trip_cost
from agents.RootRouter.root_router.tools import extract_travel_intent


@pytest.mark.parametrize(
    "loyalty_tier, discount_pct",
    [
        ("Gold", 0.15),
        ("Silver", 0.10),
        ("Bronze", 0.05),
        ("None", 0.0),
        ("Platinum", 0.0),  # Unknown tier should get 0 discount
    ],
)
def test_calculate_trip_cost_loyalty(loyalty_tier, discount_pct):
    """Award-winning test for loyalty tier calculations."""
    flight = 100.0
    hotel = 50.0
    car = 30.0
    days = 2

    # Subtotal = 100 + (50*2) + (30*2) = 100 + 100 + 60 = 260
    subtotal = 260.0
    expected_discount = subtotal * discount_pct
    expected_total = subtotal - expected_discount

    import asyncio
    result = asyncio.run(calculate_trip_cost(flight, hotel, car, days, loyalty_tier))

    assert result["subtotal"] == subtotal
    assert result["loyalty_discount_pct"] == discount_pct * 100
    assert result["discount_amount"] == round(expected_discount, 2)
    assert result["total"] == round(expected_total, 2)


def test_calculate_trip_cost_zero_days():
    """Verifies behavior when days is zero (e.g., day trip with no hotel/car)."""
    import asyncio
    result = asyncio.run(calculate_trip_cost(100.0, 50.0, 30.0, 0, "Gold"))
    assert result["subtotal"] == 100.0  # Only flight cost
    assert result["discount_amount"] == 15.0  # 15% of 100
    assert result["total"] == 85.0


@pytest.mark.parametrize(
    "user_input, expected_dates",
    [
        ("I want to travel on 2026-05-12", "2026-05-12"),
        ("Leaving May 12 and returning May 15", "May 12, May 15"),
        ("No dates here", None),
        ("Mixed formats 2026-05-12 and June 1", "2026-05-12, June 1"),
    ],
)
def test_extract_travel_intent_dates(user_input, expected_dates):
    """Tests date extraction heuristics in extract_travel_intent."""
    import asyncio
    result = asyncio.run(extract_travel_intent(user_input))
    assert result["dates"] == expected_dates
    assert result["raw_input"] == user_input
    assert result["destination"] is None  # Currently hardcoded to None in the tool
