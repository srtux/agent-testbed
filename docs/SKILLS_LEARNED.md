# Skills Learned

This document captures key technical patterns and solutions learned during the development and debugging of the agent-testbed.

## 🌐 1. Fixing Agent Engine to GKE East-West Connectivity

### Problem
Agent Engine instances (Vertex AI Reasoning Engine) could not reach internal GKE services (e.g., `HotelSpecialist`) even though they were connected to the VPC via a Network Attachment.

### Root Cause
Missing firewall rule. Traffic from Agent Engine egresses through the Network Attachment and appears in the VPC with an IP from the Network Attachment's subnet (e.g., `10.10.0.0/24`). Without a firewall rule allowing this traffic, it is blocked by default.

### Solution
Create a firewall rule in the VPC network allowing traffic from the Network Attachment's subnet to the target resources (e.g., GKE nodes or Load Balancers).

**Example Terraform:**
```terraform
resource "google_compute_firewall" "allow_psc_to_gke" {
  name    = "allow-psc-to-gke"
  network = data.google_compute_network.main.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["80", "8080"]
  }

  source_ranges = ["10.10.0.0/24"] # PSC subnet
}
```

## 📊 2. Comprehensive Telemetry Setup (Traces, Metrics, Logs)

### Problem
Initial setup only covered distributed traces, missing metrics and structured logs.

### Solution
Borrowing from the `ai-demos/capture_telemetry` pattern, we can set up a full-stack observability pipeline using OpenTelemetry with Google Cloud exporters.

**Implementation in `testbed_utils/telemetry.py`:**
1.  **Traces**: Continue using `OTLPSpanExporter` to `telemetry.googleapis.com` with explicit gRPC auth.
2.  **Logs**: Add `CloudLoggingExporter` to route OpenTelemetry logs to Cloud Logging.
3.  **Metrics**: Add `CloudMonitoringMetricsExporter` to send metrics to Cloud Monitoring.

**Code Snippet:**
```python
from opentelemetry.exporter.cloud_logging import CloudLoggingExporter
from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider

# Inside setup_telemetry():
logger_provider = LoggerProvider(resource=provider.resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(CloudLoggingExporter()))
logs.set_logger_provider(logger_provider)

reader = PeriodicExportingMetricReader(CloudMonitoringMetricsExporter())
meter_provider = MeterProvider(metric_readers=[reader], resource=provider.resource)
metrics.set_meter_provider(meter_provider)
```
