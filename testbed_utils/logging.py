import json
import logging
import os
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from opentelemetry import trace

        span = trace.get_current_span()
        span_context = span.get_span_context()
        trace_id = span_context.trace_id if span_context.is_valid else None
        span_id = span_context.span_id if span_context.is_valid else None

        log_data = {
            "severity": record.levelname,
            "message": record.getMessage(),
        }

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "UNKNOWN_PROJECT")
        if trace_id:
            log_data["logging.googleapis.com/trace"] = (
                f"projects/{project_id}/traces/{trace_id:032x}"
            )
        if span_id:
            log_data["logging.googleapis.com/spanId"] = f"{span_id:016x}"

        return json.dumps(log_data)


def setup_logging(level=logging.INFO):
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root_logger.addHandler(handler)
        root_logger.setLevel(level)
    return logging.getLogger(__name__)
