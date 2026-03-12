import os
import random
import requests
import json
import logging
from flask import Request

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
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

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

PLANNING_PROMPTS = [
    "I want to go on a vacation to Tokyo.",
    "I need to book travel to London.",
    "I am planning a trip to Paris."
]
INSPIRATION_PROMPTS = [
    "I want a vacation but I'm not sure where to go.",
    "I'm looking for a tropical getaway, any suggestions?",
    "What are trending destinations for a spring trip?"
]

def generate_traffic(request: Request):
    """Cloud Function entry point triggered by Cloud Scheduler."""
    
    with tracer.start_as_current_span("traffic_generator.trigger_waterfall") as span:
        prompt = random.choice(PLANNING_PROMPTS if random.random() < 0.5 else INSPIRATION_PROMPTS)
        user_id = f"user_{random.randint(1000, 9999)}"
        member_id = "M-12345"
        
        logger.info(f"Initiating 2-step flow for {user_id}")
        span.set_attribute("gen_ai.prompt.initial", prompt)
        
        ae1_url = os.environ.get("ROOT_ROUTER_URL")
        if not ae1_url:
            logger.error("ROOT_ROUTER_URL environment variable is not set.")
            return json.dumps({"status": "error", "message": "ROOT_ROUTER_URL not configured"}), 500, {'Content-Type': 'application/json'}

        # --- Step 1: Initial Intent ---
        payload_1 = {"user_id": user_id, "prompt": prompt}
        try:
            logger.info("Sending Turn 1: Initial Intent")
            res_1 = requests.post(ae1_url, json=payload_1, timeout=300.0)
            res_1.raise_for_status()
            res_1_data = res_1.json()
            
            session_id = res_1_data.get("session_id")
            logger.info(f"Turn 1 response received. session_id={session_id}")

            # --- Step 2: Provide Member ID (Auth Gate) ---
            if session_id:
                 payload_2 = {
                     "user_id": user_id, 
                     "prompt": f"My member ID is {member_id}", 
                     "session_id": session_id
                 }
                 logger.info("Sending Turn 2: Providing Member ID")
                 res_2 = requests.post(ae1_url, json=payload_2, timeout=300.0)
                 res_2.raise_for_status()
                 logger.info("2-step flow completed successfully.")
                 return json.dumps({"status": "success", "response": res_2.json()}), 200, {'Content-Type': 'application/json'}
            else:
                 logger.warning("Turn 1 did not return session_id, skipping turn 2")
                 return json.dumps({"status": "partial_success", "response": res_1_data}), 200, {'Content-Type': 'application/json'}

        except Exception as e:
            logger.error(f"Trace execution failed: {e}")
            span.record_exception(e)
            return json.dumps({"status": "error", "message": str(e)}), 500, {'Content-Type': 'application/json'}
