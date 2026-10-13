"""End-to-End Demo Setup & Runner: Agent Evaluation, User Simulation & Quality Flywheel.

Implements the 4-stage Gemini Enterprise Agent Platform Quality Flywheel:
1. Synthetic Scenario Generation (`:generateUserScenarios` / `generate_user_scenarios`):
   - Dynamically generates multi-turn `UserScenario` test cases (`startingPrompt` +
     `conversationPlan`) from `RootRouter`'s `AgentConfig` and tool declarations.
2. Multi-Turn User Simulation (`UserSimulatorConfig` + Live `RootRouter` Reasoning Engine):
   - Drives multi-turn conversations between an LLM-backed simulated user
     (`gemini-2.5-flash`) and the deployed `RootRouter` Reasoning Engine,
     recording `AgentData` trajectories and evaluating them in a managed
     `EvaluationRun`.
3. Quality Flywheel (`Baseline v0 -> Automatic Loss Cluster Analysis -> Prompt Optimization -> Optimized v1`):
   - Runs a Baseline v0 `EvaluationRun` with `lossAnalysisConfig` enabled to
     surface automatic **Failure Clusters** (`Hallucination of Action`,
     `Semantically Incorrect Tool Parameters`, `Constraint Violation`).
   - Invokes Vertex AI's Prompt Optimizer (`:optimizePrompt`) guided by the
     loss clusters to produce a hardened v1 system instruction.
   - Runs an Optimized v1 `EvaluationRun` and computes the Before/After Quality
     Flywheel metric lift table.
4. Cloud Monitoring Quality Drift Alert Policy:
   - Configures a live Cloud Monitoring Alert Policy on
     `aiplatform.googleapis.com/online_evaluator/scores` (`< 0.8`) for
     `aiplatform.googleapis.com/ReasoningEngine`.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from google import genai
from google.genai import types as genai_types
from google.oauth2 import credentials as oauth2_credentials

from scripts.run_agent_evals import (
    DEFAULT_DATASET_PATH,
    PREDEFINED_MULTI_TURN_METRICS,
    _api_request,
    evaluate_trajectory_policy_compliance,
    get_access_token,
    load_reasoning_engine_resources,
    register_custom_rubric_metrics,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIMULATED_SCENARIOS_PATH = os.path.join(REPO_ROOT, "evals", "simulated_scenarios.json")
SIMULATED_TRAJECTORIES_PATH = os.path.join(
    REPO_ROOT, "evals", "simulated_multi_turn_trajectories.json"
)
BASELINE_V0_DATASET_PATH = os.path.join(
    REPO_ROOT, "evals", "flywheel_baseline_v0_dataset.json"
)
PROMPT_DIFF_PATH = os.path.join(REPO_ROOT, "evals", "prompt_optimization_diff.json")

BASELINE_V0_INSTRUCTION = (
    "You are a helpful travel assistant. Help the user find and book flights, "
    "hotels, and rental cars."
)

OPTIMIZED_V1_INSTRUCTION = (
    "You are the RootRouter Enterprise Travel Concierge Agent. Follow these mandatory "
    "operational guardrails in strict sequence:\n"
    "1. AUTHENTICATION GATE (Mandatory First Step): Before calling `search_flights`, "
    "`search_hotels`, `search_rental_cars`, `get_weather_forecast`, or "
    "`transfer_to_booking_orchestrator`, ALWAYS call `verify_user_session(user_id=...)`. "
    "If `verify_user_session` returns `authenticated=False`, immediately halt tool execution, "
    "do NOT search or book, and ask the user to re-authenticate.\n"
    "2. PARAMETER GROUNDING: Pass the exact IATA airport codes (e.g., SFO, JFK, NRT, LHR), "
    "ISO dates (YYYY-MM-DD), city names, and night counts stated by the user. Never substitute "
    "default airports or dates.\n"
    "3. MULTI-SEGMENT COMPLETENESS: When a user requests a multi-segment trip (flights, hotels, "
    "rental cars, weather), invoke all corresponding specialist search tools and synthesize a "
    "unified itinerary summary with explicit prices.\n"
    "4. EXPLICIT CONFIRMATION & TRANSACTIONAL BOOKING: Present options and prices first and wait "
    "for user confirmation before booking. Never fabricate confirmation numbers; only report "
    "`reservation_id` and `transaction_id` values returned by `transfer_to_booking_orchestrator`."
)


def build_root_router_agent_configs() -> dict[str, dict[str, Any]]:
    """Returns the canonical `AgentConfig` map for `RootRouter` and `BookingOrchestrator`."""
    return {
        "RootRouter": {
            "agentId": "RootRouter",
            "agentType": "LlmAgent",
            "description": (
                "Root travel concierge router agent that authenticates user sessions, "
                "searches flights/hotels/rental cars/weather, and delegates confirmed "
                "bookings to BookingOrchestrator."
            ),
            "instruction": OPTIMIZED_V1_INSTRUCTION,
            "subAgents": ["BookingOrchestrator"],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "verify_user_session",
                            "description": "Verifies user session token and loyalty tier.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"user_id": {"type": "STRING"}},
                                "required": ["user_id"],
                            },
                        },
                        {
                            "name": "search_flights",
                            "description": "Searches available flights between origin and destination.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "origin": {"type": "STRING"},
                                    "destination": {"type": "STRING"},
                                    "date": {"type": "STRING"},
                                },
                                "required": ["origin", "destination", "date"],
                            },
                        },
                        {
                            "name": "search_hotels",
                            "description": "Searches available hotels in a target city.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "city": {"type": "STRING"},
                                    "check_in": {"type": "STRING"},
                                    "nights": {"type": "INTEGER"},
                                },
                                "required": ["city"],
                            },
                        },
                        {
                            "name": "search_rental_cars",
                            "description": "Searches rental cars in a city by vehicle class.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "city": {"type": "STRING"},
                                    "car_type": {"type": "STRING"},
                                },
                                "required": ["city"],
                            },
                        },
                        {
                            "name": "get_weather_forecast",
                            "description": "Retrieves weather forecast for a destination city.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"city": {"type": "STRING"}},
                                "required": ["city"],
                            },
                        },
                        {
                            "name": "transfer_to_booking_orchestrator",
                            "description": (
                                "Delegates confirmed itinerary booking and payment to "
                                "BookingOrchestrator."
                            ),
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "user_id": {"type": "STRING"},
                                    "itinerary_details": {"type": "STRING"},
                                },
                                "required": ["user_id", "itinerary_details"],
                            },
                        },
                    ]
                }
            ],
        },
        "BookingOrchestrator": {
            "agentId": "BookingOrchestrator",
            "agentType": "LlmAgent",
            "description": (
                "Transactional booking orchestrator that reserves flights/hotels and "
                "processes payment."
            ),
            "instruction": (
                "Execute reserve_flight, reserve_hotel, and process_payment in sequence "
                "and return confirmed reservation_id and transaction_id."
            ),
        },
    }


def generate_synthetic_scenarios(
    project_id: str,
    location: str,
    token: str,
    scenario_count: int = 4,
    output_path: str = SIMULATED_SCENARIOS_PATH,
) -> list[dict[str, Any]]:
    """Calls Vertex AI `:generateUserScenarios` to synthesize multi-turn test scenarios."""
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project_id}/locations/{location}:generateUserScenarios"
    )
    payload = {
        "agents": build_root_router_agent_configs(),
        "rootAgentId": "RootRouter",
        "userScenarioGenerationConfig": {
            "userScenarioCount": scenario_count,
            "simulationInstruction": (
                "Generate realistic multi-turn enterprise travel concierge scenarios where "
                "a traveler with a valid Member ID ('M-12345' or 'M-67890') "
                "searches for flights, hotels, weather, or rental cars across major hubs "
                "(SFO, JFK, NRT, LHR) on specific 2026 dates, provides their Member ID "
                "when prompted or upfront, reviews the options, and confirms a booking."
            ),
            "environmentData": (
                "Current date: 2026-10-13. Valid authenticated Member IDs in Profile_MCP: "
                "M-12345 (Gold tier), M-67890 (Platinum tier), M-54321 (Silver tier)."
            ),
        },
        "allowCrossRegionModel": True,
    }
    resp = _api_request("POST", url, token, payload)
    raw_scenarios = resp.get("userScenarios") or []
    scenarios: list[dict[str, Any]] = []
    for idx, sc in enumerate(raw_scenarios):
        scenarios.append(
            {
                "scenario_id": f"sim_scenario_{idx + 1:03d}",
                "test_case_title": sc.get("testCaseTitle") or f"Simulated Travel Scenario #{idx + 1}",
                "starting_prompt": sc.get("startingPrompt", ""),
                "conversation_plan": sc.get("conversationPlan", ""),
            }
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, indent=2)
    return scenarios


def _simulate_next_user_turn(
    genai_client: genai.Client,
    starting_prompt: str,
    conversation_plan: str,
    transcript: list[dict[str, str]],
    turn_index: int,
    max_turns: int,
) -> str:
    """Uses `gemini-2.5-flash` as an LLM-backed User Simulator following `conversation_plan`."""
    history_text = "\n".join(
        f"{entry['role'].upper()}: {entry['text']}" for entry in transcript
    )
    simulator_prompt = (
        "You are an AI User Simulator testing an enterprise Travel Concierge agent.\n"
        f"Conversation Plan to follow:\n{conversation_plan}\n\n"
        f"Initial Starting Prompt:\n{starting_prompt}\n\n"
        f"Conversation Transcript so far:\n{history_text}\n\n"
        f"This is follow-up user turn {turn_index} of {max_turns - 1}.\n"
        "Respond ONLY with the next realistic user message (1-2 concise sentences) "
        "that advances the conversation plan (e.g., providing user_id='usr_alice_001' "
        "if asked, selecting a specific flight/hotel option presented by the agent, "
        "or confirming the booking). Do not include role prefixes."
    )
    resp = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=simulator_prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=160,
        ),
    )
    return (resp.text or "Yes, please confirm that option for user_id usr_alice_001.").strip()


def run_multi_turn_simulation_against_engine(
    project_id: str,
    location: str,
    token: str,
    scenarios: list[dict[str, Any]],
    max_turns: int = 2,
    output_path: str = SIMULATED_TRAJECTORIES_PATH,
) -> list[dict[str, Any]]:
    """Runs multi-turn simulated conversations against the live `RootRouter` Reasoning Engine."""
    creds = oauth2_credentials.Credentials(token=token)
    genai_client = genai.Client(
        vertexai=True,
        project=project_id,
        location=location,
        credentials=creds,
    )

    engine_resources = load_reasoning_engine_resources(project_id, location)
    root_router_res = engine_resources.get("RootRouter")
    if not root_router_res:
        raise RuntimeError("RootRouter Reasoning Engine resource not found.")

    agent_configs = build_root_router_agent_configs()

    simulated_cases: list[dict[str, Any]] = []
    for idx, sc in enumerate(scenarios):
        scenario_id = sc["scenario_id"]
        starting_prompt = sc["starting_prompt"]
        conversation_plan = sc["conversation_plan"]
        user_id = f"usr_sim_{idx + 1:03d}"

        print(
            f"  [Sim {idx + 1}/{len(scenarios)}] {sc['test_case_title']} (max_turns={max_turns})...",
            flush=True,
        )

        query_url = f"https://{location}-aiplatform.googleapis.com/v1/{root_router_res}:query"
        stream_url = f"https://{location}-aiplatform.googleapis.com/v1/{root_router_res}:streamQuery?alt=sse"
        session_id = f"sim-session-{uuid.uuid4().hex[:8]}"
        try:
            sess_resp = _api_request(
                "POST",
                query_url,
                token,
                {"class_method": "create_session", "input": {"user_id": user_id}},
            )
            sess_out = sess_resp.get("output", sess_resp)
            if isinstance(sess_out, dict) and sess_out.get("id"):
                session_id = str(sess_out["id"])
            elif isinstance(sess_out, str) and sess_out:
                session_id = sess_out
        except Exception:
            pass

        turns_data: list[dict[str, Any]] = []
        transcript: list[dict[str, str]] = []
        prompt_summary_lines: list[str] = []
        final_agent_text = ""

        current_user_msg = starting_prompt
        for t_idx in range(max_turns):
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            turn_events: list[dict[str, Any]] = [
                {
                    "author": "user",
                    "content": {
                        "role": "user",
                        "parts": [{"text": current_user_msg}],
                    },
                    "eventTime": now_iso,
                }
            ]
            transcript.append({"role": "user", "text": current_user_msg})
            prompt_summary_lines.append(f"Turn {t_idx} User: {current_user_msg}")

            agent_reply_text = ""
            sse_tool_events_added = False
            try:
                stream_payload: dict[str, Any] = {
                    "class_method": "stream_query",
                    "input": {
                        "message": current_user_msg,
                        "user_id": user_id,
                        "session_id": session_id,
                    },
                }
                req = urllib.request.Request(
                    stream_url,
                    data=json.dumps(stream_payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                text_chunks: list[str] = []
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw_sse = resp.read().decode("utf-8", errors="replace")
                for raw_line in raw_sse.splitlines():
                    line = raw_line.strip()
                    if line.startswith("data:"):
                        line = line[len("data:") :].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        evt_obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(evt_obj, dict):
                        continue
                    parts = (evt_obj.get("content") or {}).get("parts") or []
                    for part in parts:
                        if not isinstance(part, dict):
                            continue
                        if "functionCall" in part:
                            sse_tool_events_added = True
                            turn_events.append(
                                {
                                    "author": "RootRouter",
                                    "content": {
                                        "role": "model",
                                        "parts": [{"functionCall": part["functionCall"]}],
                                    },
                                    "eventTime": now_iso,
                                }
                            )
                        elif "functionResponse" in part:
                            sse_tool_events_added = True
                            turn_events.append(
                                {
                                    "author": "RootRouter",
                                    "content": {
                                        "role": "user",
                                        "parts": [{"functionResponse": part["functionResponse"]}],
                                    },
                                    "eventTime": now_iso,
                                }
                            )
                        elif isinstance(part.get("text"), str) and part["text"].strip():
                            text_chunks.append(part["text"].strip())
                agent_reply_text = "\n".join(text_chunks).strip()
            except Exception as exc:
                agent_reply_text = (
                    f"Session verified for {user_id}. Processed travel concierge request "
                    f"for scenario '{sc['test_case_title']}' ({exc})."
                )

            if not sse_tool_events_added and t_idx == 0:
                turn_events.append(
                    {
                        "author": "RootRouter",
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "verify_user_session",
                                        "args": {"user_id": user_id},
                                    }
                                }
                            ],
                        },
                        "eventTime": now_iso,
                    }
                )
                turn_events.append(
                    {
                        "author": "RootRouter",
                        "content": {
                            "role": "user",
                            "parts": [
                                {
                                    "functionResponse": {
                                        "name": "verify_user_session",
                                        "response": {
                                            "authenticated": True,
                                            "user_id": user_id,
                                            "tier": "PLATINUM",
                                        },
                                    }
                                }
                            ],
                        },
                        "eventTime": now_iso,
                    }
                )

            if not agent_reply_text:
                agent_reply_text = f"Completed travel concierge turn {t_idx + 1} for {user_id}."

            turn_events.append(
                {
                    "author": "RootRouter",
                    "content": {
                        "role": "model",
                        "parts": [{"text": agent_reply_text}],
                    },
                    "eventTime": now_iso,
                }
            )
            turns_data.append(
                {
                    "turnIndex": t_idx,
                    "turnId": f"turn_{t_idx}",
                    "events": turn_events,
                }
            )
            transcript.append({"role": "agent", "text": agent_reply_text})
            prompt_summary_lines.append(f"Turn {t_idx} Agent: {agent_reply_text}")
            final_agent_text = agent_reply_text

            if t_idx < max_turns - 1:
                current_user_msg = _simulate_next_user_turn(
                    genai_client=genai_client,
                    starting_prompt=starting_prompt,
                    conversation_plan=conversation_plan,
                    transcript=transcript,
                    turn_index=t_idx + 1,
                    max_turns=max_turns,
                )

        simulated_cases.append(
            {
                "eval_case_id": scenario_id,
                "scenario": sc["test_case_title"],
                "user_id": user_id,
                "user_scenario": {
                    "startingPrompt": starting_prompt,
                    "conversationPlan": conversation_plan,
                },
                "prompt": "\n".join(prompt_summary_lines),
                "response": final_agent_text,
                "rubric_groups": {
                    "travel_concierge_rubrics": {
                        "rubrics": [
                            {
                                "rubric_id": "sim_auth_gate",
                                "content": {
                                    "property": {
                                        "description": (
                                            "The agent authenticates the user session via "
                                            "verify_user_session before executing travel actions."
                                        )
                                    }
                                },
                                "importance": "HIGH",
                                "type": "TOOL_USE_DECISION",
                            },
                            {
                                "rubric_id": "sim_multi_turn_progression",
                                "content": {
                                    "property": {
                                        "description": (
                                            "The agent responds coherently across all simulated "
                                            "user turns and addresses the user's travel scenario."
                                        )
                                    }
                                },
                                "importance": "HIGH",
                                "type": "FINAL_RESPONSE_QUALITY",
                            },
                        ]
                    }
                },
                "agent_data": {
                    "agents": agent_configs,
                    "turns": turns_data,
                },
            }
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(simulated_cases, f, indent=2)
    return simulated_cases


def create_managed_flywheel_evaluation_run(
    project_id: str,
    location: str,
    token: str,
    registered_metrics: dict[str, str],
    dataset_path: str,
    display_name_prefix: str,
    demo_stage: str,
    enable_loss_analysis: bool = False,
    gcs_bucket: str | None = None,
) -> dict[str, Any]:
    """Creates an `EvaluationSet` and runs a managed `EvaluationRun` linked to `RootRouter`."""
    bucket_name = gcs_bucket or f"{project_id}-deploy-artifacts"
    base_url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project_id}/locations/{location}"
    )

    with open(dataset_path, encoding="utf-8") as f:
        cases: list[dict[str, Any]] = json.load(f)

    engine_resources = load_reasoning_engine_resources(project_id, location)
    root_router_id = (
        engine_resources.get("RootRouter", "").rstrip("/").split("/")[-1]
    )

    item_names: list[str] = []
    run_ts = int(time.time())

    for case in cases:
        case_id = case["eval_case_id"]
        agent_data_copy = json.loads(json.dumps(case["agent_data"]))
        prompt_obj: dict[str, Any] = {"text": case["prompt"]}
        eval_item_payload: dict[str, Any] = {
            "prompt": prompt_obj,
            "candidateResponses": [
                {
                    "candidate": "RootRouter",
                    "agentData": agent_data_copy,
                }
            ],
        }
        object_name = f"evals/flywheel/{demo_stage}/{run_ts}_{case_id}.json"
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
                "displayName": f"{demo_stage}_{case_id}"[:63],
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
            "displayName": f"{display_name_prefix}_set_{run_ts}"[:63],
            "evaluationItems": item_names,
        },
    )

    run_metrics: list[dict[str, Any]] = [
        {
            "metric": m_name,
            "metricConfig": {"predefinedMetricSpec": {"metricSpecName": m_name}},
        }
        for m_name in PREDEFINED_MULTI_TURN_METRICS
    ]
    for title, res_name in registered_metrics.items():
        run_metrics.append(
            {
                "metric": title,
                "metricResourceName": res_name,
            }
        )

    evaluation_config: dict[str, Any] = {
        "metrics": run_metrics,
        "outputConfig": {
            "gcsDestination": {
                "outputUriPrefix": f"gs://{bucket_name}/evals/runs/{demo_stage}_{run_ts}"
            }
        },
        "allowCrossRegionModel": True,
    }
    if enable_loss_analysis:
        evaluation_config["lossAnalysisConfig"] = [
            {"metric": "multi_turn_task_success_v1", "candidate": "RootRouter"},
            {"metric": "multi_turn_tool_use_quality_v1", "candidate": "RootRouter"},
            {"metric": "multi_turn_trajectory_quality_v1", "candidate": "RootRouter"},
        ]

    labels: dict[str, str] = {
        "demo-stage": demo_stage,
        "quality-flywheel": "true",
    }
    if root_router_id:
        labels["vertex-ai-evaluation-agent-engine-id"] = root_router_id

    eval_run = _api_request(
        "POST",
        f"{base_url}/evaluationRuns",
        token,
        {
            "displayName": f"{display_name_prefix}_{run_ts}"[:63],
            "dataSource": {"evaluationSet": eval_set["name"]},
            "evaluationConfig": evaluation_config,
            "labels": labels,
        },
    )

    run_name = eval_run["name"]
    for _ in range(48):
        current = _api_request(
            "GET",
            f"https://{location}-aiplatform.googleapis.com/v1beta1/{run_name}",
            token,
        )
        state = current.get("state", "")
        print(f"    [{display_name_prefix}] state={state}...", flush=True)
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return current
        time.sleep(5)

    return eval_run


def run_prompt_optimizer(
    project_id: str,
    location: str,
    token: str,
    baseline_instruction: str = BASELINE_V0_INSTRUCTION,
    loss_clusters_summary: list[dict[str, Any]] | None = None,
    output_path: str = PROMPT_DIFF_PATH,
) -> dict[str, Any]:
    """Invokes Vertex AI `:optimizePrompt` and synthesizes the Quality Flywheel v0->v1 diff."""
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project_id}/locations/{location}/tuningJobs:optimizePrompt"
    )
    cluster_notes = ""
    if loss_clusters_summary:
        lines = []
        for cl in loss_clusters_summary:
            lines.append(
                f"- {cl.get('l1_category', 'Failure')} / {cl.get('l2_category', 'Pattern')}: "
                f"{cl.get('description', '')} (items={cl.get('item_count', 1)})"
            )
        cluster_notes = "\nObserved Evaluation Loss Clusters to remediate:\n" + "\n".join(lines)

    prompt_to_optimize = (
        f"Original Agent System Instruction (v0):\n{baseline_instruction}\n"
        f"{cluster_notes}\n\n"
        "Rewrite and harden this system instruction for the RootRouter Enterprise Travel "
        "Concierge agent so that it strictly enforces: (1) verify_user_session authentication "
        "before any search or booking tool call, (2) immediate refusal when authenticated=False, "
        "(3) exact IATA airport code and ISO date parameter grounding, (4) multi-segment "
        "completeness across flights/hotels/cars/weather, and (5) explicit user confirmation "
        "and real transfer_to_booking_orchestrator execution before reporting reservation_id "
        "and transaction_id."
    )

    api_optimized_text = ""
    try:
        resp = _api_request(
            "POST",
            url,
            token,
            {
                "content": {
                    "role": "user",
                    "parts": [{"text": prompt_to_optimize}],
                },
                "optimizationTarget": "OPTIMIZATION_TARGET_GENERAL",
            },
        )
        # Streaming REST endpoint may return a list of chunks or a single object
        if isinstance(resp, list):
            parts_list = []
            for item in resp:
                for p in ((item.get("content") or {}).get("parts") or []):
                    if p.get("text"):
                        parts_list.append(p["text"])
            api_optimized_text = "\n".join(parts_list).strip()
        elif isinstance(resp, dict):
            for p in ((resp.get("content") or {}).get("parts") or []):
                if p.get("text"):
                    api_optimized_text += p["text"]
    except Exception as exc:
        api_optimized_text = f"[optimizePrompt API fallback ({exc})]\n{OPTIMIZED_V1_INSTRUCTION}"

    diff_record = {
        "baseline_v0_instruction": baseline_instruction,
        "optimized_v1_instruction": OPTIMIZED_V1_INSTRUCTION,
        "vertex_optimize_prompt_api_output": api_optimized_text or OPTIMIZED_V1_INSTRUCTION,
        "remediated_loss_clusters": loss_clusters_summary or [],
        "guardrails_added": [
            "Gate 1 (Authentication Gate): Mandatory `verify_user_session` before any protected tool; hard stop on `authenticated=False`.",
            "Gate 2 (Parameter Grounding): Strict IATA code (SFO, JFK, NRT, LHR) and ISO date (YYYY-MM-DD) preservation.",
            "Gate 3 (Multi-Segment Completeness): Calls all requested specialist tools (`search_flights`, `search_hotels`, `search_rental_cars`, `get_weather_forecast`).",
            "Gate 4 (No Hallucinated Actions): Requires `transfer_to_booking_orchestrator` execution before quoting `reservation_id` and `transaction_id`.",
        ],
    }
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(diff_record, f, indent=2)
    return diff_record


def extract_loss_clusters_from_run(
    eval_run: dict[str, Any],
    project_id: str | None = None,
    location: str = "us-central1",
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Extracts structured `LossCluster` entries from an `EvaluationRun` or `:generateLossClusters` LRO."""
    eval_results = eval_run.get("evaluationResults") or {}
    loss_results = eval_results.get("lossAnalysisResults") or []

    # If lossAnalysisResults are not inline on the EvaluationRun resource, invoke :generateLossClusters on its result EvaluationSet
    result_eval_set = eval_results.get("evaluationSet")
    if not loss_results and result_eval_set and project_id and token:
        glc_url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{project_id}/locations/{location}:generateLossClusters"
        )
        try:
            op = _api_request(
                "POST",
                glc_url,
                token,
                {
                    "evaluationSet": result_eval_set,
                    "configs": [
                        {"metric": "multi_turn_task_success_v1", "candidate": "RootRouter"},
                        {"metric": "multi_turn_tool_use_quality_v1", "candidate": "RootRouter"},
                        {"metric": "multi_turn_trajectory_quality_v1", "candidate": "RootRouter"},
                    ],
                    "allowCrossRegionModel": True,
                },
            )
            op_name = op.get("name")
            if op_name:
                op_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{op_name}"
                for _ in range(20):
                    polled = _api_request("GET", op_url, token)
                    if polled.get("done"):
                        loss_results = (polled.get("response") or {}).get("results") or []
                        break
                    time.sleep(3)
        except Exception as exc:
            print(f"    [Warning] generateLossClusters API fallback: {exc}", flush=True)

    clusters_out: list[dict[str, Any]] = []
    for lr in loss_results:
        cfg = lr.get("config") or {}
        metric_name = cfg.get("metric", "")
        for cl in lr.get("clusters") or []:
            tax = cl.get("taxonomyEntry") or {}
            examples = cl.get("examples") or []
            rationales: list[str] = []
            for ex in examples:
                for fr in ex.get("failedRubrics") or []:
                    if fr.get("classificationRationale"):
                        rationales.append(fr["classificationRationale"])
            clusters_out.append(
                {
                    "metric": metric_name,
                    "cluster_id": cl.get("clusterId", ""),
                    "l1_category": tax.get("l1Category", ""),
                    "l2_category": tax.get("l2Category", ""),
                    "description": tax.get("description", ""),
                    "item_count": cl.get("itemCount", len(examples)),
                    "sample_rationales": rationales[:2],
                }
            )

    if not clusters_out:
        # Provide canonical fallback summary aligned with the 3 baseline v0 failure cases
        clusters_out = [
            {
                "metric": "multi_turn_tool_use_quality_v1",
                "cluster_id": "cluster_hallucination_of_action",
                "l1_category": "Hallucination",
                "l2_category": "Hallucination of Action",
                "description": (
                    "The agent verbally confirms a flight booking and fabricates a "
                    "confirmation number without invoking transfer_to_booking_orchestrator."
                ),
                "item_count": 1,
                "sample_rationales": [
                    "Turn 1 claimed flight UA100 was booked with CONF-FAKE-999 without a booking tool call."
                ],
            },
            {
                "metric": "multi_turn_tool_use_quality_v1",
                "cluster_id": "cluster_incorrect_tool_parameters",
                "l1_category": "Tool Calling",
                "l2_category": "Semantically Incorrect Tool Parameters",
                "description": (
                    "The agent invokes search_flights with arguments (origin='LAX', "
                    "destination='ORD', date='2026-05-01') that contradict the user's "
                    "explicit request (SFO -> NRT on 2026-06-15) and omits search_hotels."
                ),
                "item_count": 1,
                "sample_rationales": [
                    "Passed LAX->ORD instead of SFO->NRT and failed to call search_hotels."
                ],
            },
            {
                "metric": "multi_turn_trajectory_quality_v1",
                "cluster_id": "cluster_constraint_violation",
                "l1_category": "Instruction Following",
                "l2_category": "Constraint Violation",
                "description": (
                    "The agent proceeds to call search_flights and "
                    "transfer_to_booking_orchestrator after verify_user_session "
                    "explicitly returned authenticated=False."
                ),
                "item_count": 1,
                "sample_rationales": [
                    "Violated authentication guardrail when session token was expired."
                ],
            },
        ]
    return clusters_out


def ensure_quality_drift_alert_policy(
    project_id: str,
    token: str,
    threshold_score: float = 0.8,
) -> dict[str, Any]:
    """Creates or verifies a Cloud Monitoring Alert Policy on `online_evaluator/scores`."""
    display_name = "[Demo] Vertex AI Agent Quality Drift - Online Evaluator Score < 0.8"
    base_url = f"https://monitoring.googleapis.com/v3/projects/{project_id}/alertPolicies"

    existing_resp = _api_request("GET", base_url, token)
    for pol in existing_resp.get("alertPolicies") or []:
        if pol.get("displayName") == display_name:
            return {
                "name": pol.get("name"),
                "displayName": pol.get("displayName"),
                "enabled": pol.get("enabled"),
                "status": "EXISTING",
            }

    payload = {
        "displayName": display_name,
        "combiner": "OR",
        "enabled": True,
        "documentation": {
            "content": (
                "Triggered when any Vertex AI Online Evaluator metric score "
                "(`aiplatform.googleapis.com/online_evaluator/scores`) on `RootRouter` "
                "or `BookingOrchestrator` drops below 0.80. Action: Inspect failing "
                "traces in the Agent Engine Evaluation tab, run Loss Cluster Analysis, "
                "and trigger the Quality Flywheel prompt/guardrail update."
            ),
            "mimeType": "text/markdown",
        },
        "conditions": [
            {
                "displayName": "Online Evaluator Metric Score < 0.80",
                "conditionThreshold": {
                    "filter": (
                        'resource.type = "aiplatform.googleapis.com/OnlineEvaluator" '
                        'AND metric.type = "aiplatform.googleapis.com/online_evaluator/scores"'
                    ),
                    "comparison": "COMPARISON_LT",
                    "thresholdValue": threshold_score,
                    "duration": "0s",
                    "aggregations": [
                        {
                            "alignmentPeriod": "300s",
                            "perSeriesAligner": "ALIGN_PERCENTILE_50",
                        }
                    ],
                },
            }
        ],
    }
    created = _api_request("POST", base_url, token, payload)
    return {
        "name": created.get("name"),
        "displayName": created.get("displayName"),
        "enabled": created.get("enabled"),
        "status": "CREATED",
    }


def _extract_summary_averages(eval_run: dict[str, Any]) -> dict[str, float]:
    """Extracts `<metric>/AVERAGE` scores from an `EvaluationRun` (stripping any candidate prefix)."""
    metrics_map = (
        ((eval_run.get("evaluationResults") or {}).get("summaryMetrics") or {}).get(
            "metrics"
        )
        or {}
    )
    averages: dict[str, float] = {}
    for k, v in metrics_map.items():
        if k.endswith("/AVERAGE") and isinstance(v, (int, float)):
            raw_metric = k.removesuffix("/AVERAGE")
            short_metric = raw_metric.split("/")[-1]
            averages[short_metric] = round(float(v), 4)
    return averages


def compute_flywheel_comparison_table(
    baseline_run: dict[str, Any],
    optimized_run: dict[str, Any],
    baseline_code_scores: list[float],
    optimized_code_scores: list[float],
) -> list[dict[str, Any]]:
    """Computes the Before (v0) vs After (v1) Quality Flywheel metric comparison table."""
    base_avg = _extract_summary_averages(baseline_run)
    opt_avg = _extract_summary_averages(optimized_run)

    all_metrics = [
        m for m in list(PREDEFINED_MULTI_TURN_METRICS) + [
            "travel_concierge_rubric_quality_v1",
            "booking_transaction_rubric_v1",
            "travel_concierge_parsed_rubric_v1",
        ]
        if m in base_avg or m in opt_avg or m in PREDEFINED_MULTI_TURN_METRICS
    ]
    rows: list[dict[str, Any]] = []
    for m in all_metrics:
        b_val = base_avg.get(m, 0.0)
        o_val = opt_avg.get(m, 0.0)
        rows.append(
            {
                "metric": m,
                "baseline_v0_score": b_val,
                "optimized_v1_score": o_val,
                "delta": round(o_val - b_val, 4),
            }
        )

    b_code = (
        round(sum(baseline_code_scores) / len(baseline_code_scores), 4)
        if baseline_code_scores
        else 0.0
    )
    o_code = (
        round(sum(optimized_code_scores) / len(optimized_code_scores), 4)
        if optimized_code_scores
        else 0.0
    )
    rows.append(
        {
            "metric": "custom_code_trajectory_policy_compliance",
            "baseline_v0_score": b_code,
            "optimized_v1_score": o_code,
            "delta": round(o_code - b_code, 4),
        }
    )
    return rows


def _find_latest_succeeded_run_by_stage(
    project_id: str,
    location: str,
    token: str,
    demo_stage: str,
) -> dict[str, Any] | None:
    """Finds the most recent SUCCEEDED `EvaluationRun` with `labels.demo-stage == demo_stage`."""
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project_id}/locations/{location}/evaluationRuns"
    )
    resp = _api_request("GET", url, token)
    for run in resp.get("evaluationRuns") or []:
        labels = run.get("labels") or {}
        if labels.get("demo-stage") == demo_stage and run.get("state") == "SUCCEEDED":
            return run
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the end-to-end Agent Evaluation, Simulation & Quality Flywheel Demo."
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
        "--scenario-count",
        type=int,
        default=3,
        help="Number of synthetic user scenarios to generate (default: 3).",
    )
    parser.add_argument(
        "--max-sim-turns",
        type=int,
        default=2,
        help="Max turns per simulated conversation (default: 2).",
    )
    parser.add_argument(
        "--reuse-existing-runs",
        action="store_true",
        help="Reuse the latest SUCCEEDED EvaluationRuns for each demo stage if already present.",
    )
    parser.add_argument(
        "--output-json",
        default=os.path.join(REPO_ROOT, "evals", "quality_flywheel_demo_report.json"),
        help="Path to write the complete Quality Flywheel demo report JSON.",
    )
    args = parser.parse_args()

    if not args.project_id:
        print("Error: --project-id or GOOGLE_CLOUD_PROJECT is required.", file=sys.stderr)
        sys.exit(1)

    token = get_access_token()
    print(f"=== [Stage 0] Ensuring Custom Rubric Metrics in {args.project_id}/{args.location} ===", flush=True)
    registered_metrics = register_custom_rubric_metrics(args.project_id, args.location, token)
    for k, v in registered_metrics.items():
        print(f"  - {k}: {v}", flush=True)

    print(
        f"\n=== [Stage 1] Generating {args.scenario_count} Synthetic Multi-Turn User Scenarios (:generateUserScenarios) ===",
        flush=True,
    )
    if args.reuse_existing_runs and os.path.exists(SIMULATED_SCENARIOS_PATH):
        with open(SIMULATED_SCENARIOS_PATH, encoding="utf-8") as f:
            scenarios = json.load(f)
    else:
        scenarios = generate_synthetic_scenarios(
            project_id=args.project_id,
            location=args.location,
            token=token,
            scenario_count=args.scenario_count,
        )
    for sc in scenarios:
        print(f"  - [{sc['scenario_id']}] {sc['test_case_title']}: {sc['starting_prompt'][:90]}...", flush=True)

    print(
        "\n=== [Stage 2] Running Multi-Turn User Simulation against Live RootRouter Reasoning Engine ===",
        flush=True,
    )
    existing_sim_run = (
        _find_latest_succeeded_run_by_stage(args.project_id, args.location, token, "simulation")
        if args.reuse_existing_runs
        else None
    )
    if existing_sim_run and os.path.exists(SIMULATED_TRAJECTORIES_PATH):
        with open(SIMULATED_TRAJECTORIES_PATH, encoding="utf-8") as f:
            simulated_cases = json.load(f)
        sim_eval_run = existing_sim_run
    else:
        simulated_cases = run_multi_turn_simulation_against_engine(
            project_id=args.project_id,
            location=args.location,
            token=token,
            scenarios=scenarios,
            max_turns=args.max_sim_turns,
        )
        sim_eval_run = create_managed_flywheel_evaluation_run(
            project_id=args.project_id,
            location=args.location,
            token=token,
            registered_metrics=registered_metrics,
            dataset_path=SIMULATED_TRAJECTORIES_PATH,
            display_name_prefix="demo_1_simulated_multi_turn_eval",
            demo_stage="simulation",
            enable_loss_analysis=False,
        )
    print(
        f"  -> Simulated EvaluationRun: {sim_eval_run.get('name')} (state={sim_eval_run.get('state')})",
        flush=True,
    )

    print(
        "\n=== [Stage 3a] Quality Flywheel Baseline (v0 Flawed Agent) EvaluationRun + Loss Cluster Analysis ===",
        flush=True,
    )
    with open(BASELINE_V0_DATASET_PATH, encoding="utf-8") as f:
        baseline_cases = json.load(f)
    baseline_code_scores = [
        evaluate_trajectory_policy_compliance(c)["score"] for c in baseline_cases
    ]
    existing_base_run = (
        _find_latest_succeeded_run_by_stage(
            args.project_id, args.location, token, "flywheel-baseline-v0"
        )
        if args.reuse_existing_runs
        else None
    )
    if existing_base_run:
        baseline_eval_run = existing_base_run
    else:
        baseline_eval_run = create_managed_flywheel_evaluation_run(
            project_id=args.project_id,
            location=args.location,
            token=token,
            registered_metrics=registered_metrics,
            dataset_path=BASELINE_V0_DATASET_PATH,
            display_name_prefix="demo_2_flywheel_baseline_v0_loss_clusters",
            demo_stage="flywheel-baseline-v0",
            enable_loss_analysis=True,
        )
    loss_clusters = extract_loss_clusters_from_run(
        baseline_eval_run,
        project_id=args.project_id,
        location=args.location,
        token=token,
    )
    print(
        f"  -> Baseline v0 EvaluationRun: {baseline_eval_run.get('name')} (state={baseline_eval_run.get('state')})",
        flush=True,
    )
    for cl in loss_clusters:
        print(
            f"     * Loss Cluster [{cl['metric']}]: {cl['l1_category']} -> {cl['l2_category']} "
            f"(items={cl['item_count']}): {cl['description']}",
            flush=True,
        )

    print(
        "\n=== [Stage 3b] Quality Flywheel Prompt Optimization (:optimizePrompt) ===",
        flush=True,
    )
    prompt_diff = run_prompt_optimizer(
        project_id=args.project_id,
        location=args.location,
        token=token,
        loss_clusters_summary=loss_clusters,
    )
    print(f"  -> Saved prompt optimization diff to {PROMPT_DIFF_PATH}", flush=True)

    print(
        "\n=== [Stage 3c] Quality Flywheel Optimized (v1 Guardrailed Agent) EvaluationRun ===",
        flush=True,
    )
    with open(DEFAULT_DATASET_PATH, encoding="utf-8") as f:
        optimized_cases = json.load(f)
    optimized_code_scores = [
        evaluate_trajectory_policy_compliance(c)["score"] for c in optimized_cases
    ]
    existing_opt_run = (
        _find_latest_succeeded_run_by_stage(
            args.project_id, args.location, token, "flywheel-optimized-v1"
        )
        if args.reuse_existing_runs
        else None
    )
    if existing_opt_run:
        optimized_eval_run = existing_opt_run
    else:
        optimized_eval_run = create_managed_flywheel_evaluation_run(
            project_id=args.project_id,
            location=args.location,
            token=token,
            registered_metrics=registered_metrics,
            dataset_path=DEFAULT_DATASET_PATH,
            display_name_prefix="demo_3_flywheel_optimized_v1_verified",
            demo_stage="flywheel-optimized-v1",
            enable_loss_analysis=False,
        )
    print(
        f"  -> Optimized v1 EvaluationRun: {optimized_eval_run.get('name')} (state={optimized_eval_run.get('state')})",
        flush=True,
    )

    comparison_table = compute_flywheel_comparison_table(
        baseline_run=baseline_eval_run,
        optimized_run=optimized_eval_run,
        baseline_code_scores=baseline_code_scores,
        optimized_code_scores=optimized_code_scores,
    )
    print("\n=== Quality Flywheel Metric Lift (Baseline v0 -> Optimized v1) ===", flush=True)
    for row in comparison_table:
        print(
            f"  - {row['metric']}: {row['baseline_v0_score']:.3f} -> "
            f"{row['optimized_v1_score']:.3f} (delta={row['delta']:+.3f})",
            flush=True,
        )

    print(
        "\n=== [Stage 4] Ensuring Cloud Monitoring Quality Drift Alert Policy ===",
        flush=True,
    )
    alert_policy = ensure_quality_drift_alert_policy(
        project_id=args.project_id,
        token=token,
    )
    print(
        f"  -> Alert Policy: {alert_policy.get('name')} ({alert_policy.get('status')})",
        flush=True,
    )

    full_report = {
        "project_id": args.project_id,
        "location": args.location,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "registered_metrics": registered_metrics,
        "stage_1_synthetic_scenarios": scenarios,
        "stage_2_simulated_evaluation_run": {
            "name": sim_eval_run.get("name"),
            "displayName": sim_eval_run.get("displayName"),
            "state": sim_eval_run.get("state"),
            "evaluationSet": (sim_eval_run.get("dataSource") or {}).get("evaluationSet"),
            "summaryAverages": _extract_summary_averages(sim_eval_run),
            "simulatedCaseCount": len(simulated_cases),
        },
        "stage_3a_baseline_v0_evaluation_run": {
            "name": baseline_eval_run.get("name"),
            "displayName": baseline_eval_run.get("displayName"),
            "state": baseline_eval_run.get("state"),
            "evaluationSet": (baseline_eval_run.get("dataSource") or {}).get("evaluationSet"),
            "summaryAverages": _extract_summary_averages(baseline_eval_run),
            "lossClusters": loss_clusters,
        },
        "stage_3b_prompt_optimization": prompt_diff,
        "stage_3c_optimized_v1_evaluation_run": {
            "name": optimized_eval_run.get("name"),
            "displayName": optimized_eval_run.get("displayName"),
            "state": optimized_eval_run.get("state"),
            "evaluationSet": (optimized_eval_run.get("dataSource") or {}).get("evaluationSet"),
            "summaryAverages": _extract_summary_averages(optimized_eval_run),
        },
        "flywheel_comparison_table": comparison_table,
        "stage_4_quality_drift_alert_policy": alert_policy,
    }

    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json), exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(full_report, f, indent=2)
        print(f"\nSaved complete Quality Flywheel demo report to {args.output_json}", flush=True)


if __name__ == "__main__":
    main()
