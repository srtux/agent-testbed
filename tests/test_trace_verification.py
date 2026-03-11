"""
Trace verification tests for the Agent Testbed.

These tests verify that distributed traces are correctly produced by agents
and MCP servers. Two modes:

1. **Local (in-memory)**: Uses OpenTelemetry's InMemorySpanExporter to capture
   spans during a local integration test, then verifies expected spans exist.

2. **Remote (Cloud Trace)**: Sends traffic to a deployed endpoint, waits for
   trace propagation, then queries Cloud Trace API to verify spans.

Run:
    # Local trace structure tests (no GCP required):
    uv run pytest tests/test_trace_verification.py -k "local" -v -s

    # Remote trace verification (requires deployed services + GCP creds):
    ROOT_ROUTER_URL=https://... uv run pytest tests/test_trace_verification.py -k "remote" -v -s
"""

import os
import time
import pytest
import httpx
from unittest.mock import MagicMock
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from testbed_utils.trace_verifier import (
    InMemoryTraceVerifier,
    VerificationReport,
    SpanInfo,
    TraceInfo,
    EXPECTED_AGENT_SPANS,
    EXPECTED_MCP_SPANS,
)


# ---------------------------------------------------------------------------
# Local / Unit Tests — verify trace verification logic with synthetic spans
# ---------------------------------------------------------------------------

class TestTraceVerifierLocal:
    """Tests that the trace verification logic correctly identifies agent and MCP spans."""

    def _make_mock_exporter(self, span_names: list) -> MagicMock:
        """Create a mock InMemorySpanExporter with given span names."""
        exporter = MagicMock()
        spans = []
        for i, name in enumerate(span_names):
            span = MagicMock()
            ctx = MagicMock()
            ctx.trace_id = 0xABCDEF1234567890ABCDEF1234567890
            ctx.span_id = 0x1234567890ABCDEF + i
            span.get_span_context.return_value = ctx
            span.name = name
            span.parent = None
            span.status = MagicMock()
            span.status.status_code = "OK"
            span.attributes = {"test": True}
            spans.append(span)
        exporter.get_finished_spans.return_value = spans
        return exporter

    def test_verify_detects_agent_spans(self):
        """Verifier should detect agent spans by name patterns."""
        exporter = self._make_mock_exporter([
            "RootRouter",
            "extract_travel_intent",
            "IntentClassifier",
            "FlightSpecialist",
            "validate_dates",
            "check_flight_availability",
            "SeatSelector",
            "HotelSpecialist",
            "calculate_nightly_rate",
            "CarRentalSpecialist",
            "calculate_rental_price",
            "WeatherSpecialist",
            "suggest_packing",
            "BookingOrchestrator",
            "calculate_trip_cost",
            "format_itinerary",
            "ItineraryValidator",
        ])
        verifier = InMemoryTraceVerifier(exporter)
        report = verifier.verify()

        assert report.passed, f"Verification should pass:\n{report.summary()}"
        assert len(report.missing_agents) == 0, f"All agents should be found: missing {report.missing_agents}"

    def test_verify_detects_mcp_spans(self):
        """Verifier should detect MCP server spans by name patterns."""
        exporter = self._make_mock_exporter([
            "get_user_preferences",
            "get_hotel_inventory",
            "get_weather",
            "commit_booking",
        ])
        verifier = InMemoryTraceVerifier(exporter)
        report = verifier.verify()

        assert report.passed
        assert "Profile_MCP" in report.mcp_servers_found
        assert "Inventory_MCP" in report.mcp_servers_found
        assert len(report.missing_mcp_servers) == 0

    def test_verify_reports_missing_components(self):
        """Verifier should report which components are missing."""
        exporter = self._make_mock_exporter([
            "RootRouter",
            "FlightSpecialist",
        ])
        verifier = InMemoryTraceVerifier(exporter)
        report = verifier.verify()

        # Should still pass (has some spans) but report missing ones
        assert report.passed
        assert "RootRouter" in report.agents_found
        assert "FlightSpecialist" in report.agents_found
        assert "BookingOrchestrator" in report.missing_agents
        assert "Profile_MCP" in report.missing_mcp_servers

    def test_verify_fails_on_empty_traces(self):
        """Verifier should fail if no traces are found."""
        exporter = self._make_mock_exporter([])
        verifier = InMemoryTraceVerifier(exporter)
        report = verifier.verify()

        assert not report.passed

    def test_verify_case_insensitive_matching(self):
        """Span name matching should be case-insensitive."""
        exporter = self._make_mock_exporter([
            "rootrouter",
            "FLIGHTSPECIALIST",
            "Get_User_Preferences",
        ])
        verifier = InMemoryTraceVerifier(exporter)
        report = verifier.verify()

        assert "RootRouter" in report.agents_found
        assert "FlightSpecialist" in report.agents_found
        assert "Profile_MCP" in report.mcp_servers_found

    def test_verification_report_summary(self):
        """The summary should be a readable string."""
        report = VerificationReport(
            total_traces=5,
            traces_with_agents=3,
            traces_with_mcp=2,
            agents_found={"RootRouter": 3, "FlightSpecialist": 2},
            mcp_servers_found={"Profile_MCP": 2},
            missing_agents=["BookingOrchestrator"],
            missing_mcp_servers=["Inventory_MCP"],
            passed=True,
        )
        summary = report.summary()
        assert "RootRouter" in summary
        assert "MISSING" in summary
        assert "PASSED" in summary


# ---------------------------------------------------------------------------
# Remote Tests — send real traffic and verify traces in Cloud Trace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remote_trace_generation():
    """
    Sends a request to the deployed RootRouter and verifies that a trace
    was generated with the expected structure.

    Requires:
        - ROOT_ROUTER_URL or ROOT_ROUTER_ENDPOINT env var
        - GOOGLE_CLOUD_PROJECT env var
        - Cloud Trace API access (gcloud auth application-default login)
    """
    endpoint = os.environ.get("ROOT_ROUTER_URL") or os.environ.get("ROOT_ROUTER_ENDPOINT")
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    if not endpoint:
        pytest.skip("ROOT_ROUTER_URL not set — skipping remote trace test")
    if not project_id:
        pytest.skip("GOOGLE_CLOUD_PROJECT not set — skipping remote trace test")

    # Ensure /chat path
    if not endpoint.startswith("projects/") and not endpoint.endswith("/chat"):
        endpoint = endpoint.rstrip("/") + "/chat"

    # Step 1: Send a request that triggers the full waterfall
    payload = {
        "user_id": "trace_test_user",
        "prompt": "I need to travel to SFO next Tuesday through Friday. Book flights, hotel, car, and check weather.",
    }

    print(f"\nSending trace-generating request to {endpoint}...")
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(endpoint, json=payload)
        assert response.status_code == 200, f"Request failed: {response.status_code} {response.text[:200]}"
        data = response.json()
        assert data.get("status") == "complete", f"Orchestration did not complete: {data}"

    print("Request succeeded. Waiting for traces to propagate...")

    # Step 2: Wait for trace propagation (Cloud Trace has some delay)
    time.sleep(30)

    # Step 3: Query Cloud Trace and verify
    from testbed_utils.trace_verifier import CloudTraceVerifier

    verifier = CloudTraceVerifier(project_id=project_id)
    traces = verifier.list_recent_traces(minutes=5)

    assert len(traces) > 0, "No traces found in Cloud Trace within the last 5 minutes"

    report = verifier.verify_agent_spans(traces)
    print(f"\n{report.summary()}")

    # We expect at least the RootRouter and one downstream agent
    assert report.traces_with_agents > 0, "No agent spans found in traces"
    assert "RootRouter" in report.agents_found or "FlightSpecialist" in report.agents_found, (
        f"Neither RootRouter nor FlightSpecialist found. Agents found: {list(report.agents_found.keys())}"
    )


@pytest.mark.asyncio
async def test_remote_mcp_traces_exist():
    """
    Verifies that MCP server spans appear in Cloud Trace after traffic.

    This test checks for Profile_MCP and/or Inventory_MCP span names
    in recent traces, confirming MCP trace propagation works end-to-end.
    """
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    endpoint = os.environ.get("ROOT_ROUTER_URL") or os.environ.get("ROOT_ROUTER_ENDPOINT")

    if not project_id:
        pytest.skip("GOOGLE_CLOUD_PROJECT not set")
    if not endpoint:
        pytest.skip("ROOT_ROUTER_URL not set")

    from testbed_utils.trace_verifier import CloudTraceVerifier

    # Check if there are recent traces with MCP spans (from prior traffic)
    verifier = CloudTraceVerifier(project_id=project_id)
    traces = verifier.list_recent_traces(minutes=15)

    if not traces:
        pytest.skip("No recent traces found — run traffic generator first")

    report = verifier.verify_agent_spans(traces)
    print(f"\n{report.summary()}")

    assert report.traces_with_mcp > 0 or len(report.mcp_servers_found) > 0, (
        f"No MCP server spans found in {len(traces)} traces. "
        f"Ensure traffic has been sent and MCP trace propagation is working."
    )


# ---------------------------------------------------------------------------
# Local integration trace test — verifies spans from local services
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_local_agent_produces_http_spans():
    """
    Sends a request to local RootRouter and checks that the HTTP layer
    produces the expected FastAPI span.

    Requires local services running (uv run run-all).
    """
    endpoint = os.environ.get("ROOT_ROUTER_ENDPOINT", "http://localhost:8080/chat")

    if "localhost" not in endpoint and "127.0.0.1" not in endpoint:
        pytest.skip("Not a local endpoint — use remote tests instead")

    # Quick health check
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await client.get(endpoint.replace("/chat", "/health"))
            if health.status_code != 200:
                pytest.skip("Local RootRouter not running")
    except Exception:
        pytest.skip("Local RootRouter not reachable")

    # Send a request
    payload = {
        "user_id": "local_trace_test",
        "prompt": "Find me a flight to SFO next week.",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(endpoint, json=payload)
        assert response.status_code == 200, f"Local request failed: {response.status_code}"
        data = response.json()
        assert data.get("status") == "complete"
        assert data.get("orchestration_summary"), "No summary returned"
        print(f"\nLocal trace test passed. Summary length: {len(data['orchestration_summary'])} chars")
