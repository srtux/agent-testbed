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
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        
        provider = TracerProvider()
        processor = BatchSpanProcessor(CloudTraceSpanExporter())
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

PROMPTS = [
    "My flight to Tokyo was canceled. Read my customer profile to find my preferences, check the weather in Tokyo, find a new flight, book a hotel that matches my profile, and secure a rental car. Summarize everything.",
    "I need an emergency re-booking for London due to weather. Please check my CR profile, find a flight and hotel, make sure I have a rental car, and let me know the final confirmation.",
    "My trip to Paris is in jeopardy because of a missed connection. Grab my preferences, verify Paris weather, book a new flight and adjust my hotel and car rental accordingly."
]

def generate_traffic(request: Request):
    """Cloud Function entry point triggered by Cloud Scheduler."""
    
    # We create a root active span here from which the entire A2A and MCP waterfall descends.
    with tracer.start_as_current_span("traffic_generator.trigger_waterfall") as span:
        prompt = random.choice(PROMPTS)
        user_id = f"user_{random.randint(1000, 9999)}"
        
        logger.info(f"Initiating travel concierge trace waterfall for {user_id}")
        span.set_attribute("gen_ai.prompt", prompt)
        
        ae1_url = os.environ.get("ROOT_ROUTER_URL", "http://ae1-root-router/chat")
        
        payload = {"user_id": user_id, "prompt": prompt}
        
        try:
            # The RequestsInstrumentor ensures traceparent is sent to RootRouter
            res = requests.post(ae1_url, json=payload, timeout=300.0)
            res.raise_for_status()
            
            logger.info("Trace execution completed successfully.")
            return json.dumps({"status": "success", "response": res.json()}), 200, {'Content-Type': 'application/json'}
            
        except Exception as e:
            logger.error(f"Trace execution failed: {e}")
            span.record_exception(e)
            return json.dumps({"status": "error", "message": str(e)}), 500, {'Content-Type': 'application/json'}
