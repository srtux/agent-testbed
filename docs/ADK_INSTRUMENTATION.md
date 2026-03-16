# ADK Instrumentation: Agent Engine vs. Cloud Run / GKE

This document clarifies the critical differences in **OpenTelemetry initialization** depending on the runtime environment where your ADK (Agent Development Kit) agents are executing.

---

## 🚀 Two Distinct Execution Models

To avoid double-initialization crashes or silent telemetry drops, follow the environment-specific loading hooks correctly.

### 🟣 1. Vertex AI Agent Engine (Managed Platform)

When deployed as a Reasoning Engine, the platform **inherently initializes** OpenTelemetry hooks prior loading your binary.

*   **Rule**: Do **NOT** call `setup_telemetry()` or create a `TracerProvider` manually. Overwriting the platform's provider will immediately break trace exports to Cloud Trace.
*   **Required Action**: You MUST call `setup_authenticated_transport()` at the module-level instead to install OIDC auth interceptors for outbound requests.

**Example `main.py` entrypoint:**
```python
from testbed_utils.telemetry import setup_authenticated_transport

# 1. Setup transport auth ONLY
setup_authenticated_transport()

# 2. Imports & Runner loads onwards
from root_router.agent import agent
```

---

### 🔵 2. Cloud Run & GKE (Self-Managed Containers)

When running agents as standard FastAPI microservices inside standard containers (e.g., specialists), you own the full runtime life cycle.

*   **Rule**: You **MUST** initialize the OpenTelemetry SDK containing your target `TracerProvider` exporter loops yourself.
*   **Required Action**: Call `setup_telemetry()` at the module-level to load `OTLPSpanExporter` bound targets appropriately.

**Example `main.py` entrypoint:**
```python
from testbed_utils.telemetry import setup_telemetry

# 1. Setup FULL Telemetry loops 
setup_telemetry()

# 2. Add FastAPI instrumentor hooks onwards
FastAPIInstrumentor.instrument_app(app)
```

---

## 📊 Summary Comparison

| Metric | Agent Engine (Vertex) | Cloud Run / GKE |
| :--- | :--- | :--- |
| **Exporter** | Platform-managed | `OTLPSpanExporter` (authenticated) |
| **Auth Setup** | `setup_authenticated_transport()` | `setup_telemetry()` |
| **Inbound Extraction** | FastAPIInstrumentor | FastAPIInstrumentor |
| **VPC Binding (Egress)** | Private Service Connect (PSC) | Direct VPC Egress allocated bounds |
| **Safty Hazard** | Overwriting global TracerProvider crashes exports | Forgetting `setup_telemetry()` drops links |

Both environments leverage identical `GoogleGenAiSdkInstrumentor` sub-envelopes under the hood, guaranteeing consistent Trace IDs distributed backwards downstream seamlessly!
