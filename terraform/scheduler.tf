# Cloud Scheduler job to invoke the traffic generator Cloud Function periodically.
# This creates a steady stream of traces through the entire agent + MCP waterfall.

resource "google_cloud_scheduler_job" "traffic_generator_trigger" {
  name        = "travel-traffic-trigger"
  description = "Periodically invokes the traffic generator to keep agents warm and produce traces"
  project     = var.project_id
  region      = "us-east1"
  schedule    = var.traffic_schedule # Default: every 5 minutes
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.traffic_generator.service_config[0].uri

    oidc_token {
      service_account_email = google_service_account.test_runner.email
      audience              = google_cloudfunctions2_function.traffic_generator.service_config[0].uri
    }
  }

  retry_config {
    retry_count          = 1
    min_backoff_duration = "5s"
    max_backoff_duration = "30s"
  }
}
