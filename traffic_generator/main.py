import datetime
import json
import logging
import os
import random
import re
import uuid

from typing import Any

import google.auth
import google.auth.transport.requests
import requests
from google.cloud import aiplatform
from vertexai.preview.reasoning_engines import ReasoningEngine

try:
    from flask import Request
except ImportError:
    Request = Any


def _is_otel_initialized() -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        return isinstance(trace.get_tracer_provider(), TracerProvider)
    except Exception:
        return False


def _create_authenticated_exporter():
    """Create an OTLPSpanExporter with Google ADC credentials when targeting
    telemetry.googleapis.com. See AGENTS.md for rationale.
    """
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if "telemetry.googleapis.com" not in endpoint:
        return OTLPSpanExporter()

    try:
        import google.auth.transport.grpc
        import google.auth.transport.requests
        import grpc

        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        auth_metadata_plugin = google.auth.transport.grpc.AuthMetadataPlugin(
            credentials=credentials, request=auth_req
        )
        channel_creds = grpc.composite_channel_credentials(
            grpc.ssl_channel_credentials(),
            grpc.metadata_call_credentials(auth_metadata_plugin),
        )
        return OTLPSpanExporter(
            endpoint="telemetry.googleapis.com:443",
            credentials=channel_creds,
        )
    except Exception as e:
        print(f"Warning: failed to build authenticated OTLP exporter: {e}")
        return OTLPSpanExporter()


def setup_telemetry():
    if _is_otel_initialized():
        return
    if os.environ.get("DISABLE_TELEMETRY", "false").lower() == "true":
        return
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        project_id = os.environ.get(
            "GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID", "")
        )
        if not project_id:
            try:
                _, detected_project = google.auth.default()
                project_id = detected_project or ""
            except Exception:
                project_id = ""

        resource = Resource(
            attributes={
                "service.name": os.environ.get("OTEL_SERVICE_NAME", "traffic-generator"),
                "gcp.project_id": project_id,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(_create_authenticated_exporter()))
        trace.set_tracer_provider(provider)

        # Critical: Instrument requests so our call to RootRouter includes traceparent
        RequestsInstrumentor().instrument()
    except ImportError as e:
        print(f"Warning: Telemetry dependencies not fully installed: {e}")


setup_telemetry()
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# Basic logging config
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EXPLORER_CATEGORIES = [
    "beach destinations",
    "historical cities",
    "nature and hiking places",
]

DESTINATIONS = {
    "beach destinations": ["Bali", "Maldives", "Hawaii", "Cancun"],
    "historical cities": ["Rome", "Athens", "Cairo", "Kyoto"],
    "nature and hiking places": ["Swiss Alps", "Patagonia", "Banff", "Yosemite"],
}

DECIDED_DESTINATIONS = [
    "Tokyo",
    "London",
    "Paris",
    "New York",
    "Sydney",
    "Rio de Janeiro",
    "Cape Town",
]

ALL_KNOWN_DESTINATIONS = sorted(
    set(DECIDED_DESTINATIONS + [d for dsts in DESTINATIONS.values() for d in dsts])
)

AIRPORTS = ["SFO", "JFK", "LAX", "LHR", "HND"]
HOTEL_PREFERENCES = ["luxury", "budget", "family-friendly", "boutique", "standard"]
CAR_TYPES = ["SUV", "sedan", "compact", "convertible", "luxury car"]
MEMBER_IDS = ["M-12345", "M-67890", "M-54321", "M-98765"]


def _build_persona(scenario: str, user_id: str) -> dict:
    """Create a randomized traveler persona for dynamic multi-turn simulation."""
    category = random.choice(EXPLORER_CATEGORIES)
    fallback_destination = (
        random.choice(DESTINATIONS[category])
        if scenario == "explorer"
        else random.choice(DECIDED_DESTINATIONS)
    )
    start_offset = random.randint(21, 90)
    trip_days = random.randint(4, 7)
    start_date = datetime.date(2026, 5, 1) + datetime.timedelta(days=start_offset)
    end_date = start_date + datetime.timedelta(days=trip_days)
    return {
        "user_id": user_id,
        "member_id": random.choice(MEMBER_IDS),
        "scenario": scenario,
        "category": category,
        "fallback_destination": fallback_destination,
        "airport": random.choice(AIRPORTS),
        "dates": f"{start_date.isoformat()} to {end_date.isoformat()}",
        "trip_days": trip_days,
        "hotel_preference": random.choice(HOTEL_PREFERENCES),
        "car_type": random.choice(CAR_TYPES),
    }


def _extract_agent_reply(raw_response: str) -> str:
    """Extract clean assistant text from Vertex AI Reasoning Engine SSE or JSON responses."""
    if not raw_response:
        return ""

    extracted_chunks: list[str] = []
    for raw_line in raw_response.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[len("data:") :].strip()
        if not line or line == "[DONE]":
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        if isinstance(obj, dict):
            # Standard ADK / Vertex AI stream_query event structure
            parts = obj.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_val = part["text"].strip()
                    if text_val:
                        extracted_chunks.append(text_val)
            # Local FastAPI /chat structure: {"response": "..."} or {"output": "..."}
            for key in ("response", "output", "text"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    extracted_chunks.append(val.strip())

    if extracted_chunks:
        return "\n".join(extracted_chunks)
    return raw_response.strip()


def _is_booking_complete(agent_reply: str, turn_idx: int) -> bool:
    """Detect whether the agent has already finalized the booking and payment."""
    if turn_idx < 3 or not agent_reply:
        return False
    lower = agent_reply.lower()
    completion_signals = [
        "booking is confirmed",
        "reservation is confirmed",
        "itinerary is confirmed",
        "payment has been processed",
        "payment confirmed",
        "successfully booked",
        "confirmation number",
        "loyalty discount",
    ]
    return any(sig in lower for sig in completion_signals)


def _fallback_next_user_prompt(persona: dict, history: list[dict], turn_idx: int) -> str:
    """Context-aware heuristic fallback if LLM user simulation is unavailable."""
    if not history:
        if persona["scenario"] == "explorer":
            return (
                f"Hi! I'm planning a vacation and haven't picked a destination yet. "
                f"Can you suggest some great {persona['category']}?"
            )
        return (
            f"Hi! I'd like to plan a trip to {persona['fallback_destination']} "
            f"for {persona['dates']} flying out of {persona['airport']}."
        )

    last_agent_msg = (history[-1].get("agent") or "").strip()
    last_agent_lower = last_agent_msg.lower()
    all_user_text = " ".join(h.get("user", "") for h in history)
    all_user_lower = all_user_text.lower()

    # 1. If the agent asks for member_id / user_id / authentication and we haven't provided it yet
    if persona["member_id"].lower() not in all_user_lower and any(
        kw in last_agent_lower
        for kw in ("member id", "member_id", "membership", "authenticate", "user id", "user_id")
    ):
        if persona["scenario"] == "explorer":
            return (
                f"Sure, my member ID is {persona['member_id']} (user ID {persona['user_id']}). "
                f"Could you recommend some {persona['category']}?"
            )
        return (
            f"My member ID is {persona['member_id']} (user ID {persona['user_id']}). I want to plan a trip to "
            f"{persona['fallback_destination']} for {persona['dates']} departing from {persona['airport']}."
        )

    # 2. Detect if the agent suggested any known destinations in its response
    mentioned_destinations = [
        d for d in ALL_KNOWN_DESTINATIONS if d.lower() in last_agent_lower
    ]
    chosen_dest = (
        mentioned_destinations[0]
        if mentioned_destinations
        else persona["fallback_destination"]
    )

    # 3. If destination/dates/flights/hotels/cars haven't been requested yet
    if "flight" not in all_user_lower or "hotel" not in all_user_lower:
        return (
            f"Let's go with {chosen_dest} for {persona['dates']}! "
            f"Please check roundtrip flights from {persona['airport']}, "
            f"a {persona['hotel_preference']} hotel, and a {persona['car_type']} rental car."
        )

    # 4. If the agent asked for clarification on dates, airport, hotel, or car
    if any(
        kw in last_agent_lower
        for kw in ("which airport", "departure", "what dates", "travel dates", "when")
    ) and persona["dates"] not in all_user_text:
        return (
            f"I'll be traveling {persona['dates']} departing from {persona['airport']}, "
            f"and I'd like a {persona['hotel_preference']} hotel and a {persona['car_type']} rental."
        )

    # 5. Otherwise, respond to the options presented and ask to finalize the booking
    return (
        f"Those flight, {persona['hotel_preference']} hotel, and {persona['car_type']} options "
        f"for {chosen_dest} ({persona['dates']}) look good! Please go ahead and book the "
        f"complete itinerary and calculate my final total with my loyalty discount."
    )


def _generate_next_user_prompt(
    persona: dict,
    history: list[dict],
    turn_idx: int,
    max_turns: int,
    project: str | None,
    location: str,
    auth_headers: dict,
) -> str:
    """Use Gemini on Vertex AI to dynamically simulate the next user turn based on the agent's response."""
    if not history:
        return _fallback_next_user_prompt(persona, history, turn_idx)

    simulator_model = os.environ.get("USER_SIMULATOR_MODEL", "gemini-2.5-flash")
    resolved_project = project or os.environ.get(
        "GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID", "")
    )
    if not resolved_project or not auth_headers.get("Authorization"):
        return _fallback_next_user_prompt(persona, history, turn_idx)

    all_user_text = " ".join(h.get("user", "") for h in history)
    member_id_given = persona["member_id"].lower() in all_user_text.lower()

    if turn_idx >= max_turns:
        stage_directive = (
            "This is the FINAL turn of the conversation. Explicitly confirm the specific "
            "flight, hotel, and rental car options the agent presented (or provide your "
            f"dates {persona['dates']}, origin airport {persona['airport']}, "
            f"{persona['hotel_preference']} hotel, and {persona['car_type']} car if not yet given) "
            "and tell the agent to finalize and book the complete itinerary now."
        )
    elif not member_id_given:
        stage_directive = (
            f"If the agent is asking for your Member ID or User ID, provide both "
            f"Member ID '{persona['member_id']}' and User ID '{persona['user_id']}', "
            "and remind them of what you want to plan."
        )
    else:
        stage_directive = (
            "Respond directly to the agent's latest message: "
            "if the agent suggested destinations or asked which destination you want, pick ONE specific "
            "destination from the agent's reply and IMMEDIATELY include your User ID "
            f"({persona['user_id']}), travel dates ({persona['dates']}), origin airport "
            f"({persona['airport']}), hotel preference ({persona['hotel_preference']}), and "
            f"rental car type ({persona['car_type']}) so the planning agent can check flights, "
            "hotels, weather, and cars right away. "
            "If the agent already listed flight/hotel/car options or asked for confirmation, "
            "select specific options from its reply and ask it to finalize and book the full itinerary now."
        )

    transcript_lines = []
    for idx, turn in enumerate(history, start=1):
        transcript_lines.append(f"Turn {idx} Traveler: {turn['user']}")
        transcript_lines.append(f"Turn {idx} Concierge Agent: {turn['agent']}")
    transcript_text = "\n\n".join(transcript_lines)

    system_prompt = (
        "You are roleplaying as a human traveler chatting with an AI travel concierge.\n"
        "Output ONLY the traveler's next message (1 to 3 natural sentences, plain text, no quotes or role labels).\n"
        f"Traveler Persona:\n"
        f"- User ID: {persona['user_id']}\n"
        f"- Member ID: {persona['member_id']}\n"
        f"- Scenario: {persona['scenario']} (preferred category: {persona['category']}, fallback destination: {persona['fallback_destination']})\n"
        f"- Home Airport: {persona['airport']}\n"
        f"- Travel Dates: {persona['dates']} ({persona['trip_days']} days)\n"
        f"- Hotel Preference: {persona['hotel_preference']}\n"
        f"- Car Rental Preference: {persona['car_type']}\n"
        f"\nCurrent Turn Goal ({turn_idx}/{max_turns}): {stage_directive}"
    )

    user_prompt = (
        f"Conversation so far:\n{transcript_text}\n\n"
        "Write the traveler's next reply responding directly to the Concierge Agent's last message:"
    )

    with tracer.start_as_current_span("traffic_generator.simulate_user_turn") as sim_span:
        sim_span.set_attribute("gen_ai.system", "vertex_ai")
        sim_span.set_attribute("gen_ai.request.model", simulator_model)
        sim_span.set_attribute("gen_ai.conversation.turn", turn_idx)
        try:
            url = (
                f"https://{location}-aiplatform.googleapis.com/v1/projects/{resolved_project}"
                f"/locations/{location}/publishers/google/models/{simulator_model}:generateContent"
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 512,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            }
            resp = requests.post(url, json=payload, headers=auth_headers, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text = " ".join(
                    p.get("text", "").strip() for p in parts if p.get("text")
                ).strip()
                if text:
                    sim_span.set_attribute("gen_ai.Simulator.dynamic", True)
                    return text
        except Exception as e:
            logger.warning(f"LLM user simulator fallback on turn {turn_idx}: {e}")
            sim_span.set_attribute("gen_ai.Simulator.dynamic", False)

    return _fallback_next_user_prompt(persona, history, turn_idx)


def generate_traffic(request: Request):
    """Cloud Function entry point triggered by Cloud Scheduler."""

    with tracer.start_as_current_span("traffic_generator.trigger_waterfall") as span:
        user_id = f"user_{random.randint(1000, 9999)}"

        # 50/50 Chance between Explorer and Decided
        scenario = "explorer" if random.random() < 0.5 else "decided"
        persona = _build_persona(scenario=scenario, user_id=user_id)
        max_turns = int(os.environ.get("MAX_TURNS", "5"))

        logger.info(
            f"Initiating dynamic {scenario} flow for {user_id} "
            f"(member_id={persona['member_id']}, dates={persona['dates']}, max_turns={max_turns})"
        )
        span.set_attribute("gen_ai.scenario", scenario)
        span.set_attribute("gen_ai.user_id", user_id)
        span.set_attribute("gen_ai.member_id", persona["member_id"])

        ae1_url = os.environ.get("ROOT_ROUTER_URL")
        if not ae1_url:
            logger.error("ROOT_ROUTER_URL environment variable is not set.")
            return (
                json.dumps(
                    {"status": "error", "message": "ROOT_ROUTER_URL not configured"}
                ),
                500,
                {"Content-Type": "application/json"},
            )

        try:
            # Get Google auth token for Calling Vertex AI Reasoning Engine & User Simulator
            project = os.environ.get(
                "GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID")
            )
            try:
                credentials, detected_project = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                if not project:
                    project = detected_project
                auth_request = google.auth.transport.requests.Request()
                credentials.refresh(auth_request)
                auth_headers = {"Authorization": f"Bearer {credentials.token}"}
                logger.info("Successfully acquired Google auth token")
            except Exception as auth_e:
                logger.error(f"Failed to acquire auth token: {auth_e}")
                auth_headers = {}

            responses = []
            history: list[dict] = []

            # Detect if ROOT_ROUTER_URL targets a Vertex AI Reasoning Engine
            re_match = re.search(
                r"(projects/[^/]+/locations/([^/]+)/reasoningEngines/([^/:?]+))",
                ae1_url,
            )
            is_reasoning_engine = bool(re_match)
            session_id = None
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

            if is_reasoning_engine:
                resource_name = re_match.group(1)
                location = re_match.group(2)
                engine_id = re_match.group(3)
                query_url = f"https://{location}-aiplatform.googleapis.com/v1/{resource_name}:query"
                stream_url = f"https://{location}-aiplatform.googleapis.com/v1/{resource_name}:streamQuery?alt=sse"
                logger.info(
                    f"Resolved Reasoning Engine: {resource_name} (location={location})"
                )

                try:
                    sess_res = requests.post(
                        query_url,
                        json={
                            "class_method": "create_session",
                            "input": {"user_id": user_id},
                        },
                        headers=auth_headers,
                        timeout=60.0,
                    )
                    sess_res.raise_for_status()
                    sess_data = sess_res.json()
                    output_obj = sess_data.get("output", sess_data)
                    if isinstance(output_obj, dict):
                        session_id = output_obj.get("id")
                    elif isinstance(output_obj, str):
                        session_id = output_obj
                    logger.info(f"Successfully created session via REST: {session_id}")
                except Exception as rest_e:
                    logger.warning(
                        f"REST create_session failed ({rest_e}), trying SDK fallback..."
                    )
                    try:
                        aiplatform.init(project=project, location=location)
                        engine = ReasoningEngine(engine_id)
                        session = engine.create_session(user_id=user_id)
                        session_id = (
                            session.get("id")
                            if isinstance(session, dict)
                            else getattr(session, "id", str(session))
                        )
                    except Exception as sdk_e:
                        logger.error(
                            f"Failed to create session via SDK: {sdk_e}. Proceeding stateless."
                        )
            else:
                session_id = str(uuid.uuid4())

            for turn_idx in range(1, max_turns + 1):
                prompt_text = _generate_next_user_prompt(
                    persona=persona,
                    history=history,
                    turn_idx=turn_idx,
                    max_turns=max_turns,
                    project=project,
                    location=location,
                    auth_headers=auth_headers,
                )
                logger.info(f"Sending Turn {turn_idx}: {prompt_text}")
                span.set_attribute(f"gen_ai.prompt.{turn_idx}", prompt_text)

                if is_reasoning_engine:
                    payload = {
                        "class_method": "stream_query",
                        "input": {"message": prompt_text, "user_id": user_id},
                    }
                    if session_id:
                        payload["input"]["session_id"] = session_id

                    res = requests.post(
                        stream_url,
                        json=payload,
                        headers=auth_headers,
                        timeout=300.0,
                        stream=True,
                    )
                    res.raise_for_status()

                    raw_lines = []
                    for line in res.iter_lines():
                        if line:
                            raw_lines.append(line.decode("utf-8"))
                    full_response = "\n".join(raw_lines)
                else:
                    target_url = (
                        ae1_url
                        if ae1_url.endswith("/chat")
                        else ae1_url.rstrip("/") + "/chat"
                    )
                    payload = {"user_id": user_id, "prompt": prompt_text}
                    if session_id:
                        payload["session_id"] = session_id
                    res = requests.post(
                        target_url,
                        json=payload,
                        headers=auth_headers,
                        timeout=300.0,
                    )
                    res.raise_for_status()
                    full_response = res.text

                agent_reply = _extract_agent_reply(full_response)
                logger.info(
                    f"Turn {turn_idx} agent reply ({len(agent_reply)} chars): "
                    f"{agent_reply[:240]}"
                )
                span.set_attribute(
                    f"gen_ai.response.{turn_idx}", agent_reply[:1000]
                )

                history.append({"user": prompt_text, "agent": agent_reply})
                responses.append(
                    {
                        "turn": turn_idx,
                        "user_prompt": prompt_text,
                        "agent_reply_preview": agent_reply[:300],
                        "status": "stream_completed",
                        "full_response_length": len(full_response),
                    }
                )

                if _is_booking_complete(agent_reply, turn_idx):
                    logger.info(
                        f"Booking completed on turn {turn_idx}; concluding conversation."
                    )
                    break

            logger.info("Multi-turn dynamic stateful flow completed successfully.")
            return (
                json.dumps(
                    {
                        "status": "success",
                        "scenario": scenario,
                        "session_id": session_id,
                        "turns": len(responses),
                        "responses": responses,
                    }
                ),
                200,
                {"Content-Type": "application/json"},
            )

        except Exception as e:
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Trace execution failed: {e}. Body: {e.response.text}")
            else:
                logger.error(f"Trace execution failed: {e}")
            span.record_exception(e)
            return (
                json.dumps({"status": "error", "message": str(e)}),
                500,
                {"Content-Type": "application/json"},
            )
