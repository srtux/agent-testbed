import pytest
from unittest.mock import MagicMock
from opentelemetry import trace
from opentelemetry.propagate import inject

# A simple mock context class that mirrors what FastMCP passes into handlers
class MockRequestContext:
    def __init__(self, meta=None):
        self.meta = meta

class MockContext:
    def __init__(self, meta=None):
        self.request_context = MockRequestContext(meta)

# Pull the core logic we implanted in the servers
from mcp_servers.Inventory_MCP.main import _extract_trace_context

def test_trace_extraction_from_meta():
    """Validates that a W3C traceparent injected into the meta dict is correctly extracted by the FastMCP helper function."""
    
    tracer = trace.get_tracer(__name__)
    
    # Create an active span
    with tracer.start_as_current_span("test_client_span") as client_span:
        client_ctx = client_span.get_span_context()
        trace_id = client_ctx.trace_id
        
        # Inject the active W3C headers into a meta dictionary just like the ADK Agent does
        meta = {}
        inject(meta)
        
        # Ensure it got injected
        assert "traceparent" in meta
        
        # Create the mock FastMCP context
        fastmcp_ctx = MockContext(meta=meta)
        
        # Run the server-side extraction logic
        extracted_context = _extract_trace_context(fastmcp_ctx)
        
        # In OpenTelemetry Python, extracted context isn't an active span until you start one with it,
        # but the extracted context dict contains the parent Spans.
        
        # We start a new span using the extracted context to simulate what the server does
        with tracer.start_as_current_span("test_server_span", context=extracted_context) as server_span:
            server_ctx = server_span.get_span_context()
            
            # The server's trace ID MUST exactly match the client's trace ID
            assert server_ctx.trace_id == trace_id
            # The server's span is a child, so its ID is different, but the trace ID remains identical.

def test_trace_extraction_no_meta():
    """Validates the system doesn't crash if the _meta array is missing."""
    fastmcp_ctx = MockContext(meta=None)
    extracted_context = _extract_trace_context(fastmcp_ctx)
    
    # It should extract an empty context but not raise an exception
    assert extracted_context == {}
