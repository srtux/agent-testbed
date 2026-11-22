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


def _patch_adk_app_name_validation():
    """Relaxes google-adk 2.0+ validate_app_name() to allow numeric Reasoning Engine IDs."""
    try:
        import google.adk.apps.app as _adk_app_mod

        _orig_validate = getattr(_adk_app_mod, "validate_app_name", None)
        if _orig_validate and not getattr(
            _orig_validate, "_allows_numeric_engine_id", False
        ):

            def _allow_numeric_engine_id(name: str) -> None:
                if isinstance(name, str) and name.isdigit():
                    return
                return _orig_validate(name)

            _allow_numeric_engine_id._allows_numeric_engine_id = True
            _adk_app_mod.validate_app_name = _allow_numeric_engine_id
    except Exception:
        pass


def _patch_otel_cross_context_detach():
    """Suppresses benign cross-context OTel token detach tracebacks during asyncgen teardown.

    Under google-adk 2.0.0a3 NEW_WORKFLOW sub-agent transfers (e.g. InspirationAgent ->
    PlaceAgent/PoiAgent), child workflow nodes yield inside synchronous OTel span context
    managers (`use_span`, `_use_extra_generate_content_attributes`) in one asyncio Task's
    Context and are later closed (`GeneratorExit`) from the outer AgentTool/Runner Context.
    `ContextVar.reset(token)` raises `ValueError: <Token ...> was created in a different
    Context`, which `opentelemetry.context.detach()` catches and logs via `logger.exception`,
    emitting false-positive `severity=ERROR` tracebacks to Reasoning Engine stderr while
    `use_span`'s outer `finally` block still ends the span normally.
    """
    try:
        from opentelemetry.context.contextvars_context import ContextVarsRuntimeContext

        _orig_detach = getattr(ContextVarsRuntimeContext, "detach", None)
        if _orig_detach and not getattr(
            _orig_detach, "_suppresses_cross_context_value_error", False
        ):

            def _safe_contextvars_detach(self, token) -> None:
                try:
                    return _orig_detach(self, token)
                except ValueError as exc:
                    if "was created in a different Context" in str(exc):
                        logger.debug(
                            "Ignoring cross-context OTel token detach during generator close: %s",
                            exc,
                        )
                        return
                    raise

            _safe_contextvars_detach._suppresses_cross_context_value_error = True
            ContextVarsRuntimeContext.detach = _safe_contextvars_detach
    except Exception:
        pass


def is_transient_session_error(exc: BaseException) -> bool:
    """Returns True for transient Vertex AI session control-plane errors (e.g. UNVERIFIED_ORG_POLICY, 429, 5xx)."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    code = getattr(exc, "code", None)
    if code in {408, 429, 500, 502, 503, 504}:
        return True
    msg = str(exc).upper()
    transient_markers = (
        "UNVERIFIED_ORG_POLICY",
        "FAILED TO CHECK ORG POLICY",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "INTERNAL",
        "429",
        "500",
        "502",
        "503",
        "504",
    )
    return any(marker in msg for marker in transient_markers)


def _run_coro_in_worker_thread(coro_fn, timeout: float = 30.0):
    """Runs an async callable in a dedicated thread without leaking uncaught exceptions to stderr."""
    import asyncio
    import queue
    import threading

    outcome_queue: queue.Queue = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            res = asyncio.run(coro_fn())
            outcome_queue.put(("ok", res))
        except BaseException as exc:  # noqa: BLE001
            outcome_queue.put(("err", exc))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    try:
        status, payload = outcome_queue.get_nowait()
    except queue.Empty:
        raise RuntimeError(
            f"Timed out after {timeout:.1f}s waiting for session operation."
        ) from None
    if status == "err":
        if isinstance(payload, Exception):
            raise payload
        raise RuntimeError(f"Session operation aborted: {payload}") from None
    return payload


def _record_fallback_session_id(adk_app, session_id: str, max_entries: int = 512) -> None:
    fallback_ids = adk_app._tmpl_attrs.get("fallback_in_memory_sessions")
    if not isinstance(fallback_ids, dict):
        fallback_ids = {}
        adk_app._tmpl_attrs["fallback_in_memory_sessions"] = fallback_ids
    if len(fallback_ids) >= max_entries and session_id not in fallback_ids:
        fallback_ids.pop(next(iter(fallback_ids)), None)
    fallback_ids[session_id] = True


async def resilient_adk_async_create_session(
    adk_app,
    *,
    user_id: str,
    session_id: str | None = None,
    state: dict | None = None,
    max_attempts: int = 3,
    base_delay: float = 0.6,
    **kwargs,
):
    """Creates an ADK session with transient control-plane retries and in-memory fallback."""
    import asyncio

    if not adk_app._tmpl_attrs.get("session_service"):
        adk_app.set_up()

    app_name = adk_app._tmpl_attrs.get("app_name")
    primary_service = adk_app._tmpl_attrs.get("session_service")
    in_memory_service = adk_app._tmpl_attrs.get("in_memory_session_service")

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await primary_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state=state,
                **kwargs,
            )
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < max_attempts and is_transient_session_error(exc):
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Transient session creation error on attempt %d/%d for user %s (%s: %s); retrying in %.1fs",
                    attempt + 1,
                    max_attempts,
                    user_id,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            break

    if in_memory_service is not None and in_memory_service is not primary_service:
        logger.warning(
            "Primary session_service.create_session failed for user %s (%s: %s); falling back to InMemorySessionService",
            user_id,
            type(last_exc).__name__ if last_exc else "UnknownError",
            last_exc,
        )
        fallback_session = await in_memory_service.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state=state,
        )
        _record_fallback_session_id(adk_app, fallback_session.id)
        return fallback_session

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Failed to create session.")


def resilient_adk_create_session(
    adk_app,
    *,
    user_id: str,
    session_id: str | None = None,
    state: dict | None = None,
    timeout: float = 30.0,
    **kwargs,
):
    """Thread-safe sync wrapper for resilient_adk_async_create_session without uncaught thread stderr."""
    return _run_coro_in_worker_thread(
        lambda: resilient_adk_async_create_session(
            adk_app,
            user_id=user_id,
            session_id=session_id,
            state=state,
            **kwargs,
        ),
        timeout=timeout,
    )


def resilient_adk_stream_query(
    adk_app,
    *,
    message,
    user_id: str,
    session_id: str | None = None,
    run_config: dict | None = None,
    **kwargs,
):
    """Streams ADK responses using InMemoryRunner for stateless/fallback sessions and primary Runner otherwise."""
    from google.adk.agents.run_config import RunConfig
    from google.genai import types
    from vertexai.agent_engines import _utils

    if isinstance(message, dict):
        content = types.Content.model_validate(message)
    elif isinstance(message, str):
        content = types.Content(role="user", parts=[types.Part(text=message)])
    else:
        raise TypeError(
            "message must be a string or a dictionary representing a Content object."
        )

    if not adk_app._tmpl_attrs.get("runner"):
        adk_app.set_up()

    validated_run_config = None
    if run_config is not None:
        if isinstance(run_config, dict):
            validated_run_config = RunConfig.model_validate(run_config)
        elif isinstance(run_config, RunConfig):
            validated_run_config = run_config
        else:
            raise TypeError(
                "run_config must be a dictionary representing a RunConfig object."
            )

    in_memory_runner = adk_app._tmpl_attrs.get("in_memory_runner")
    in_memory_service = adk_app._tmpl_attrs.get("in_memory_session_service")
    fallback_ids = adk_app._tmpl_attrs.get("fallback_in_memory_sessions") or {}

    use_in_memory = False
    if not session_id:
        if in_memory_runner is not None and in_memory_service is not None:
            app_name = adk_app._tmpl_attrs.get("app_name")
            ephemeral_session = _run_coro_in_worker_thread(
                lambda: in_memory_service.create_session(
                    app_name=app_name, user_id=user_id
                )
            )
            session_id = ephemeral_session.id
            use_in_memory = True
        else:
            created = resilient_adk_create_session(adk_app, user_id=user_id)
            session_id = created.id
            fallback_ids = adk_app._tmpl_attrs.get("fallback_in_memory_sessions") or {}
            use_in_memory = session_id in fallback_ids
    elif session_id in fallback_ids and in_memory_runner is not None:
        use_in_memory = True

    active_runner = (
        in_memory_runner
        if (use_in_memory and in_memory_runner is not None)
        else adk_app._tmpl_attrs.get("runner")
    )
    run_kwargs = dict(kwargs)
    if validated_run_config is not None:
        run_kwargs["run_config"] = validated_run_config

    for event in active_runner.run(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
        **run_kwargs,
    ):
        yield _utils.dump_event_for_json(event)


def setup_authenticated_transport():
    """Hooks into Requests and HTTPX to inject OIDC tokens for service-to-service auth."""
    _patch_adk_app_name_validation()
    _patch_otel_cross_context_detach()
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

            project_id = os.environ.get(
                "GOOGLE_CLOUD_PROJECT", os.environ.get("PROJECT_ID", "")
            )
            if not project_id:
                try:
                    import google.auth

                    _, detected_project = google.auth.default()
                    project_id = detected_project or ""
                except Exception:
                    project_id = ""

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
    """Parses URL_AUDIENCE_MAP env var into a dict and merges *_URL / *_AUDIENCE env pairs."""
    import ast
    import json

    audience_map = {}
    map_str = os.environ.get("URL_AUDIENCE_MAP", "")
    if map_str:
        try:
            parsed = json.loads(map_str)
            if isinstance(parsed, dict):
                audience_map.update(parsed)
        except Exception:
            try:
                parsed = ast.literal_eval(map_str)
                if isinstance(parsed, dict):
                    audience_map.update(parsed)
            except (ValueError, SyntaxError):
                pass

    # Also merge explicit service URL -> Audience environment variable pairs
    env_pairs = [
        ("FLIGHT_SPECIALIST_URL", "FLIGHT_SPECIALIST_AUDIENCE"),
        ("WEATHER_SPECIALIST_URL", "WEATHER_SPECIALIST_AUDIENCE"),
        ("PROFILE_MCP_URL", "PROFILE_MCP_AUDIENCE"),
    ]
    for url_var, aud_var in env_pairs:
        svc_url = os.environ.get(url_var, "").strip()
        svc_aud = os.environ.get(aud_var, "").strip()
        if svc_url and svc_aud:
            audience_map.setdefault(svc_url, svc_aud)
            # Also register the origin prefix (e.g. http://10.128.0.103)
            parts = svc_url.split("/")
            if len(parts) >= 3:
                origin = f"{parts[0]}//{parts[2]}"
                audience_map.setdefault(origin, svc_aud)

    return audience_map


async def invoke_booking_orchestrator(
    url: str, user_id: str, itinerary_details: str, timeout: float = 180.0
) -> dict:
    """Invokes BookingOrchestrator over either Vertex AI Agent Engine REST API or HTTP /chat."""
    import json
    import re

    import httpx

    re_match = re.search(
        r"(projects/[^/]+/locations/([^/]+)/reasoningEngines/[^/:?]+)", url or ""
    )
    if re_match:
        resource_name = re_match.group(1)
        location = re_match.group(2)
        stream_url = (
            f"https://{location}-aiplatform.googleapis.com/v1/"
            f"{resource_name}:streamQuery?alt=sse"
        )
        token = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "").strip()
        if not token:
            import google.auth
            import google.auth.transport.requests

            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token

        prompt = (
            f"Please finalize the following itinerary and summarize: "
            f"{itinerary_details} for user {user_id}"
        )
        payload = {
            "class_method": "stream_query",
            "input": {"user_id": user_id, "message": prompt},
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(stream_url, json=payload, headers=headers)
            response.raise_for_status()
            raw_text = response.text

        final_response = ""
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            try:
                evt = json.loads(line)
                for part in evt.get("content", {}).get("parts", []):
                    if isinstance(part, dict) and part.get("text"):
                        final_response += part["text"]
            except Exception:
                pass
        return {
            "status": "confirmed",
            "summary": final_response or "Booking finalized via Reasoning Engine.",
        }

    payload = {"user_id": user_id, "itinerary_details": itinerary_details}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


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
    import httpx
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

    if requests_inst.is_instrumented_by_opentelemetry:
        requests_inst.uninstrument()
    requests_inst.instrument(request_hook=requests_request_hook)

    # For HTTPX (ADK and specialist tools use both sync Client and AsyncClient)
    def httpx_request_hook(span, request):
        _inject_auth_headers(request, str(request.url))

    async def async_httpx_request_hook(span, request):
        _inject_auth_headers(request, str(request.url))

    if httpx_inst.is_instrumented_by_opentelemetry:
        httpx_inst.uninstrument()
    httpx_inst.instrument(
        request_hook=httpx_request_hook,
        async_request_hook=async_httpx_request_hook,
    )

    # Also wrap httpx.Client.send and httpx.AsyncClient.send directly so OIDC
    # and PSC Host headers are guaranteed even if OTel instrumentation is reset
    # by the host runtime (e.g. Vertex AI Reasoning Engine).
    _orig_sync_send = getattr(httpx.Client, "_orig_oidc_send", httpx.Client.send)
    httpx.Client._orig_oidc_send = _orig_sync_send

    def _oidc_sync_send(self, request, *args, **kwargs):
        _inject_auth_headers(request, str(request.url))
        return _orig_sync_send(self, request, *args, **kwargs)

    httpx.Client.send = _oidc_sync_send

    _orig_async_send = getattr(
        httpx.AsyncClient, "_orig_oidc_send", httpx.AsyncClient.send
    )
    httpx.AsyncClient._orig_oidc_send = _orig_async_send

    async def _oidc_async_send(self, request, *args, **kwargs):
        _inject_auth_headers(request, str(request.url))
        return await _orig_async_send(self, request, *args, **kwargs)

    httpx.AsyncClient.send = _oidc_async_send
