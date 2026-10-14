"""Sets up and executes Online and Offline Agent Evaluations with Custom Rubrics.

Supports:
1. Vertex AI Metric Registry (`evaluationMetrics`):
   - Registers custom LLM-as-a-Judge rubric metrics (with `scoreRange` metadata
     and custom Python `parsingFunction` configs) for `RootRouter` and
     `BookingOrchestrator`.
2. Vertex AI Online Evaluators (`onlineEvaluators`):
   - Attaches active online evaluators to deployed Reasoning Engines so live
     background traffic traces are continuously scored against predefined and
     custom rubric metrics.
3. Vertex AI Offline Multi-Turn Evaluations (`:evaluateInstances` & `evaluationRuns`):
   - Evaluates multi-turn `AgentData` trajectories (`agents` + `turns` + `events`)
     with predefined multi-turn metrics (`multi_turn_task_success_v1`,
     `multi_turn_tool_use_quality_v1`, `multi_turn_trajectory_quality_v1`),
     per-case custom `rubric_groups` (`RubricVerdict`s), deterministic custom
     Python code metrics, and managed `evaluationRuns` backed by `evaluationSets`.
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import google.auth
import google.auth.transport.requests
import vertexai
from google.genai import types as genai_types
from google.oauth2 import credentials as oauth2_credentials
from vertexai._genai import types as eval_types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATASET_PATH = os.path.join(REPO_ROOT, "evals", "multi_turn_travel_dataset.json")
AGENT_OUTPUTS_PATH = os.path.join(REPO_ROOT, "agent_engine_outputs.json")

PREDEFINED_MULTI_TURN_METRICS = (
    "multi_turn_task_success_v1",
    "multi_turn_tool_use_quality_v1",
    "multi_turn_trajectory_quality_v1",
)

CONTEXT_TEMPLATE_BLOCK = (
    "{% if agent_data %}Multi-Turn Agent Session Trajectory:\n{agent_data}\n\n{% endif %}"
    "{% if events %}Session Events & Tool Invocations:\n{events}\n\n{% endif %}"
    "{% if prompt %}User Prompt:\n{prompt}\n\n{% endif %}"
    "{% if response %}Agent Response:\n{response}\n\n{% endif %}"
    "{% if input_text %}User Input:\n{input_text}\n\n{% endif %}"
    "{% if output_text %}Agent Output:\n{output_text}\n\n{% endif %}"
    "{% if intermediate_steps %}Tool Invocations:\n{intermediate_steps}\n\n{% endif %}"
    "{% if tool_declarations %}Available Tool Declarations:\n{tool_declarations}\n\n{% endif %}"
    "{% if developer_instruction %}Developer Instructions:\n{developer_instruction}\n\n{% endif %}"
)

CUSTOM_RUBRIC_METRIC_SPECS: list[dict[str, Any]] = [
    {
        "title": "travel_concierge_rubric_quality_v1",
        "displayName": "Travel Concierge Multi-Turn Rubric Evaluator",
        "description": (
            "Evaluates RootRouter multi-turn travel concierge trajectories against "
            "4 domain rubrics: session authentication gate, multi-turn option "
            "confirmation, tool parameter accuracy, and booking confirmation IDs."
        ),
        "metric": {
            "llmBasedMetricSpec": {
                "metricPromptTemplate": (
                    "You are an expert Travel Concierge Quality Auditor evaluating an AI agent trajectory.\n\n"
                    f"{CONTEXT_TEMPLATE_BLOCK}"
                    "Evaluate the response against the following 4 domain rubric criteria (0.25 points each, total 0.0 to 1.0):\n"
                    "1. Authentication Gate (0.25): The agent verifies or references the user's session/loyalty status before executing or confirming travel searches and bookings.\n"
                    "2. Explicit Confirmation Flow (0.25): The agent clearly communicates options/prices before finalizing bookings or confirms the user's explicit selection.\n"
                    "3. Grounded Itinerary Details (0.25): Flight numbers, hotel names, dates, cities, and prices are specific and internally consistent.\n"
                    "4. Actionable Next Step or Confirmation IDs (0.25): If a booking is completed, reservation/transaction IDs are provided; if in discovery/search, a clear next step is offered.\n\n"
                    '{% raw %}Assign a score from [0.0, 0.25, 0.5, 0.75, 1.0] and explain which criteria passed or failed.\n'
                    'Respond ONLY with valid JSON: {"score": <0.0|0.25|0.5|0.75|1.0>, "explanation": "<concise rubric rationale>"}{% endraw %}'
                )
            },
            "metadata": {
                "title": "travel_concierge_rubric_quality_v1",
                "scoreRange": {"min": 0, "max": 1, "step": 0.25},
            },
        },
    },
    {
        "title": "booking_transaction_rubric_v1",
        "displayName": "Booking Orchestrator Transaction Rubric",
        "description": (
            "Evaluates BookingOrchestrator transactional execution against payment "
            "and reservation integrity rubrics."
        ),
        "metric": {
            "llmBasedMetricSpec": {
                "metricPromptTemplate": (
                    "You are a Transactional Integrity Auditor evaluating a BookingOrchestrator trajectory.\n\n"
                    f"{CONTEXT_TEMPLATE_BLOCK}"
                    "Evaluate the response against these 4 rubric criteria (0.25 points each, total 0.0 to 1.0):\n"
                    "1. Reservation Completeness (0.25): Addresses all requested travel segments (flight, hotel, car).\n"
                    "2. Loyalty & Pricing Clarity (0.25): Accurately reflects pricing or loyalty tier handling.\n"
                    "3. Payment & Transaction Confirmation (0.25): Confirms payment processing status without fabricating unsupported charges.\n"
                    "4. Structured Confirmation Output (0.25): Provides clear confirmation/reservation details for the caller.\n\n"
                    '{% raw %}Assign a score from [0.0, 0.25, 0.5, 0.75, 1.0] and explain your reasoning.\n'
                    'Respond ONLY with valid JSON: {"score": <0.0|0.25|0.5|0.75|1.0>, "explanation": "<concise rubric rationale>"}{% endraw %}'
                )
            },
            "metadata": {
                "title": "booking_transaction_rubric_v1",
                "scoreRange": {"min": 0, "max": 1, "step": 0.25},
            },
        },
    },
    {
        "title": "travel_concierge_parsed_rubric_v1",
        "displayName": "Travel Concierge Custom-Parsed Rubric Metric",
        "description": (
            "Custom LLM rubric metric with a Python parsingFunction that extracts "
            "structured JSON rubric scores and explanations."
        ),
        "metric": {
            "llmBasedMetricSpec": {
                "metricPromptTemplate": (
                    "Evaluate the travel concierge agent trajectory on a 0.0 to 1.0 scale (increments of 0.25) "
                    "for authentication hygiene, tool grounding, and itinerary clarity.\n\n"
                    f"{CONTEXT_TEMPLATE_BLOCK}"
                    '{% raw %}Respond ONLY with valid JSON: {"score": <0.0|0.25|0.5|0.75|1.0>, "explanation": "<concise rubric rationale>"}{% endraw %}'
                ),
                "resultParserConfig": {
                    "customCodeParserConfig": {
                        "parsingFunction": (
                            "import json\n"
                            "import re\n"
                            "def parse_llm_response(llm_response: str) -> dict:\n"
                            "    raw = (llm_response or '').strip()\n"
                            "    cleaned = re.sub(r'^```(?:json)?\\s*|\\s*```$', '', raw, flags=re.DOTALL).strip()\n"
                            "    try:\n"
                            "        data = json.loads(cleaned)\n"
                            "    except Exception:\n"
                            "        match = re.search(r'(\\{.*\\})', cleaned, flags=re.DOTALL)\n"
                            "        data = json.loads(match.group(1)) if match else {'score': 0.0, 'explanation': raw[:300]}\n"
                            "    if isinstance(data, list) and data and isinstance(data[0], dict):\n"
                            "        data = data[0]\n"
                            "    score = max(0.0, min(1.0, float(data.get('score', 0.0))))\n"
                            "    return {'score': score, 'explanation': str(data.get('explanation') or data.get('reasoning') or '')}\n"
                            "\n"
                            "def parse_results(responses: list[str] | str) -> dict:\n"
                            "    first = responses[0] if isinstance(responses, list) and responses else (responses if isinstance(responses, str) else '')\n"
                            "    return parse_llm_response(str(first))\n"
                        )
                    }
                },
            },
            "metadata": {
                "title": "travel_concierge_parsed_rubric_v1",
                "scoreRange": {"min": 0, "max": 1, "step": 0.25},
            },
        },
    },
]


def get_access_token() -> str:
    """Retrieves a Google Cloud access token from ADC or internal SSO fallback."""
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        if creds.token:
            return creds.token
    except Exception:
        pass

    sso_bin = "/google/data/ro/teams/oneplatform/sso"
    user = os.environ.get("USER", "summitt")
    if os.path.exists(sso_bin):
        out = subprocess.check_output(
            [sso_bin, f"{user}@google.com", "https://www.googleapis.com/auth/cloud-platform"],
            text=True,
        )
        return out.strip().splitlines()[-1]

    out = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True)
    return out.strip()


def _api_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Executes an authenticated JSON request against the Vertex AI v1beta1 API."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {err.code} for {method} {url}: {err_body}") from err


def evaluate_trajectory_policy_compliance(instance: dict[str, Any]) -> dict[str, Any]:
    """Deterministic custom code metric verifying multi-turn tool ordering and policy guardrails.

    Checks:
    1. `verify_user_session` is called before any `search_*`, `get_weather_forecast`,
       or `transfer_to_booking_orchestrator` call.
    2. In any turn where `verify_user_session` returns `authenticated=False`, no
       downstream search or booking tool is called in that turn.
    3. If `transfer_to_booking_orchestrator` returns `status=CONFIRMED`, both
       `reservation_id` and `transaction_id` appear in the final response.
    """
    agent_data = instance.get("agent_data") or {}
    turns = agent_data.get("turns") or []
    response_text = str(instance.get("response") or "")

    checks_passed = 0
    total_checks = 3
    notes: list[str] = []

    session_verified_ever = False
    ordering_violation = False
    unauth_guardrail_violation = False
    expected_ids: list[str] = []

    protected_tools = {
        "search_flights",
        "search_hotels",
        "search_rental_cars",
        "get_weather_forecast",
        "transfer_to_booking_orchestrator",
    }

    for turn in turns:
        events = turn.get("events") or []
        turn_unauthenticated = False
        for event in events:
            content = event.get("content") or {}
            for part in content.get("parts") or []:
                fc = part.get("functionCall") or part.get("function_call")
                fr = part.get("functionResponse") or part.get("function_response")
                if fc:
                    tool_name = fc.get("name", "")
                    if tool_name == "verify_user_session":
                        session_verified_ever = True
                    elif tool_name in protected_tools:
                        if not session_verified_ever:
                            ordering_violation = True
                        if turn_unauthenticated:
                            unauth_guardrail_violation = True
                if fr:
                    tool_name = fr.get("name", "")
                    resp_obj = fr.get("response") or {}
                    if tool_name == "verify_user_session":
                        if resp_obj.get("authenticated") is False:
                            turn_unauthenticated = True
                        elif resp_obj.get("authenticated") is True:
                            turn_unauthenticated = False
                    elif tool_name == "transfer_to_booking_orchestrator":
                        if resp_obj.get("status") == "CONFIRMED":
                            for key in ("reservation_id", "transaction_id"):
                                val = resp_obj.get(key)
                                if val:
                                    expected_ids.append(str(val))

    if session_verified_ever and not ordering_violation:
        checks_passed += 1
        notes.append("PASS: verify_user_session preceded all protected tool calls.")
    else:
        notes.append("FAIL: Protected tool called before verify_user_session.")

    if not unauth_guardrail_violation:
        checks_passed += 1
        notes.append("PASS: Unauthenticated session guardrail respected across all turns.")
    else:
        notes.append("FAIL: Protected tool called after verify_user_session returned authenticated=False.")

    missing_ids = [cid for cid in expected_ids if cid not in response_text]
    if not missing_ids:
        checks_passed += 1
        notes.append("PASS: Final response includes all confirmed reservation/transaction IDs.")
    else:
        notes.append(f"FAIL: Final response missing confirmed IDs: {missing_ids}.")

    score = round(checks_passed / total_checks, 4)
    return {
        "score": score,
        "explanation": " | ".join(notes),
    }


def register_custom_rubric_metrics(
    project_id: str,
    location: str,
    token: str,
) -> dict[str, str]:
    """Registers or updates custom rubric metrics in Vertex AI `evaluationMetrics`.

    Reuses an existing `EvaluationMetric` only when its `metricPromptTemplate`
    and `parsingFunction` match the current spec; otherwise creates a fresh
    `EvaluationMetric` and deletes stale duplicates with the same title.

    Returns a mapping from metric title to full `evaluationMetrics` resource name.
    """
    base_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{location}"
    existing_resp = _api_request("GET", f"{base_url}/evaluationMetrics", token)
    existing_metrics = existing_resp.get("evaluationMetrics") or []

    by_title: dict[str, list[dict[str, Any]]] = {}
    for m in existing_metrics:
        title = (m.get("metric") or {}).get("metadata", {}).get("title") or m.get("displayName")
        if title and m.get("name"):
            by_title.setdefault(title, []).append(m)

    registered: dict[str, str] = {}
    for spec in CUSTOM_RUBRIC_METRIC_SPECS:
        title = spec["title"]
        desired_llm_spec = (spec.get("metric") or {}).get("llmBasedMetricSpec") or {}
        desired_template = desired_llm_spec.get("metricPromptTemplate", "")
        desired_parser = (
            (desired_llm_spec.get("resultParserConfig") or {})
            .get("customCodeParserConfig", {})
            .get("parsingFunction", "")
        )

        matching_name: str | None = None
        stale_names: list[str] = []
        for m in by_title.get(title, []):
            m_metric = m.get("metric") or {}
            score_range = (m_metric.get("metadata") or {}).get("scoreRange")
            m_llm = m_metric.get("llmBasedMetricSpec") or {}
            m_template = m_llm.get("metricPromptTemplate", "")
            m_parser = (
                (m_llm.get("resultParserConfig") or {})
                .get("customCodeParserConfig", {})
                .get("parsingFunction", "")
            )
            if (
                matching_name is None
                and score_range
                and m_template == desired_template
                and m_parser == desired_parser
            ):
                matching_name = m["name"]
            else:
                stale_names.append(m["name"])

        if matching_name:
            registered[title] = matching_name
        else:
            payload = {
                "displayName": spec["displayName"],
                "description": spec["description"],
                "metric": spec["metric"],
            }
            created = _api_request("POST", f"{base_url}/evaluationMetrics", token, payload)
            registered[title] = created["name"]

        for stale_name in stale_names:
            try:
                _api_request(
                    "DELETE",
                    f"https://{location}-aiplatform.googleapis.com/v1beta1/{stale_name}",
                    token,
                )
            except Exception as exc:
                print(f"  [warn] Could not delete stale metric {stale_name}: {exc}", flush=True)

    return registered


def load_reasoning_engine_resources(project_id: str, location: str) -> dict[str, str]:
    """Loads deployed Reasoning Engine resource paths from `agent_engine_outputs.json` or env."""
    resources: dict[str, str] = {}
    if os.path.exists(AGENT_OUTPUTS_PATH):
        with open(AGENT_OUTPUTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
            for key in ("RootRouter", "BookingOrchestrator"):
                if data.get(key):
                    resources[key] = data[key]

    if os.environ.get("ROOT_ROUTER_RESOURCE"):
        resources["RootRouter"] = os.environ["ROOT_ROUTER_RESOURCE"]
    if os.environ.get("BOOKING_ORCHESTRATOR_RESOURCE"):
        resources["BookingOrchestrator"] = os.environ["BOOKING_ORCHESTRATOR_RESOURCE"]

    return resources


def configure_online_evaluators(
    project_id: str,
    location: str,
    token: str,
    registered_metrics: dict[str, str],
    sampling_rate: float = 1.0,
) -> list[dict[str, Any]]:
    """Creates or verifies active `onlineEvaluators` on RootRouter and BookingOrchestrator."""
    base_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{location}"
    existing_resp = _api_request(
        "GET", f"{base_url}/onlineEvaluators?pageSize=100&orderBy=create_time%20desc", token
    )
    existing_evaluators = existing_resp.get("onlineEvaluators") or []
    by_engine_id: dict[str, dict[str, Any]] = {}
    for ev in existing_evaluators:
        ar = ev.get("agentResource", "")
        if ar:
            eng_key = ar.rstrip("/").split("/")[-1]
            if eng_key not in by_engine_id:
                by_engine_id[eng_key] = ev

    engine_resources = load_reasoning_engine_resources(project_id, location)
    configured: list[dict[str, Any]] = []

    agent_metric_map = {
        "RootRouter": [
            "travel_concierge_rubric_quality_v1",
            "travel_concierge_parsed_rubric_v1",
        ],
        "BookingOrchestrator": [
            "booking_transaction_rubric_v1",
            "travel_concierge_parsed_rubric_v1",
        ],
    }

    created_or_updated_any = False
    for agent_name, agent_resource in engine_resources.items():
        engine_id = agent_resource.rstrip("/").split("/")[-1]
        canonical_agent_resource = (
            f"projects/{project_id}/locations/{location}/reasoningEngines/{engine_id}"
        )

        metric_sources: list[dict[str, Any]] = [
            {"metric": {"predefinedMetricSpec": {"metricSpecName": "final_response_quality_v1"}}},
            {"metric": {"predefinedMetricSpec": {"metricSpecName": "tool_use_quality_v1"}}},
            {"metric": {"predefinedMetricSpec": {"metricSpecName": "hallucination_v1"}}},
            {"metric": {"predefinedMetricSpec": {"metricSpecName": "safety_v1"}}},
        ]
        desired_custom_refs: set[str] = set()
        for custom_title in agent_metric_map.get(agent_name, []):
            if custom_title in registered_metrics:
                ref = registered_metrics[custom_title]
                metric_sources.append({"metricResourceName": ref})
                desired_custom_refs.add(ref.rstrip("/").split("/")[-1])

        existing = by_engine_id.get(engine_id)
        if existing and existing.get("state") == "ACTIVE":
            existing_custom_refs = {
                ms["metricResourceName"].rstrip("/").split("/")[-1]
                for ms in (existing.get("metricSources") or [])
                if ms.get("metricResourceName")
            }
            if existing_custom_refs == desired_custom_refs:
                configured.append(existing)
                continue
            _api_request(
                "DELETE",
                f"https://{location}-aiplatform.googleapis.com/v1beta1/{existing['name']}",
                token,
            )

        sampling_pct = max(1, min(100, int(round(sampling_rate * 100))))
        payload = {
            "displayName": f"{agent_name} Custom Rubric Online Evaluator"[:63],
            "agentResource": canonical_agent_resource,
            "metricSources": metric_sources,
            "cloudObservability": {
                "traceScope": {},
                "openTelemetry": {
                    "semconvVersion": "1.39.0",
                },
            },
            "config": {
                "maxEvaluatedSamplesPerRun": 50,
                "randomSampling": {
                    "percentage": sampling_pct,
                },
            },
        }
        created = _api_request("POST", f"{base_url}/onlineEvaluators", token, payload)
        created_or_updated_any = True
        op_name = created.get("name", "")
        if op_name and "/operations/" in op_name and not created.get("done"):
            for _ in range(10):
                time.sleep(1.0)
                op_state = _api_request(
                    "GET",
                    f"https://{location}-aiplatform.googleapis.com/v1beta1/{op_name}",
                    token,
                )
                if op_state.get("done"):
                    created = op_state
                    break
        if "response" in created and isinstance(created["response"], dict):
            configured.append(created["response"])
        else:
            configured.append(created)

    if created_or_updated_any:
        refreshed = _api_request(
            "GET", f"{base_url}/onlineEvaluators?pageSize=100&orderBy=create_time%20desc", token
        )
        refreshed_map: dict[str, dict[str, Any]] = {}
        for ev in refreshed.get("onlineEvaluators") or []:
            ar = ev.get("agentResource", "")
            if ar:
                eng_key = ar.rstrip("/").split("/")[-1]
                if eng_key not in refreshed_map:
                    refreshed_map[eng_key] = ev
        configured = [
            refreshed_map.get(res.rstrip("/").split("/")[-1], {})
            for res in engine_resources.values()
            if res.rstrip("/").split("/")[-1] in refreshed_map
        ]

    return configured


def _build_evaluation_instance(case: dict[str, Any]) -> eval_types.EvaluationInstance:
    """Converts a dataset case dictionary into a `vertexai._genai.types.EvaluationInstance`."""
    agent_data_dict = case["agent_data"]
    turns = agent_data_dict.get("turns") or []

    user_contents: list[genai_types.Content] = []
    history_lines: list[str] = []
    for turn in turns:
        for ev in turn.get("events") or []:
            content = ev.get("content") or {}
            author = ev.get("author", "user")
            for part in content.get("parts") or []:
                if "text" in part and part["text"]:
                    history_lines.append(f"{author}: {part['text']}")
                    if author == "user":
                        user_contents.append(
                            genai_types.Content(
                                role="user",
                                parts=[genai_types.Part(text=part["text"])],
                            )
                        )
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    history_lines.append(
                        f"{author} [tool_call]: {fc.get('name')}({json.dumps(fc.get('args', {}))})"
                    )
                elif "functionResponse" in part:
                    fr = part["functionResponse"]
                    history_lines.append(
                        f"{author} [tool_response]: {fr.get('name')} -> {json.dumps(fr.get('response', {}))}"
                    )

    if not user_contents:
        user_contents = [
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=case["prompt"])],
            )
        ]

    rubric_groups_raw = case.get("rubric_groups") or {}
    rubric_groups_typed: dict[str, eval_types.RubricGroup] = {}
    for group_key, group_val in rubric_groups_raw.items():
        rubrics_list = [
            eval_types.evals.Rubric.model_validate(r)
            for r in (group_val.get("rubrics") or [])
        ]
        rubric_groups_typed[group_key] = eval_types.RubricGroup(rubrics=rubrics_list)

    agent_data_typed = eval_types.evals.AgentData.model_validate(agent_data_dict)

    return eval_types.EvaluationInstance(
        prompt=eval_types.evals.InstanceData(
            contents=eval_types.evals.InstanceDataContents(
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=case["prompt"])],
                    )
                ]
            )
        ),
        response=eval_types.evals.InstanceData(
            contents=eval_types.evals.InstanceDataContents(
                contents=[
                    genai_types.Content(
                        role="model",
                        parts=[genai_types.Part(text=case["response"])],
                    )
                ]
            )
        ),
        other_data=eval_types.MapInstance(
            map_instance={
                "conversation_history": eval_types.evals.InstanceData(
                    text="\n".join(history_lines)
                )
            }
        ),
        agent_data=agent_data_typed,
        rubric_groups=rubric_groups_typed or None,
    )


def run_offline_multi_turn_evals(
    project_id: str,
    location: str,
    token: str,
    dataset_path: str = DEFAULT_DATASET_PATH,
) -> list[dict[str, Any]]:
    """Evaluates all multi-turn travel concierge cases against predefined and custom rubrics."""
    with open(dataset_path, encoding="utf-8") as f:
        cases: list[dict[str, Any]] = json.load(f)

    creds = oauth2_credentials.Credentials(token=token)

    def _eval_single_metric(
        case_id: str,
        metric_key: str,
        metric_obj: eval_types.Metric,
        inst: eval_types.EvaluationInstance,
        include_rubric_id: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        thread_client = vertexai.Client(
            project=project_id,
            location=location,
            credentials=creds,
            http_options=genai_types.HttpOptions(timeout=180000),
        )
        try:
            resp = thread_client.evals._evaluate_instances(
                metrics=[metric_obj],
                instance=inst,
            )
        except Exception as exc:
            print(f"    [{case_id}] {metric_key}: transient error ({exc}), retrying once...", flush=True)
            time.sleep(3)
            resp = thread_client.evals._evaluate_instances(
                metrics=[metric_obj],
                instance=inst,
            )
        m_res = resp.metric_results[0] if resp.metric_results else None
        verdicts = []
        if m_res and m_res.rubric_verdicts:
            for rv in m_res.rubric_verdicts:
                r_id = rv.evaluated_rubric.rubric_id if rv.evaluated_rubric else ""
                desc = ""
                if (
                    rv.evaluated_rubric
                    and rv.evaluated_rubric.content
                    and rv.evaluated_rubric.content.property
                ):
                    desc = rv.evaluated_rubric.content.property.description or ""
                item: dict[str, Any] = {
                    "description" if include_rubric_id else "rubric": desc,
                    "verdict": rv.verdict,
                    "reasoning": rv.reasoning,
                }
                if include_rubric_id:
                    item["rubric_id"] = r_id
                verdicts.append(item)
        score = m_res.score if m_res else None
        print(
            f"    [{case_id}] {metric_key}: score={score} ({len(verdicts)} rubrics)",
            flush=True,
        )
        return metric_key, {
            "score": score,
            "rubric_verdicts": verdicts,
        }

    results_summary: list[dict[str, Any]] = []
    for case in cases:
        case_id = case["eval_case_id"]
        print(f"  -> Evaluating case {case_id}...", flush=True)
        instance = _build_evaluation_instance(case)
        rubric_only_instance = instance.model_copy(update={"agent_data": None})
        case_metrics: dict[str, Any] = {}

        tasks_to_run: list[tuple[str, eval_types.Metric, eval_types.EvaluationInstance, bool]] = [
            (m_name, eval_types.Metric(name=m_name), instance, False)
            for m_name in PREDEFINED_MULTI_TURN_METRICS
        ]
        tasks_to_run.append(
            (
                "custom_rubric_group_travel_concierge",
                eval_types.Metric(
                    name="general_quality_v1",
                    metric_spec_parameters={
                        "rubric_group_key": "travel_concierge_rubrics"
                    },
                ),
                rubric_only_instance,
                True,
            )
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_eval_single_metric, case_id, m_key, m_obj, inst, inc_id)
                for m_key, m_obj, inst, inc_id in tasks_to_run
            ]
            for fut in concurrent.futures.as_completed(futures):
                m_key, m_data = fut.result()
                case_metrics[m_key] = m_data

        # 3. Deterministic Custom Code Metric (Policy & Tool Ordering Compliance)
        code_metric_res = evaluate_trajectory_policy_compliance(case)
        case_metrics["custom_code_trajectory_policy_compliance"] = code_metric_res

        results_summary.append(
            {
                "eval_case_id": case_id,
                "scenario": case.get("scenario", ""),
                "metrics": case_metrics,
            }
        )

    return results_summary


def create_and_poll_evaluation_run(
    project_id: str,
    location: str,
    token: str,
    registered_metrics: dict[str, str],
    dataset_path: str = DEFAULT_DATASET_PATH,
    gcs_bucket: str | None = None,
) -> dict[str, Any]:
    """Uploads multi-turn `EvaluationItem`s to GCS, creates an `EvaluationSet`, and runs an `EvaluationRun`."""
    bucket_name = gcs_bucket or f"{project_id}-deploy-artifacts"
    base_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project_id}/locations/{location}"

    with open(dataset_path, encoding="utf-8") as f:
        cases: list[dict[str, Any]] = json.load(f)

    item_names: list[str] = []
    run_ts = int(time.time())

    for case in cases:
        case_id = case["eval_case_id"]
        agent_data_copy = json.loads(json.dumps(case["agent_data"]))
        eval_item_payload = {
            "prompt": {"text": case["prompt"]},
            "candidateResponses": [
                {
                    "candidate": "RootRouter",
                    "agentData": agent_data_copy,
                }
            ],
        }
        object_name = f"evals/items/{run_ts}_{case_id}.json"
        upload_url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{bucket_name}/o"
            f"?uploadType=media&name={object_name}"
        )
        req = urllib.request.Request(
            upload_url,
            data=json.dumps(eval_item_payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()

        gcs_uri = f"gs://{bucket_name}/{object_name}"
        created_item = _api_request(
            "POST",
            f"{base_url}/evaluationItems",
            token,
            {
                "displayName": f"travel_concierge_{case_id}",
                "evaluationItemType": "REQUEST",
                "gcsUri": gcs_uri,
            },
        )
        item_names.append(created_item["name"])

    eval_set = _api_request(
        "POST",
        f"{base_url}/evaluationSets",
        token,
        {
            "displayName": f"travel_concierge_multi_turn_set_{run_ts}",
            "evaluationItems": item_names,
        },
    )

    run_metrics: list[dict[str, Any]] = [
        {"metric": m_name, "metricConfig": {"predefinedMetricSpec": {"metricSpecName": m_name}}}
        for m_name in PREDEFINED_MULTI_TURN_METRICS
    ]
    for title, res_name in registered_metrics.items():
        run_metrics.append(
            {
                "metric": title,
                "metricResourceName": res_name,
            }
        )

    eval_run = _api_request(
        "POST",
        f"{base_url}/evaluationRuns",
        token,
        {
            "displayName": f"travel_concierge_multi_turn_rubric_eval_{run_ts}",
            "dataSource": {"evaluationSet": eval_set["name"]},
            "evaluationConfig": {
                "metrics": run_metrics,
                "outputConfig": {
                    "gcsDestination": {
                        "outputUriPrefix": f"gs://{bucket_name}/evals/runs/{run_ts}"
                    }
                },
            },
        },
    )

    run_name = eval_run["name"]
    for _ in range(36):
        current = _api_request("GET", f"https://{location}-aiplatform.googleapis.com/v1beta1/{run_name}", token)
        state = current.get("state", "")
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return current
        time.sleep(5)

    return eval_run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure and run Online & Offline Agent Evals with Custom Rubrics."
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        help="Google Cloud project ID (defaults to GOOGLE_CLOUD_PROJECT).",
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        help="Vertex AI region (default: us-central1).",
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET_PATH,
        help="Path to multi-turn evaluation dataset JSON.",
    )
    parser.add_argument(
        "--sampling-rate",
        type=float,
        default=1.0,
        help="Online evaluator sampling rate (0.0 to 1.0, default: 1.0).",
    )
    parser.add_argument(
        "--skip-online",
        action="store_true",
        help="Skip registering custom metrics and online evaluators.",
    )
    parser.add_argument(
        "--skip-offline",
        action="store_true",
        help="Skip offline multi-turn dataset evaluation.",
    )
    parser.add_argument(
        "--create-evaluation-run",
        action="store_true",
        help="Also create and poll a managed Vertex AI EvaluationRun in GCS.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional path to write full evaluation report JSON.",
    )
    args = parser.parse_args()

    if not args.project_id:
        print("Error: --project-id or GOOGLE_CLOUD_PROJECT is required.", file=sys.stderr)
        sys.exit(1)

    token = get_access_token()
    report: dict[str, Any] = {
        "project_id": args.project_id,
        "location": args.location,
        "registered_metrics": {},
        "online_evaluators": [],
        "offline_case_results": [],
        "evaluation_run": None,
    }

    if not args.skip_online:
        print(f"[1/3] Registering custom rubric metrics in {args.project_id}/{args.location}...")
        registered = register_custom_rubric_metrics(args.project_id, args.location, token)
        report["registered_metrics"] = registered
        for title, res_name in registered.items():
            print(f"  - {title}: {res_name}")

        print("[2/3] Configuring active onlineEvaluators on deployed Reasoning Engines...")
        evaluators = configure_online_evaluators(
            args.project_id,
            args.location,
            token,
            registered,
            sampling_rate=args.sampling_rate,
        )
        report["online_evaluators"] = [
            {
                "name": ev.get("name"),
                "displayName": ev.get("displayName"),
                "agentResource": ev.get("agentResource"),
                "state": ev.get("state"),
                "samplingRate": ev.get("samplingRate"),
                "metricSourcesCount": len(ev.get("metricSources") or []),
            }
            for ev in evaluators
        ]
        for ev in report["online_evaluators"]:
            print(
                f"  - {ev['displayName']} -> {ev['name']} "
                f"(state={ev['state']}, metrics={ev['metricSourcesCount']})"
            )

    if not args.skip_offline:
        print(f"[3/3] Running offline multi-turn evaluations on {args.dataset}...")
        offline_results = run_offline_multi_turn_evals(
            args.project_id,
            args.location,
            token,
            dataset_path=args.dataset,
        )
        report["offline_case_results"] = offline_results
        for case_res in offline_results:
            print(f"\n  Case: {case_res['eval_case_id']} ({case_res['scenario']})")
            for m_name, m_val in case_res["metrics"].items():
                score = m_val.get("score")
                verdicts = m_val.get("rubric_verdicts") or []
                passed_v = sum(1 for v in verdicts if v.get("verdict") is True)
                if verdicts:
                    print(f"    - {m_name}: score={score} ({passed_v}/{len(verdicts)} rubrics passed)")
                else:
                    print(f"    - {m_name}: score={score} ({m_val.get('explanation', '')})")

    if args.create_evaluation_run:
        print("\n[Bonus] Creating managed Vertex AI EvaluationRun from EvaluationSet...")
        registered = report["registered_metrics"] or register_custom_rubric_metrics(
            args.project_id, args.location, token
        )
        eval_run = create_and_poll_evaluation_run(
            args.project_id,
            args.location,
            token,
            registered,
            dataset_path=args.dataset,
        )
        report["evaluation_run"] = {
            "name": eval_run.get("name"),
            "displayName": eval_run.get("displayName"),
            "state": eval_run.get("state"),
            "evaluationSet": (eval_run.get("dataSource") or {}).get("evaluationSet"),
            "evaluationResults": eval_run.get("evaluationResults"),
        }
        print(
            f"  - EvaluationRun: {eval_run.get('name')} (state={eval_run.get('state')})"
        )

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved full evaluation report to {args.output_json}")


if __name__ == "__main__":
    main()
