import os
import sys

def is_otel_initialized() -> bool:
    """Checks if OpenTelemetry has already been initialized with a real provider."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        provider = trace.get_tracer_provider()
        return isinstance(provider, TracerProvider)
    except (ImportError, Exception):
        return False

def setup_telemetry(force_cloud_trace: bool = False):
    """
    Initializes OpenTelemetry for ADK Agents and FastAPI services.
    Ensures GenAI semantic conventions are enabled and instruments common libraries.
    """
    if is_otel_initialized():
        return
    
    # Force the latest GenAI semantic conventions
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        
        # Determine if we should use Cloud Trace
        # Cloud Run environments usually want Cloud Trace explicitly set up if not using the agent-based auto-instrumentation
        enable_manual_trace = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "false").lower() != "true"
        
        if force_cloud_trace or enable_manual_trace:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            provider = TracerProvider()
            processor = BatchSpanProcessor(CloudTraceSpanExporter())
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        
        # Instrument generic libraries
        GoogleGenAiSdkInstrumentor().instrument()
        
        # We wrap the underlying transport to inject OIDC tokens for service-to-service auth
        _setup_oidc_auth(RequestsInstrumentor(), HTTPXClientInstrumentor())
        
    except ImportError as e:
        print(f"Warning: Telemetry dependencies not fully installed: {e}", file=sys.stderr)

def _setup_oidc_auth(requests_inst, httpx_inst):
    """
    Hooks into Requests and HTTPX to inject OIDC tokens automatically 
    for Cloud Run/Functions targets when running in GCP.
    """
    import google.auth
    import google.auth.transport.requests
    from google.oauth2 import id_token
    
    # Cache for tokens to avoid overhead
    token_cache = {}

    def get_oidc_token(audience):
        if audience in token_cache:
            return token_cache[audience]
        try:
            auth_req = google.auth.transport.requests.Request()
            token = id_token.fetch_id_token(auth_req, audience)
            token_cache[audience] = token
            return token
        except Exception:
            return None

    # For Requests
    requests_inst.instrument()
    
    # For HTTPX (ADK uses this)
    def httpx_request_hook(span, request):
        url = str(request.url)
        if ".a.run.app" in url or ".cloudfunctions.net" in url:
            # Determine audience (the root URL)
            parts = url.split('/')
            audience = f"{parts[0]}//{parts[2]}"
            token = get_oidc_token(audience)
            if token:
                request.headers["Authorization"] = f"Bearer {token}"

    httpx_inst.instrument(request_hook=httpx_request_hook)
