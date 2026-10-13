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


def test_extract_agent_reply_sse_and_json():
    """Verifies SSE and JSON assistant text extraction in traffic_generator."""
    from traffic_generator.main import _extract_agent_reply

    sse_payload = (
        'data: {"content": {"parts": [{"text": "Please provide your member ID."}]}}\n'
        'data: {"content": {"parts": [{"text": "Once authenticated, I can recommend destinations."}]}}\n'
    )
    extracted = _extract_agent_reply(sse_payload)
    assert "Please provide your member ID." in extracted
    assert "Once authenticated, I can recommend destinations." in extracted

    json_payload = '{"response": "Your booking is confirmed with a 15% loyalty discount!"}'
    assert (
        _extract_agent_reply(json_payload)
        == "Your booking is confirmed with a 15% loyalty discount!"
    )


def test_dynamic_user_prompt_llm_and_fallback():
    """Verifies LLM-driven dynamic user prompt generation and context-aware fallback."""
    from unittest.mock import MagicMock, patch
    from traffic_generator.main import (
        _build_persona,
        _fallback_next_user_prompt,
        _generate_next_user_prompt,
        _is_booking_complete,
    )

    persona = _build_persona("explorer", "user_1234")
    persona["member_id"] = "M-12345"
    persona["fallback_destination"] = "Bali"

    # Turn 1 (empty history)
    turn1 = _generate_next_user_prompt(
        persona=persona,
        history=[],
        turn_idx=1,
        max_turns=5,
        project="test-proj",
        location="us-central1",
        auth_headers={"Authorization": "Bearer tok"},
    )
    assert persona["category"] in turn1

    # Turn 2: Agent asks for member ID -> LLM simulator dynamically responds
    history = [
        {
            "user": turn1,
            "agent": "Welcome! Please provide your member ID so I can pull up your profile.",
        }
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "My member ID is M-12345. Can you recommend some great beach destinations?"
                        }
                    ]
                }
            }
        ]
    }
    with patch("traffic_generator.main.requests.post", return_value=mock_resp) as mock_post:
        turn2 = _generate_next_user_prompt(
            persona=persona,
            history=history,
            turn_idx=2,
            max_turns=5,
            project="test-proj",
            location="us-central1",
            auth_headers={"Authorization": "Bearer tok"},
        )
        assert "M-12345" in turn2
        assert mock_post.called

    # Turn 3 fallback: Agent recommends Kyoto and Athens -> fallback picks a recommended city
    history.append(
        {
            "user": turn2,
            "agent": "Thanks! Based on your Gold profile, I recommend Kyoto or Athens for historical sightseeing.",
        }
    )
    turn3_fallback = _fallback_next_user_prompt(persona, history, turn_idx=3)
    assert ("Athens" in turn3_fallback or "Kyoto" in turn3_fallback)
    assert persona["dates"] in turn3_fallback

    # Completion detection
    assert _is_booking_complete("Your booking is confirmed! Confirmation number #9912.", 4) is True
    assert _is_booking_complete("Which hotel would you prefer?", 4) is False

