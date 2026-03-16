# Agent-to-Agent (A2A) Communication Guide

This document describes how agents communicate with other specialists or endpoints over standard HTTP pathways inside the **agent-testbed**.

---

## 🛰️ 1. Concept: Microservice Delegation

In this mesh, an agent can distribute part of its reasoning process by calling another agent's REST endpoint. 
*   **Protocol**: Standard HTTP/JSON `POST` requests.
*   **Edge Design**: Wraps the call inside a Python function tool available to the `LlmAgent`.

---

## 💻 2. Implementation Example

Outbound calls leverages the standard Python `httpx` client synchronous/asynchronous triggers:

```python
import httpx
import os

async def call_flight_specialist(user_id: str, destination: str) -> dict:
    url = os.environ.get("FLIGHT_SPECIALIST_URL", "http://localhost:8082/chat")
    payload = {
        "user_id": user_id,
        "destination": destination
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
    response.raise_for_status()
    return response.json()
```

---

## 🔍 3. Context Propagation (Tracing)

Distributed tracing is **fully automated** using OpenTelemetry hooks.

1.  **Preparation**: The app-runner initializes `setup_authenticated_transport()` (from `testbed_utils.telemetry`) at app startup module-level.
2.  **Instrumentor**: Hooks into `HTTPXClientInstrumentor` wrapping `httpx` client instantiations globally for that process cycle.
3.  **Action**: Outbound requests automatically carry `traceparent` sub-envelopes without requiring any manual map-packing hooks backwards.

---

## 🔒 4. Authorization (OIDC ID Tokens)

Outbound calls targeting **Cloud Run** or secure Gateways require Identity verification tokens.

*   **Behind the Scenes**: `testbed_utils.telemetry` intercepts any outgoing requests addressing `.run.app` or `.cloudfunctions.net`.
*   **Injection**: Transparently fetches a Google OIDC ID token using Application Default Credentials (ADC) and puts it inside the `Authorization: Bearer <ID_TOKEN>` header safely.
*   **Validation**: Google-managed infrastructure validates the payload prior forwards routing transparently.

---

## 📥 5. Inbound Extraction

Every agent receiving an A2A trigger extracts the context seamlessly prior process:
```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# Inside app creation:
FastAPIInstrumentor.instrument_app(app)
```
This forces automatic unpacked coordinate bindings back to the current local node accurately maintaining distributed links waterfall graphs perfectly.
