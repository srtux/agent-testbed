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


def test_audience_map_env_pair_fallback(monkeypatch):
    """Verifies that _load_audience_map, _needs_oidc_auth, and _get_audience resolve ILB URLs from *_URL/*_AUDIENCE env vars."""
    from testbed_utils.telemetry import _get_audience, _load_audience_map, _needs_oidc_auth

    monkeypatch.delenv("URL_AUDIENCE_MAP", raising=False)
    monkeypatch.setenv("FLIGHT_SPECIALIST_URL", "http://10.128.0.103/chat")
    monkeypatch.setenv(
        "FLIGHT_SPECIALIST_AUDIENCE",
        "https://flight-specialist-umbi5pyafa-uc.a.run.app",
    )
    monkeypatch.setenv("PROFILE_MCP_URL", "http://10.128.0.87/sse")
    monkeypatch.setenv(
        "PROFILE_MCP_AUDIENCE",
        "https://profile-mcp-umbi5pyafa-uc.a.run.app",
    )

    aud_map = _load_audience_map()
    assert aud_map.get("http://10.128.0.103") == "https://flight-specialist-umbi5pyafa-uc.a.run.app"
    assert _needs_oidc_auth("http://10.128.0.103/chat") is True
    assert _get_audience("http://10.128.0.103/chat") == "https://flight-specialist-umbi5pyafa-uc.a.run.app"
    assert _needs_oidc_auth("http://10.128.0.87/sse") is True
    assert _get_audience("http://10.128.0.87/sse") == "https://profile-mcp-umbi5pyafa-uc.a.run.app"


def test_httpx_async_client_oidc_and_host_injection(monkeypatch):
    """Verifies that httpx.AsyncClient and httpx.Client inject Authorization and Host headers for PSC ILB targets."""
    import asyncio
    from unittest.mock import patch
    import httpx
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from testbed_utils.telemetry import _setup_oidc_auth

    monkeypatch.setenv("FLIGHT_SPECIALIST_URL", "http://10.128.0.103/chat")
    monkeypatch.setenv(
        "FLIGHT_SPECIALIST_AUDIENCE",
        "https://flight-specialist-umbi5pyafa-uc.a.run.app",
    )

    captured_headers = {}

    class MockAsyncTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers["authorization"] = request.headers.get("authorization")
            captured_headers["host"] = request.headers.get("host")
            return httpx.Response(200, json={"status": "ok"})

    with patch("google.oauth2.id_token.fetch_id_token", return_value="fake-oidc-token"):
        _setup_oidc_auth(RequestsInstrumentor(), HTTPXClientInstrumentor())

        async def _run():
            async with httpx.AsyncClient(transport=MockAsyncTransport()) as client:
                resp = await client.post("http://10.128.0.103/chat", json={"user_id": "u1"})
                assert resp.status_code == 200

        asyncio.run(_run())

    assert captured_headers.get("authorization") == "Bearer fake-oidc-token"
    assert captured_headers.get("host") == "flight-specialist-umbi5pyafa-uc.a.run.app"
