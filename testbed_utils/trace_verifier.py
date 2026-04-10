"""
Trace verification utility for the Agent Testbed.

Queries Google Cloud Trace API to verify that distributed traces contain the
expected spans for agents and MCP servers. Can also verify traces from a local
in-memory exporter for unit testing.

Usage:
    from testbed_utils.trace_verifier import CloudTraceVerifier

    verifier = CloudTraceVerifier(project_id="my-project")
    traces = verifier.list_recent_traces(minutes=5)
    report = verifier.verify_agent_spans(traces)
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Expected span name patterns for each component in the testbed.
# These are matched as substrings against span displayName.
EXPECTED_AGENT_SPANS = {
    "RootRouter": ["RootRouter", "extract_travel_intent"],
    "IntentClassifier": ["IntentClassifier"],
    "FlightSpecialist": [
        "FlightSpecialist",
        "validate_dates",
        "check_flight_availability",
    ],
    "SeatSelector": ["SeatSelector"],
    "HotelSpecialist": ["HotelSpecialist", "calculate_nightly_rate"],
    "CarRentalSpecialist": ["CarRentalSpecialist", "calculate_rental_price"],
    "WeatherSpecialist": ["WeatherSpecialist", "suggest_packing"],
    "BookingOrchestrator": [
        "BookingOrchestrator",
        "calculate_trip_cost",
        "format_itinerary",
    ],
    "ItineraryValidator": ["ItineraryValidator"],
}

EXPECTED_MCP_SPANS = {
    "Profile_MCP": ["get_user_preferences", "profile", "Profile"],
    "Inventory_MCP": [
        "get_hotel_inventory",
        "get_weather",
        "commit_booking",
        "inventory",
        "Inventory",
    ],
}


@dataclass
class SpanInfo:
    """Lightweight representation of a trace span."""

    span_id: str
    name: str
    parent_span_id: str = ""
    start_time: str = ""
    end_time: str = ""
    status: str = ""
    attributes: dict = field(default_factory=dict)


@dataclass
class TraceInfo:
    """Lightweight representation of a trace."""

    trace_id: str
    spans: list = field(default_factory=list)


@dataclass
class VerificationReport:
    """Results of trace verification."""

    total_traces: int = 0
    traces_with_agents: int = 0
    traces_with_mcp: int = 0
    agents_found: dict = field(default_factory=dict)
    mcp_servers_found: dict = field(default_factory=dict)
    missing_agents: list = field(default_factory=list)
    missing_mcp_servers: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    passed: bool = False

    def summary(self) -> str:
        lines = [
            "Trace Verification Report",
            f"  Total traces examined: {self.total_traces}",
            f"  Traces with agent spans: {self.traces_with_agents}",
            f"  Traces with MCP spans: {self.traces_with_mcp}",
            f"  Agents found: {', '.join(sorted(self.agents_found.keys())) or 'none'}",
            f"  MCP servers found: {', '.join(sorted(self.mcp_servers_found.keys())) or 'none'}",
        ]
        if self.missing_agents:
            lines.append(f"  MISSING agents: {', '.join(self.missing_agents)}")
        if self.missing_mcp_servers:
            lines.append(
                f"  MISSING MCP servers: {', '.join(self.missing_mcp_servers)}"
            )
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"    - {e}")
        lines.append(f"  Result: {'PASSED' if self.passed else 'FAILED'}")
        return "\n".join(lines)


def _analyze_traces(
    traces: list,
    require_all_agents: bool = False,
    require_all_mcp: bool = False,
) -> VerificationReport:
    """Shared verification logic: scan traces for expected agent and MCP spans.

    Args:
        traces: List of TraceInfo objects to examine.
        require_all_agents: If True, all agents must appear across traces to pass.
        require_all_mcp: If True, both MCP servers must appear across traces to pass.
    """
    report = VerificationReport(total_traces=len(traces))

    for trace in traces:
        span_names = [s.name for s in trace.spans]
        has_agent = False
        has_mcp = False

        for agent_name, patterns in EXPECTED_AGENT_SPANS.items():
            for pattern in patterns:
                if any(pattern.lower() in sn.lower() for sn in span_names):
                    report.agents_found.setdefault(agent_name, 0)
                    report.agents_found[agent_name] += 1
                    has_agent = True
                    break

        for mcp_name, patterns in EXPECTED_MCP_SPANS.items():
            for pattern in patterns:
                if any(pattern.lower() in sn.lower() for sn in span_names):
                    report.mcp_servers_found.setdefault(mcp_name, 0)
                    report.mcp_servers_found[mcp_name] += 1
                    has_mcp = True
                    break

        if has_agent:
            report.traces_with_agents += 1
        if has_mcp:
            report.traces_with_mcp += 1

    # Determine missing components
    for agent_name in EXPECTED_AGENT_SPANS:
        if agent_name not in report.agents_found:
            report.missing_agents.append(agent_name)
    for mcp_name in EXPECTED_MCP_SPANS:
        if mcp_name not in report.mcp_servers_found:
            report.missing_mcp_servers.append(mcp_name)

    # Determine pass/fail
    if report.total_traces == 0:
        report.passed = False
        report.errors.append("No traces found")
    elif require_all_agents and report.missing_agents:
        report.passed = False
    elif require_all_mcp and report.missing_mcp_servers:
        report.passed = False
    else:
        report.passed = (
            len(report.agents_found) > 0 and len(report.mcp_servers_found) > 0
        )

    return report


class CloudTraceVerifier:
    """Queries Google Cloud Trace v1 API to verify agent and MCP spans."""

    def __init__(self, project_id: str = ""):
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not self.project_id:
            raise ValueError("project_id is required (or set GOOGLE_CLOUD_PROJECT)")

    def list_recent_traces(self, minutes: int = 10, page_size: int = 20) -> list:
        """List recent traces from Cloud Trace v1 API."""
        import datetime

        from googleapiclient import discovery

        now = datetime.datetime.now(datetime.timezone.utc)
        start = now - datetime.timedelta(minutes=minutes)

        start_time = start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        end_time = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        service = discovery.build("cloudtrace", "v1", cache_discovery=False)

        traces = []
        try:
            request = (
                service.projects()
                .traces()
                .list(
                    projectId=self.project_id,
                    startTime=start_time,
                    endTime=end_time,
                    pageSize=page_size,
                    orderBy="start desc",
                )
            )
            response = request.execute()

            for trace_summary in response.get("traces", []):
                trace_id = trace_summary.get("traceId", "")
                try:
                    trace_data = (
                        service.projects()
                        .traces()
                        .get(projectId=self.project_id, traceId=trace_id)
                        .execute()
                    )
                except Exception:
                    continue

                spans = []
                for span_data in trace_data.get("spans", []):
                    spans.append(
                        SpanInfo(
                            span_id=span_data.get("spanId", ""),
                            name=span_data.get("name", ""),
                            parent_span_id=span_data.get("parentSpanId", ""),
                            start_time=span_data.get("startTime", ""),
                            end_time=span_data.get("endTime", ""),
                            attributes=span_data.get("labels", {}),
                        )
                    )
                traces.append(TraceInfo(trace_id=trace_id, spans=spans))

        except Exception as e:
            logger.error(f"Failed to list traces: {e}")
            raise

        return traces

    def verify_agent_spans(self, traces: list, **kwargs) -> VerificationReport:
        """Verify that traces contain expected agent and MCP server spans."""
        return _analyze_traces(traces, **kwargs)


class InMemoryTraceVerifier:
    """Verifies spans collected by an in-memory exporter (for local/unit tests).

    Usage:
        from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter
        exporter = InMemorySpanExporter()
        # ... run agent code ...
        verifier = InMemoryTraceVerifier(exporter)
        report = verifier.verify()
    """

    def __init__(self, exporter):
        self.exporter = exporter

    def get_traces(self) -> list:
        """Convert in-memory spans to TraceInfo objects grouped by trace ID."""
        spans_by_trace = {}
        for span in self.exporter.get_finished_spans():
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, "032x")
            if trace_id not in spans_by_trace:
                spans_by_trace[trace_id] = TraceInfo(trace_id=trace_id)

            spans_by_trace[trace_id].spans.append(
                SpanInfo(
                    span_id=format(ctx.span_id, "016x"),
                    name=span.name,
                    parent_span_id=format(span.parent.span_id, "016x")
                    if span.parent
                    else "",
                    status=str(span.status.status_code) if span.status else "",
                    attributes=dict(span.attributes) if span.attributes else {},
                )
            )

        return list(spans_by_trace.values())

    def verify(self, **kwargs) -> VerificationReport:
        """Verify spans from the in-memory exporter."""
        traces = self.get_traces()
        # InMemoryTraceVerifier uses a slightly relaxed pass criteria:
        # passes if *any* recognized spans are found (agents OR mcp)
        report = _analyze_traces(traces, **kwargs)
        if report.total_traces > 0 and not report.passed:
            has_any = len(report.agents_found) > 0 or len(report.mcp_servers_found) > 0
            if has_any:
                report.passed = True
        return report


def verify_traces_exist(
    project_id: str = "",
    minutes: int = 10,
    require_all_agents: bool = False,
    require_all_mcp: bool = False,
) -> VerificationReport:
    """Convenience function: query Cloud Trace and verify spans exist.

    Returns a VerificationReport with pass/fail and detailed findings.
    """
    verifier = CloudTraceVerifier(project_id=project_id)
    traces = verifier.list_recent_traces(minutes=minutes)
    return verifier.verify_agent_spans(
        traces,
        require_all_agents=require_all_agents,
        require_all_mcp=require_all_mcp,
    )
