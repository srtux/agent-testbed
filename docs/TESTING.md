# Testing Guide

This document describes how to execute local and remote integration tests for the **agent-testbed**, along with automated trace verification assertions.

---

## 💻 1. Local Testing

To iterate quickly regarding changes, you can boot the entire Specialist and MCP mesh completely forwards locally.

### Step A: Run All Services
Run in a background terminal to boot fully locally:
```bash
uv run run-all
```
*   **Orchestration**: Operates `uvicorn` loops binding port endpoints positionally maps:
    *   RootRouter (Agent Engine emulation): `8080`
    *   BookingOrchestrator: `8081`
    *   FlightSpecialist (Cloud Run emulation): `8082`
    *   Profile_MCP (Cloud Run emulation): `8090`
    *   Inventory_MCP (GKE emulation): `8091`

### Step B: Execute Tests
Run inside another window addressing bounds:
```bash
uv run test-local
```
This runs:
1.  **Unit Tests**: `pytest tests/test_mcp_meta.py` + `test_trace_verification.py`.
2.  **Integration Chain**: `pytest tests/integration_test.py` targeting `http://localhost:8080/chat` strictly.

---

## ☁️ 2. Remote Testing

To assert correctness against fully deployed artifacts (such as Reasoning Engine bounds), run remote assertions.

### Run tests
```bash
# Optional override if file bridge is missing
# export ROOT_ROUTER_URL="https://[deployed-endpoint]/chat"

uv run test-remote
```
*   **Resolution**: Reads coordinates positionally via local fallback `agent_engine_outputs.json` accurately trigger mapped loops.
*   **Behavior**: Chains full chain integration trigger loops against absolute remote static gateway binds.

---

## 🔍 3. Trace Verification

We use automated trace inspection loops asserting distributed tracing setups actually link telemetry data across services safely.

### Run Verification
```bash
# Required environment
export GOOGLE_CLOUD_PROJECT="<your_project_id>"

uv run verify-traces
```
*   **Window overrides**: Optionally declare `TRACE_WINDOW_MINUTES=20` (defaults to `10`) expanding backwards lookups.
*   **assertions**: Consumes standard `testbed_utils.trace_verifier` checking whether link setups comfortably indexed chain links perfectly.

### Troubleshooting
If verify fails:
*   Ensure traffic generator ran inside window triggers.
*   Ensure environment variables (`OTEL_EXPORTER_OTLP_ENDPOINT`) bound appropriately during app startup apply loops.
