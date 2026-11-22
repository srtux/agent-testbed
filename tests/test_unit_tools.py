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
        llm_spec = spec["metric"]["llmBasedMetricSpec"]
        template = llm_spec["metricPromptTemplate"]
        assert "{% if agent_data %}" in template
        assert "{% if events %}" in template
        assert "{% if prompt %}" in template
        assert "{% if response %}" in template
        assert "{% if input_text %}" in template
        assert "{% if output_text %}" in template
        assert "{% raw %}" in template and "{% endraw %}" in template
        parser_cfg = (
            llm_spec
            .get("resultParserConfig", {})
            .get("customCodeParserConfig")
        )
        if parser_cfg:
            ns = {}
            exec(parser_cfg["parsingFunction"], ns)
            parsed = ns["parse_llm_response"]('```json\n{"score": 0.75, "explanation": "3 of 4 rubrics met"}\n```')
            assert parsed == {"score": 0.75, "explanation": "3 of 4 rubrics met"}
            parsed_results = ns["parse_results"](['```json\n{"score": 0.75, "explanation": "3 of 4 rubrics met"}\n```'])
            assert parsed_results == {"score": 0.75, "explanation": "3 of 4 rubrics met"}


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


def test_specialist_timeout_hierarchy_and_http_resilience():
    """Verifies downstream timeout budgets prevent timeout inversion and HTTP failures degrade gracefully."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    import httpx

    from agents.FlightSpecialist.flight_specialist import agent as flight_mod
    from agents.RootRouter.root_router.sub_agents import planning as planning_mod
    from agents.WeatherSpecialist.weather_specialist import agent as weather_mod

    # Upstream timeouts must strictly exceed downstream delegation budgets:
    # RootRouter (240s) > FlightSpecialist->WeatherSpecialist (180s) > WeatherSpecialist->BookingOrchestrator (120s)
    assert planning_mod.SPECIALIST_TIMEOUT_SECONDS >= 240.0
    assert flight_mod.WEATHER_SPECIALIST_TIMEOUT_SECONDS >= 180.0
    assert flight_mod.HOTEL_SPECIALIST_TIMEOUT_SECONDS >= 120.0

    async def _exercise_fallbacks():
        req = httpx.Request("POST", "http://10.128.0.53/chat")
        read_timeout = httpx.ReadTimeout("timed out after 60s", request=req)
        resp_500 = httpx.Response(500, request=httpx.Request("POST", "http://10.128.0.103/chat"))

        with patch.object(httpx.AsyncClient, "post", new=AsyncMock(side_effect=read_timeout)):
            weather_fallback = await flight_mod.delegate_to_weather_specialist(
                user_id="user_1438",
                destination="Patagonia",
                itinerary_so_far="Flight CloudAir + Patagonia Cloud Suites",
            )
            assert weather_fallback["status"] == "mock_success"
            assert "ReadTimeout" in weather_fallback["degraded_reason"]

            hotel_fallback = await flight_mod.delegate_to_hotel_specialist(
                user_id="user_1438",
                destination="Patagonia",
                dates="2026-06-28 to 2026-07-03",
            )
            assert hotel_fallback["status"] == "mock_success"
            assert hotel_fallback["hotel"] == "Fallback Inn"

        with patch.object(httpx.AsyncClient, "post", new=AsyncMock(return_value=resp_500)):
            flight_res = await planning_mod.call_flight_specialist(
                user_id="user_1438",
                destination="Patagonia",
                departure_airport="SFO",
                dates="2026-06-28 to 2026-07-03",
            )
            assert flight_res["status"] == "degraded"
            assert "Patagonia" in flight_res["agent_response"]

            hotel_res = await planning_mod.call_hotel_specialist(
                user_id="user_1438",
                destination="Patagonia",
                dates="2026-06-28 to 2026-07-03",
            )
            assert hotel_res["status"] == "degraded"

            car_res = await planning_mod.call_car_specialist(
                user_id="user_1438",
                destination="Patagonia",
                dates="2026-06-28 to 2026-07-03",
            )
            assert car_res["status"] == "degraded"

        with patch(
            "testbed_utils.telemetry.invoke_booking_orchestrator",
            new=AsyncMock(side_effect=read_timeout),
        ):
            booking_res = await weather_mod.delegate_to_booking_orchestrator(
                user_id="user_1438",
                itinerary_details="Patagonia itinerary",
            )
            assert booking_res["status"] == "pending_confirmation"

    asyncio.run(_exercise_fallbacks())


def test_resilient_gemini_cross_pool_429_failover_and_tool_sanitizer():
    """Verifies ResilientGemini fails over across Gemini 4 pools on 429 and strips hallucinated tools."""
    import asyncio
    from unittest.mock import patch

    from google.adk.models.google_llm import Gemini
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    from google.genai.errors import ClientError

    from testbed_utils.llm import (
        DEFAULT_FLASH_MODEL_NAME,
        DEFAULT_PRO_MODEL_NAME,
        ResilientGemini,
        build_flash_model,
        build_pro_model,
        sanitize_unregistered_tool_calls,
    )

    assert DEFAULT_PRO_MODEL_NAME == "gemini-4-neon"
    assert DEFAULT_FLASH_MODEL_NAME == "gemini-4-hydrogen"
    assert build_pro_model().vertex_location == "global"
    assert build_flash_model().retry_options.attempts >= 4

    attempted_models: list[str] = []

    async def _fake_super_generate(self, llm_request: LlmRequest, stream: bool = False):
        attempted_models.append(llm_request.model)
        if llm_request.model == "gemini-4-neon":
            raise ClientError(
                429,
                {
                    "error": {
                        "code": 429,
                        "message": "TPM quota exhausted.",
                        "status": "RESOURCE_EXHAUSTED",
                    }
                },
                None,
            )
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            name="run_code", args={"code": "print(1)"}
                        )
                    ),
                    types.Part.from_text(text="Recovered on fallback pool."),
                ],
            )
        )

    async def _run_failover():
        model = ResilientGemini(
            model="gemini-4-neon",
            fallback_models=("gemini-4-neon", "gemini-4-hydrogen", "gemini-4-argon"),
        )
        req = LlmRequest(
            model="gemini-4-neon",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="Book trip")])],
        )
        with patch.object(Gemini, "generate_content_async", _fake_super_generate):
            outputs = [r async for r in model.generate_content_async(req)]
        assert attempted_models == ["gemini-4-neon", "gemini-4-hydrogen"]
        assert len(outputs) == 1
        parts = outputs[0].content.parts
        assert all(getattr(p, "function_call", None) is None for p in parts)
        assert parts[0].text == "Recovered on fallback pool."

        # Also verify graceful LlmResponse when all pools fail with 429
        async def _always_429(self, llm_request: LlmRequest, stream: bool = False):
            raise ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, None)
            yield  # pragma: no cover

        req_exhausted = LlmRequest(
            model="gemini-4-neon",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text="Hi")])],
        )
        with patch.object(Gemini, "generate_content_async", _always_429):
            degraded = [r async for r in model.generate_content_async(req_exhausted)]
        assert len(degraded) == 1
        assert "momentarily busy" in degraded[0].content.parts[0].text

    asyncio.run(_run_failover())

    # Verify sole unregistered tool call gets replaced with safe text
    only_bad_tool = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="google:python_interpreter", args={}
                    )
                )
            ],
        )
    )
    cleaned = sanitize_unregistered_tool_calls(only_bad_tool, {"fetch_profile"})
    assert len(cleaned.content.parts) == 1
    assert cleaned.content.parts[0].function_call is None
    assert "member ID" in cleaned.content.parts[0].text

    # Verify api_client isolates google.genai.Client instances across separate asyncio.run() threads
    import threading

    shared_model = build_pro_model()
    seen_clients: list[int] = []

    def _thread_worker():
        async def _grab_clients():
            c1 = shared_model.api_client
            c2 = shared_model.api_client
            assert c1 is c2
            seen_clients.append(id(c1))

        asyncio.run(_grab_clients())

    t1 = threading.Thread(target=_thread_worker)
    t2 = threading.Thread(target=_thread_worker)
    t1.start()
    t1.join()
    t2.start()
    t2.join()
    assert len(seen_clients) == 2
    assert seen_clients[0] != seen_clients[1]


def test_otel_cross_context_detach_suppresses_asyncgen_stderr_error(caplog):
    """Verifies cross-Task async generator teardown does not log ERROR 'Failed to detach context'."""
    import asyncio
    import logging

    import opentelemetry.context as otel_context
    from opentelemetry import trace

    from testbed_utils.telemetry import setup_authenticated_transport

    setup_authenticated_transport()
    tracer = trace.get_tracer("test_cross_context_detach")

    async def _span_yielding_agen():
        tok = otel_context.attach(otel_context.set_value("test.extra.key", "v1"))
        try:
            with tracer.start_as_current_span("child_task_span"):
                yield "first_chunk"
                yield "second_chunk"
        finally:
            otel_context.detach(tok)

    async def _drive_across_tasks():
        holder = {}

        async def _producer_in_child_task():
            agen = _span_yielding_agen()
            first = await agen.__anext__()
            assert first == "first_chunk"
            holder["agen"] = agen

        child_task = asyncio.create_task(_producer_in_child_task())
        await child_task
        # Closing the suspended async generator from the parent Task executes
        # `finally: otel_context.detach(...)` in a different contextvars.Context.
        await holder["agen"].aclose()

    with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
        asyncio.run(_drive_across_tasks())

    error_messages = [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert not any("Failed to detach context" in m for m in error_messages)


def test_resilient_adk_session_retries_org_policy_and_falls_back_in_memory():
    """Verifies UNVERIFIED_ORG_POLICY retries, in-memory fallback, and stateless stream_query routing."""
    from types import SimpleNamespace

    from google.adk.events import Event
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types
    from google.genai.errors import ClientError

    from testbed_utils.telemetry import (
        is_transient_session_error,
        resilient_adk_create_session,
        resilient_adk_stream_query,
    )

    org_policy_err = ClientError(
        400,
        {
            "error": {
                "code": 400,
                "message": "Failed to check org policy for project 123456789012.",
                "status": "FAILED_PRECONDITION",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "UNVERIFIED_ORG_POLICY",
                    }
                ],
            }
        },
        None,
    )
    assert is_transient_session_error(org_policy_err) is True

    # 1. Transient failure on attempt 1 recovers on attempt 2 via primary service
    call_count = {"n": 0}

    class _FlakyPrimarySessionService:
        async def create_session(self, *, app_name, user_id, session_id=None, state=None, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise org_policy_err
            return SimpleNamespace(id="primary-sess-42", user_id=user_id, app_name=app_name)

    in_mem_service = InMemorySessionService()
    fake_app = SimpleNamespace(
        _tmpl_attrs={
            "app_name": "RootRouter",
            "session_service": _FlakyPrimarySessionService(),
            "in_memory_session_service": in_mem_service,
        },
        set_up=lambda: None,
    )
    recovered = resilient_adk_create_session(fake_app, user_id="user_101", base_delay=0.01)
    assert recovered.id == "primary-sess-42"
    assert call_count["n"] == 2

    # 2. Persistent failure falls back cleanly to InMemorySessionService without raising or stderr crash
    class _BrokenPrimarySessionService:
        async def create_session(self, **kwargs):
            raise org_policy_err

    primary_runs: list[str] = []
    in_memory_runs: list[str] = []

    class _RecordingRunner:
        def __init__(self, bucket: list[str], label: str):
            self._bucket = bucket
            self._label = label

        def run(self, *, user_id, session_id, new_message, **kwargs):
            self._bucket.append(session_id)
            yield Event(
                author="BookingOrchestrator",
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=f"handled-by-{self._label}")],
                ),
            )

    fake_app_fallback = SimpleNamespace(
        _tmpl_attrs={
            "app_name": "BookingOrchestrator",
            "session_service": _BrokenPrimarySessionService(),
            "in_memory_session_service": InMemorySessionService(),
            "runner": _RecordingRunner(primary_runs, "primary"),
            "in_memory_runner": _RecordingRunner(in_memory_runs, "in_memory"),
        },
        set_up=lambda: None,
    )
    fallback_sess = resilient_adk_create_session(
        fake_app_fallback, user_id="user_202", max_attempts=2, base_delay=0.01
    )
    assert fallback_sess.id in fake_app_fallback._tmpl_attrs["fallback_in_memory_sessions"]

    # Subsequent stream_query with that fallback session_id routes to in_memory_runner
    events_fb = list(
        resilient_adk_stream_query(
            fake_app_fallback,
            message="Finalize booking",
            user_id="user_202",
            session_id=fallback_sess.id,
        )
    )
    assert len(events_fb) == 1
    assert "handled-by-in_memory" in str(events_fb[0])
    assert in_memory_runs == [fallback_sess.id]
    assert primary_runs == []

    # 3. Stateless stream_query (session_id=None) uses in_memory_runner directly without hitting broken primary
    events_stateless = list(
        resilient_adk_stream_query(
            fake_app_fallback,
            message="Stateless booking handoff",
            user_id="user_303",
            session_id=None,
        )
    )
    assert len(events_stateless) == 1
    assert len(in_memory_runs) == 2
    assert primary_runs == []






