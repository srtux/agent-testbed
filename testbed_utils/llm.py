"""Resilient Gemini 4 model wrapper with cross-pool 429 failover and tool-call guardrails."""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from typing import Any, AsyncGenerator, Optional

from google.adk.models.google_llm import Gemini, _ResourceExhaustedError
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import APIError
from pydantic import Field

logger = logging.getLogger(__name__)

DEFAULT_PRO_MODEL_NAME = "gemini-4-neon"
DEFAULT_FLASH_MODEL_NAME = "gemini-4-hydrogen"
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-4-neon",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-4-carbon",
)
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})

# Cache google.genai.Client per running asyncio event loop so aiohttp/httpx sessions
# are never shared across separate asyncio.run() threads in Vertex AI Reasoning Engine.
_LOOP_CLIENTS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[Any, ...], Any]
] = weakref.WeakKeyDictionary()


def default_retry_options() -> types.HttpRetryOptions:
    """Retry transient 429/5xx errors with jittered exponential backoff per model pool."""
    return types.HttpRetryOptions(
        attempts=4,
        initial_delay=1.5,
        max_delay=10.0,
        exp_base=2.0,
        jitter=0.5,
        http_status_codes=sorted(RETRYABLE_STATUS_CODES),
    )


def sanitize_unregistered_tool_calls(
    llm_response: LlmResponse,
    allowed_tools: set[str],
) -> LlmResponse:
    """Strips hallucinated function_call parts not present in llm_request.tools_dict."""
    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        return llm_response

    dropped_names: list[str] = []
    kept_parts: list[types.Part] = []
    for part in parts:
        fn_call = getattr(part, "function_call", None)
        fn_name = getattr(fn_call, "name", None) if fn_call is not None else None
        if fn_name and fn_name not in allowed_tools:
            dropped_names.append(fn_name)
            continue
        kept_parts.append(part)

    if not dropped_names:
        return llm_response

    logger.warning(
        "Dropped unregistered tool call(s) %s; allowed tools=%s",
        dropped_names,
        sorted(allowed_tools),
    )
    if not kept_parts:
        kept_parts = [
            types.Part.from_text(
                text=(
                    "I can coordinate your travel request directly with our "
                    "specialist services. Please share or confirm your member ID, "
                    "destination, and travel dates to proceed."
                )
            )
        ]
    content.parts = kept_parts
    return llm_response


def _is_retryable_model_error(exc: Exception) -> bool:
    if isinstance(exc, _ResourceExhaustedError):
        return True
    if isinstance(exc, APIError):
        code = getattr(exc, "code", None)
        if code in RETRYABLE_STATUS_CODES:
            return True
    msg = str(exc).upper()
    return (
        "429" in msg
        or "RESOURCE_EXHAUSTED" in msg
        or "503" in msg
        or "UNAVAILABLE" in msg
    )


class ResilientGemini(Gemini):
    """Gemini integration targeting Vertex global endpoint with cross-model 429 failover."""

    model: str = DEFAULT_PRO_MODEL_NAME
    vertex_location: str = "global"
    fallback_models: tuple[str, ...] = DEFAULT_FALLBACK_MODELS
    retry_options: Optional[types.HttpRetryOptions] = Field(
        default_factory=default_retry_options
    )

    def _build_client(self):
        from google.genai import Client

        # Respect explicit AI Studio API-key mode in local dev/tests when Vertex is not requested.
        if (
            os.getenv("GOOGLE_API_KEY")
            and os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() != "true"
        ):
            return Client(
                http_options=types.HttpOptions(
                    headers=self._tracking_headers(),
                    retry_options=self.retry_options,
                    base_url=self.base_url,
                )
            )

        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
        if not project:
            try:
                import google.auth

                _, project = google.auth.default()
            except Exception:
                project = None

        credentials = None
        oauth_token = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "").strip()
        if oauth_token:
            from google.oauth2.credentials import Credentials

            credentials = Credentials(oauth_token)

        kwargs: dict[str, Any] = {
            "vertexai": True,
            "location": self.vertex_location,
            "http_options": types.HttpOptions(
                headers=self._tracking_headers(),
                retry_options=self.retry_options,
                base_url=self.base_url,
            ),
        }
        if project:
            kwargs["project"] = project
        if credentials is not None:
            kwargs["credentials"] = credentials
        return Client(**kwargs)

    @property
    def api_client(self):
        cache_key = (
            self.vertex_location,
            self.base_url,
            os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            bool(os.environ.get("GOOGLE_API_KEY")),
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._build_client()

        per_loop = _LOOP_CLIENTS.get(loop)
        if per_loop is None:
            per_loop = {}
            _LOOP_CLIENTS[loop] = per_loop
        client = per_loop.get(cache_key)
        if client is None:
            client = self._build_client()
            per_loop[cache_key] = client
        return client

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        primary = llm_request.model or self.model
        candidates = [primary] + [m for m in self.fallback_models if m != primary]
        orig_contents = list(llm_request.contents)
        allowed_tools = set((llm_request.tools_dict or {}).keys())

        last_err: Optional[Exception] = None
        for idx, candidate_model in enumerate(candidates):
            llm_request.model = candidate_model
            llm_request.contents = list(orig_contents)
            yielded_any = False
            try:
                async for resp in super().generate_content_async(
                    llm_request, stream=stream
                ):
                    yielded_any = True
                    yield sanitize_unregistered_tool_calls(resp, allowed_tools)
                return
            except Exception as exc:
                if yielded_any or not _is_retryable_model_error(exc):
                    raise
                last_err = exc
                next_model = candidates[idx + 1] if idx + 1 < len(candidates) else None
                logger.warning(
                    "Model %s hit transient/quota error (%s); %s",
                    candidate_model,
                    type(exc).__name__,
                    f"failing over to {next_model}" if next_model else "all pools exhausted",
                )

        logger.warning(
            "All Gemini 4 model pools exhausted (%s); returning graceful degraded LlmResponse",
            last_err,
        )
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            "Our travel concierge model capacity is momentarily busy. "
                            "Your session is preserved—please retry or confirm your itinerary details."
                        )
                    )
                ],
            )
        )


def build_pro_model(model_name: Optional[str] = None) -> ResilientGemini:
    """Builds a ResilientGemini instance for orchestrator/specialist reasoning roles."""
    resolved = model_name or os.environ.get("PRO_MODEL", DEFAULT_PRO_MODEL_NAME)
    return ResilientGemini(model=resolved)


def build_flash_model(model_name: Optional[str] = None) -> ResilientGemini:
    """Builds a ResilientGemini instance for high-throughput sub-agent/classifier roles."""
    resolved = model_name or os.environ.get("FLASH_MODEL", DEFAULT_FLASH_MODEL_NAME)
    return ResilientGemini(model=resolved)
