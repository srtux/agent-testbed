# AGENTS.md — AI Agent Development Guide

This document captures hard-won learnings about OpenTelemetry, ADK, and Google Cloud telemetry integration in this testbed. It exists so that future AI coding agents (Claude, Gemini, Copilot, etc.) do not repeat the same mistakes.

## Critical Rules

### 1. Agent Engine Has Built-in OpenTelemetry — Do NOT Manually Create a TracerProvider

**Agents deployed to Vertex AI Agent Engine (RootRouter, BookingOrchestrator) must NOT manually create a `TracerProvider` or call `trace.set_tracer_provider()`.**

Agent Engine automatically initializes OpenTelemetry when `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true` is set in `env_vars` during deployment (see `scripts/deploy_agent_engine.py`). The platform creates its own `TracerProvider` and configures trace export to Cloud Trace automatically.

**However, Agent Engine agents SHOULD call `setup_telemetry()`**. The function detects when OTel is already initialized and skips TracerProvider creation, but still installs critical library instrumentation (httpx, requests, GenAI) and OIDC auth hooks needed for service-to-service calls. Without this, outbound HTTP calls to Cloud Run services (e.g. RootRouter → FlightSpecialist) will fail with 403 permission errors because no OIDC token is injected.

The guards in `testbed_utils/telemetry.py` make this safe:
```python
already_initialized = is_otel_initialized()  # True in Agent Engine
if not already_initialized:
    # TracerProvider setup — skipped in Agent Engine
    ...
# Library instrumentation & OIDC auth — always runs
_setup_oidc_auth(RequestsInstrumentor(), HTTPXClientInstrumentor())
```

**All agents call `setup_telemetry()`** at module level before other imports.

### 2. Use `opentelemetry-exporter-otlp-proto-grpc` — NOT `opentelemetry-exporter-gcp-trace`

The `opentelemetry-exporter-gcp-trace` package is **deprecated**. It uses the proprietary Cloud Trace v2 API (`cloudtrace.googleapis.com`) which can cause data loss during format conversion from OTLP to the proprietary format.

Google recommends using the standard OTLP exporter (`opentelemetry-exporter-otlp-proto-grpc`) pointed at the **Google Cloud Telemetry API** (`telemetry.googleapis.com`). This endpoint accepts native OTLP/gRPC and routes data to Cloud Trace, Cloud Monitoring, and Cloud Logging without lossy conversion.

Reference: https://docs.cloud.google.com/stackdriver/docs/reference/telemetry/overview

### 3. OTLPSpanExporter Requires Explicit Google Auth for telemetry.googleapis.com

**This is the single most common mistake.** Setting `OTEL_EXPORTER_OTLP_ENDPOINT=https://telemetry.googleapis.com` in environment variables is NOT sufficient. The generic `OTLPSpanExporter()` does not handle Google Cloud authentication automatically.

You MUST provide explicit gRPC channel credentials using Application Default Credentials (ADC):

```python
import google.auth
import google.auth.transport.requests
import google.auth.transport.grpc
import grpc
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

credentials, project = google.auth.default()
request = google.auth.transport.requests.Request()
auth_metadata_plugin = google.auth.transport.grpc.AuthMetadataPlugin(
    credentials=credentials, request=request
)
channel_creds = grpc.composite_channel_credentials(
    grpc.ssl_channel_credentials(),
    grpc.metadata_call_credentials(auth_metadata_plugin),
)
exporter = OTLPSpanExporter(
    endpoint="telemetry.googleapis.com:443",
    credentials=channel_creds,
)
```

This is implemented in `testbed_utils/telemetry.py:_create_authenticated_exporter()`.

Reference: https://docs.cloud.google.com/stackdriver/docs/instrumentation/migrate-to-otlp-endpoints

### 4. Service Accounts Need `roles/cloudtrace.agent`

Every service account (Cloud Run SA, GKE KSA via Workload Identity) that exports traces must have the `roles/cloudtrace.agent` IAM role. Without it, trace export silently fails. This is configured in `terraform/iam.tf`.

### 5. OTEL_EXPORTER_OTLP_ENDPOINT Must Be Set in Infrastructure

For Cloud Run and GKE services, the endpoint is set via Terraform environment variables:
```hcl
env {
  name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
  value = "https://telemetry.googleapis.com"
}
```

The `_create_authenticated_exporter()` function reads this env var to decide whether to attach Google ADC credentials.

## Telemetry Architecture by Runtime

| Runtime | TracerProvider Setup | Exporter | Auth |
|---------|---------------------|----------|------|
| **Agent Engine** | Platform auto-creates | Platform-managed | Platform-managed |
| **Cloud Run** | `setup_telemetry()` in `main.py` | `OTLPSpanExporter` with ADC gRPC creds | ADC via service account |
| **GKE** | `setup_telemetry()` in `main.py` | `OTLPSpanExporter` with ADC gRPC creds | ADC via Workload Identity |
| **Local dev** | `setup_telemetry()` | `OTLPSpanExporter()` (no auth, local collector) | N/A |

## Trace Context Propagation

### A2A (Agent-to-Agent HTTP)
- `HTTPXClientInstrumentor` automatically injects `traceparent` headers on outbound `httpx` requests (ADK uses httpx internally)
- `FastAPIInstrumentor` automatically extracts `traceparent` from inbound requests
- No manual header injection needed for A2A calls

### MCP (Agent-to-MCP Server)
- MCP trace propagation uses `opentelemetry.propagate.inject()` to put `traceparent` into the MCP `_meta` object:
  ```python
  from opentelemetry.propagate import inject
  meta = {}
  inject(meta)
  result = await session.call_tool("tool_name", arguments=args, meta=meta)
  ```
- The MCP server extracts this from the meta object to continue the trace

### OIDC Authentication for Cloud Run
- Cross-service calls to Cloud Run require OIDC token injection
- Implemented via `request_hook` callbacks on both `RequestsInstrumentor` and `HTTPXClientInstrumentor`
- See `testbed_utils/telemetry.py:_setup_oidc_auth()`
- Tokens are cached for 55 minutes (OIDC tokens expire after ~1 hour)

## Instrumentation Checklist for New Agents

When adding a new agent to this testbed:

1. **Agent Engine agents**: Call `setup_telemetry()` at module level (before other imports). It safely skips TracerProvider creation but installs OIDC auth and library instrumentation.
2. **Cloud Run / GKE agents**:
   - Call `setup_telemetry()` at module level (before FastAPI app creation)
   - Call `FastAPIInstrumentor.instrument_app(app)` after creating the FastAPI app
   - Set `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` in Terraform
   - Ensure the service account has `roles/cloudtrace.agent`
3. **All agents**: Use `session_id=str(uuid.uuid4())` for unique sessions, not `"default"`
4. **MCP calls**: Use `inject(meta)` for trace propagation through MCP

## Common Mistakes to Avoid

| Mistake | Why It's Wrong | Correct Approach |
|---------|---------------|-----------------|
| Calling `trace.set_tracer_provider()` in Agent Engine agents | Overwrites platform's TracerProvider | Call `setup_telemetry()` which safely skips provider creation |
| Using `opentelemetry-exporter-gcp-trace` | Deprecated, lossy format conversion | Use `opentelemetry-exporter-otlp-proto-grpc` |
| `OTLPSpanExporter()` without credentials | Fails silently against telemetry.googleapis.com | Use `_create_authenticated_exporter()` |
| Setting `session_id="default"` | All sessions collide, traces intermix | Use `str(uuid.uuid4())` |
| Missing `FastAPIInstrumentor` on Cloud Run/GKE | Incoming trace context not extracted | Always instrument FastAPI apps |
| Missing `roles/cloudtrace.agent` on SA | Trace export silently fails | Add IAM binding in terraform/iam.tf |

## Key Dependencies

```
opentelemetry-api>=1.38.0
opentelemetry-sdk>=1.38.0
opentelemetry-exporter-otlp-proto-grpc          # OTLP exporter for telemetry.googleapis.com
opentelemetry-instrumentation-fastapi>=0.59b0    # Inbound trace extraction
opentelemetry-instrumentation-google-genai>=0.7b0 # GenAI/Gemini span capture
opentelemetry-instrumentation-httpx>=0.59b0      # Outbound trace injection (ADK uses httpx)
opentelemetry-instrumentation-requests>=0.59b0   # Outbound trace injection (traffic generator)
google-auth                                       # ADC for OTLP exporter auth
grpcio                                            # gRPC channel credentials
```

**Do NOT add**: `opentelemetry-exporter-gcp-trace` (deprecated), `opentelemetry-exporter-gcp-monitoring` (not needed for traces).
