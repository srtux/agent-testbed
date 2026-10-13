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


def test_agent_evals_custom_code_metric_compliance():
    """Verifies evaluate_trajectory_policy_compliance on passing and violating multi-turn trajectories."""
    import json

    from scripts.run_agent_evals import (
        DEFAULT_DATASET_PATH,
        evaluate_trajectory_policy_compliance,
    )

    with open(DEFAULT_DATASET_PATH, encoding="utf-8") as f:
        cases = json.load(f)

    assert len(cases) >= 3
    for case in cases:
        res = evaluate_trajectory_policy_compliance(case)
        assert res["score"] == 1.0, f"Expected 1.0 for {case['eval_case_id']}, got {res}"

    # Construct a violating trajectory (calls search_flights before verify_user_session and omits transaction ID)
    violating_case = {
        "response": "Your flight is booked! Reservation ID: RES-100.",
        "agent_data": {
            "turns": [
                {
                    "turnIndex": 0,
                    "events": [
                        {
                            "author": "RootRouter",
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "search_flights",
                                            "args": {"origin": "SFO", "destination": "JFK"},
                                        }
                                    }
                                ],
                            },
                        },
                        {
                            "author": "RootRouter",
                            "content": {
                                "role": "user",
                                "parts": [
                                    {
                                        "functionResponse": {
                                            "name": "transfer_to_booking_orchestrator",
                                            "response": {
                                                "status": "CONFIRMED",
                                                "reservation_id": "RES-100",
                                                "transaction_id": "TXN-MISSING",
                                            },
                                        }
                                    }
                                ],
                            },
                        },
                    ],
                }
            ]
        },
    }
    bad_res = evaluate_trajectory_policy_compliance(violating_case)
    assert bad_res["score"] < 1.0
    assert "FAIL: Protected tool called before verify_user_session." in bad_res["explanation"]
    assert "TXN-MISSING" in bad_res["explanation"]


def test_agent_evals_instance_builder_and_custom_rubric_specs():
    """Verifies _build_evaluation_instance and CUSTOM_RUBRIC_METRIC_SPECS definitions."""
    import json

    from scripts.run_agent_evals import (
        CUSTOM_RUBRIC_METRIC_SPECS,
        DEFAULT_DATASET_PATH,
        _build_evaluation_instance,
    )

    with open(DEFAULT_DATASET_PATH, encoding="utf-8") as f:
        cases = json.load(f)

    instance = _build_evaluation_instance(cases[0])
    assert instance.agent_data is not None
    assert "RootRouter" in instance.agent_data.agents
    assert len(instance.agent_data.turns) == 2
    assert instance.rubric_groups is not None
    assert "travel_concierge_rubrics" in instance.rubric_groups
    assert len(instance.rubric_groups["travel_concierge_rubrics"].rubrics) == 3

    for spec in CUSTOM_RUBRIC_METRIC_SPECS:
        meta = spec["metric"]["metadata"]
        assert meta["scoreRange"] == {"min": 0, "max": 1, "step": 0.25}
        parser_cfg = (
            spec["metric"]["llmBasedMetricSpec"]
            .get("resultParserConfig", {})
            .get("customCodeParserConfig")
        )
        if parser_cfg:
            ns = {}
            exec(parser_cfg["parsingFunction"], ns)
            parsed = ns["parse_llm_response"]('```json\n{"score": 0.75, "explanation": "3 of 4 rubrics met"}\n```')
            assert parsed == {"score": 0.75, "explanation": "3 of 4 rubrics met"}


def test_quality_flywheel_baseline_vs_optimized_and_loss_clusters():
    """Verifies Quality Flywheel baseline v0 policy failures, loss cluster extraction, and metric lift table."""
    import json

    from scripts.run_agent_evals import (
        DEFAULT_DATASET_PATH,
        evaluate_trajectory_policy_compliance,
    )
    from scripts.run_quality_flywheel_demo import (
        BASELINE_V0_DATASET_PATH,
        build_root_router_agent_configs,
        compute_flywheel_comparison_table,
        extract_loss_clusters_from_run,
    )

    agent_configs = build_root_router_agent_configs()
    assert "RootRouter" in agent_configs
    assert "BookingOrchestrator" in agent_configs

    with open(BASELINE_V0_DATASET_PATH, encoding="utf-8") as f:
        baseline_cases = json.load(f)
    with open(DEFAULT_DATASET_PATH, encoding="utf-8") as f:
        optimized_cases = json.load(f)

    assert len(baseline_cases) == 3
    baseline_scores = [evaluate_trajectory_policy_compliance(c)["score"] for c in baseline_cases]
    optimized_scores = [evaluate_trajectory_policy_compliance(c)["score"] for c in optimized_cases]

    assert all(s < 1.0 for s in baseline_scores)
    assert all(s == 1.0 for s in optimized_scores)

    mock_baseline_run = {
        "evaluationResults": {
            "summaryMetrics": {
                "metrics": {
                    "multi_turn_task_success_v1/AVERAGE": 0.3333,
                    "multi_turn_tool_use_quality_v1/AVERAGE": 0.0,
                    "multi_turn_trajectory_quality_v1/AVERAGE": 0.2222,
                    "travel_concierge_rubric_quality_v1/AVERAGE": 0.25,
                }
            },
            "lossAnalysisResults": [
                {
                    "config": {"metric": "multi_turn_tool_use_quality_v1", "candidate": "RootRouter"},
                    "clusters": [
                        {
                            "clusterId": "c1",
                            "taxonomyEntry": {
                                "l1Category": "Hallucination",
                                "l2Category": "Hallucination of Action",
                                "description": "Verbal confirmation without booking tool execution.",
                            },
                            "itemCount": 1,
                            "examples": [
                                {
                                    "failedRubrics": [
                                        {"classificationRationale": "Fabricated confirmation ID."}
                                    ]
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }
    mock_optimized_run = {
        "evaluationResults": {
            "summaryMetrics": {
                "metrics": {
                    "multi_turn_task_success_v1/AVERAGE": 1.0,
                    "multi_turn_tool_use_quality_v1/AVERAGE": 1.0,
                    "multi_turn_trajectory_quality_v1/AVERAGE": 0.9778,
                    "travel_concierge_rubric_quality_v1/AVERAGE": 0.9167,
                }
            }
        }
    }

    clusters = extract_loss_clusters_from_run(mock_baseline_run)
    assert len(clusters) == 1
    assert clusters[0]["l2_category"] == "Hallucination of Action"

    comparison = compute_flywheel_comparison_table(
        baseline_run=mock_baseline_run,
        optimized_run=mock_optimized_run,
        baseline_code_scores=baseline_scores,
        optimized_code_scores=optimized_scores,
    )
    by_metric = {r["metric"]: r for r in comparison}
    assert by_metric["multi_turn_task_success_v1"]["delta"] > 0.6
    assert by_metric["custom_code_trajectory_policy_compliance"]["optimized_v1_score"] == 1.0
    assert by_metric["custom_code_trajectory_policy_compliance"]["delta"] > 0.3



