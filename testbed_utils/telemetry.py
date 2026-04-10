import logging
import os
import sys
import time

logger = logging.getLogger(__name__)


def is_otel_initialized() -> bool:
    """Checks if OpenTelemetry has already been initialized with a real provider."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        return isinstance(provider, TracerProvider)
    except (ImportError, Exception):
        return False


def _create_authenticated_exporter(OTLPSpanExporter):
    """Creates an OTLPSpanExporter with Google Cloud ADC credentials.

    The generic OTLPSpanExporter does NOT handle Google Cloud authentication
    automatically. When targeting telemetry.googleapis.com, we must provide
    explicit gRPC channel credentials using Application Default Credentials.

    See: https://docs.google.com/stackdriver/docs/reference/telemetry/overview
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    if "telemetry.googleapis.com" not in endpoint:
        # Not targeting Google Cloud Telemetry API — use default (e.g., local collector)
        return OTLPSpanExporter()

    try:
        import google.auth
        import google.auth.transport.grpc
        import google.auth.transport.requests
        import grpc

        credentials, _project = google.auth.default()
        request = google.auth.transport.requests.Request()
        auth_metadata_plugin = google.auth.transport.grpc.AuthMetadataPlugin(
            credentials=credentials, request=request
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
        print(
            f"Warning: Could not create authenticated exporter, falling back to default: {e}",
            file=sys.stderr,
        )
        return OTLPSpanExporter()


def setup_authenticated_transport():
    """Hooks into Requests and HTTPX to inject OIDC tokens for service-to-service auth."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    _setup_oidc_auth(RequestsInstrumentor(), HTTPXClientInstrumentor())


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

        enable_manual_trace = (
            os.environ.get(
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "false"
            ).lower()
            != "true"
        )

        if force_cloud_trace or enable_manual_trace:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource

            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

            provider = TracerProvider(
                resource=Resource(
                    attributes={
                        "service.name": os.environ.get(
                            "OTEL_SERVICE_NAME", "unknown_service"
                        ),
                        "gcp.project_id": project_id,
                    }
                )
            )
            exporter = _create_authenticated_exporter(OTLPSpanExporter)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.google_genai import (
            GoogleGenAiSdkInstrumentor,
        )

        # Instrument generic libraries
        GoogleGenAiSdkInstrumentor().instrument()

        # We wrap the underlying transport to inject OIDC tokens for service-to-service auth
        setup_authenticated_transport()

    except ImportError as e:
        print(
            f"Warning: Telemetry dependencies not fully installed: {e}", file=sys.stderr
        )


def _load_audience_map():
    """Parses URL_AUDIENCE_MAP env var into a dict. Returns {} on any failure."""
    import ast

    map_str = os.environ.get("URL_AUDIENCE_MAP", "")
    if not map_str:
        return {}
    try:
        # Handle potential single-quote dict string from env
        parsed = ast.literal_eval(map_str)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def _needs_oidc_auth(url):
    """Determines if a URL requires OIDC token injection for service-to-service auth."""
    logger.debug(f"Checking if {url} needs OIDC auth")
    if ".a.run.app" in url or ".cloudfunctions.net" in url:
        return True
    custom_domain = os.environ.get("CUSTOM_DOMAIN", "")
    if custom_domain and custom_domain in url:
        return True

    # Check audience map for IP/Internal URLs
    audience_map = _load_audience_map()
    if any(url.startswith(k) for k in audience_map):
        return True

    return False


def _get_audience(url):
    """Resolves the OIDC audience for a given URL."""
    audience_map = _load_audience_map()
    for k, v in audience_map.items():
        if url.startswith(k):
            return v
    # Fallback to root URL audience
    parts = url.split("/")
    if len(parts) < 3:
        return url
    return f"{parts[0]}//{parts[2]}"


# OIDC tokens expire after ~1 hour; refresh 5 minutes before expiry
_TOKEN_TTL_SECONDS = 55 * 60


def _setup_oidc_auth(requests_inst, httpx_inst):
    """
    Hooks into Requests and HTTPX to inject OIDC tokens automatically
    for Cloud Run/Functions targets when running in GCP.
    """
    import google.auth
    import google.auth.transport.requests
    from google.oauth2 import id_token

    # Cache: audience -> (token, expiry_timestamp)
    token_cache = {}

    def get_oidc_token(audience):
        cached = token_cache.get(audience)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        try:
            logger.debug(f"Fetching OIDC token for audience: {audience}")
            auth_req = google.auth.transport.requests.Request()
            token = id_token.fetch_id_token(auth_req, audience)
            token_cache[audience] = (token, time.monotonic() + _TOKEN_TTL_SECONDS)
            return token
        except Exception:
            logger.exception(f"Failed to fetch OIDC token for {audience}")
            return None

    def _inject_auth_headers(request, url):
        """Inject OIDC bearer token and rewrite Host header for PSC routing."""
        if not _needs_oidc_auth(url):
            return
        audience = _get_audience(url)
        logger.debug(f"Injecting OIDC auth for {url} (audience={audience})")
        token = get_oidc_token(audience)
        if not token:
            logger.warning(f"No OIDC token available for {url}")
            return
        request.headers["Authorization"] = f"Bearer {token}"
        # Extract host from audience URL for Cloud Run routing via PSC
        if audience and ("https://" in audience or "http://" in audience):
            host = (
                audience.replace("https://", "")
                .replace("http://", "")
                .split("/")[0]
            )
            request.headers["Host"] = host

    # For Requests — inject OIDC tokens via request_hook (used by traffic generator)
    def requests_request_hook(span, request):
        _inject_auth_headers(request, request.url)

    if not requests_inst.is_instrumented_by_opentelemetry:
        requests_inst.instrument(request_hook=requests_request_hook)

    # For HTTPX (ADK uses this)
    def httpx_request_hook(span, request):
        _inject_auth_headers(request, str(request.url))

    if not httpx_inst.is_instrumented_by_opentelemetry:
        httpx_inst.instrument(request_hook=httpx_request_hook)
