import json
import logging
import os
import random
import re
import uuid

import google.auth
import google.auth.transport.requests
import requests
from flask import Request
from google.cloud import aiplatform
from vertexai.preview.reasoning_engines import ReasoningEngine


def is_otel_initialized() -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        return isinstance(trace.get_tracer_provider(), TracerProvider)
    except Exception:
        return False


def setup_telemetry():
    if is_otel_initialized():
        return
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()
        processor = BatchSpanProcessor(OTLPSpanExporter())
        provider.add_span_processor(processor)
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

AIRPORTS = ["SFO", "JFK", "LAX", "LHR", "HND"]
HOTEL_PREFERENCES = ["luxury", "budget", "family-friendly", "boutique", "standard"]
CAR_TYPES = ["SUV", "sedan", "compact", "convertible", "luxury car"]


def generate_traffic(request: Request):
    """Cloud Function entry point triggered by Cloud Scheduler."""

    with tracer.start_as_current_span("traffic_generator.trigger_waterfall") as span:
        user_id = f"user_{random.randint(1000, 9999)}"
        member_id = "M-12345"

        # 50/50 Chance between Explorer and Decided
        scenario = "explorer" if random.random() < 0.5 else "decided"
        logger.info(f"Initiating {scenario} flow for {user_id}")
        span.set_attribute("gen_ai.scenario", scenario)

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
            # Get Google auth token for Calling Vertex AI Reasoning Engine
            try:
                credentials, project = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                auth_request = google.auth.transport.requests.Request()
                credentials.refresh(auth_request)
                auth_headers = {"Authorization": f"Bearer {credentials.token}"}
                logger.info("Successfully acquired Google auth token")
            except Exception as auth_e:
                logger.error(f"Failed to acquire auth token: {auth_e}")
                auth_headers = {}

            responses = []

            # Extract engine_id from URL to create session via SDK
            match = re.search(r"/reasoningEngines/([^:]+)", ae1_url)
            if match:
                engine_id = match.group(1)
                logger.info(f"Extracted engine_id: {engine_id}")

                try:
                    aiplatform.init(project=project, location="us-central1")
                    engine = ReasoningEngine(engine_id)
                    logger.info(f"Creating session for user {user_id}...")
                    session = engine.create_session(user_id=user_id)
                    session_id = session.get("id")
                    logger.info(f"Successfully created session: {session_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to create session via SDK: {e}. Falling back to random UUID."
                    )
                    session_id = str(uuid.uuid4())
            else:
                logger.warning(
                    f"Could not extract engine_id from URL: {ae1_url}. Falling back to random UUID."
                )
                session_id = str(uuid.uuid4())

            # --- Setup Scenario Prompts Chain ---
            prompts_chain = []
            destination = None

            if scenario == "explorer":
                category = random.choice(EXPLORER_CATEGORIES)
                destination = random.choice(DESTINATIONS[category])
                airport = random.choice(AIRPORTS)

                prompts_chain = [
                    f"I don't know where to go. Suggest some {category}.",
                    f"My member ID is {member_id}",  # satisfies Auth Gate
                    f"Let's go with {destination}!",
                    f"Show me nice {random.choice(HOTEL_PREFERENCES)} hotels near downtown there.",
                    f"Look up roundtrip flights from {airport}.",
                    f"I will also need a {random.choice(CAR_TYPES)}.",
                    f"What sightseeing placed do you recommend in {destination}?",
                ]
            else:  # decided
                destination = random.choice(DECIDED_DESTINATIONS)
                airport = random.choice(AIRPORTS)

                prompts_chain = [
                    f"I want to book a trip to {destination}.",
                    f"My member ID is {member_id}",  # satisfies Auth Gate
                    f"Find roundtrip flights from {airport}.",
                    f"Show me {random.choice(HOTEL_PREFERENCES)} hotels that have a pool.",
                    f"Add a {random.choice(CAR_TYPES)} to my booking details.",
                ]

            logger.info(f"Starting prompts chain with {len(prompts_chain)} turns.")

            for i, prompt_text in enumerate(prompts_chain):
                logger.info(f"Sending Turn {i + 1}: {prompt_text}")
                span.set_attribute(f"gen_ai.prompt.{i + 1}", prompt_text)

                payload = {"input": {"message": prompt_text, "user_id": user_id}}
                if session_id:
                    payload["input"]["session_id"] = session_id

                res = requests.post(
                    ae1_url,
                    json=payload,
                    headers=auth_headers,
                    timeout=300.0,
                    stream=True,
                )

                res.raise_for_status()

                full_response = ""
                for line in res.iter_lines():
                    if line:
                        decoded_line = line.decode("utf-8")
                        full_response += decoded_line

                responses.append(
                    {
                        "status": "stream_completed",
                        "full_response_length": len(full_response),
                    }
                )

            logger.info("Multi-turn stateful flow completed successfully.")
            return (
                json.dumps(
                    {"status": "success", "scenario": scenario, "responses": responses}
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
