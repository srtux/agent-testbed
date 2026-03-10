resource "google_cloudfunctions2_function" "traffic_generator" {
  name        = "travel-traffic-generator"
  location    = var.region
  description = "Simulates travel traffic for the testbed"
  project     = var.project_id

  build_config {
    runtime     = "python312"
    entry_point = "main"
    source {
      storage_source {
        bucket = "${var.project_id}-deploy-artifacts"
        object = var.traffic_generator_source_zip
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256M"
    timeout_seconds    = 60

    # Do not allow unauthenticated access
    service_account_email = google_service_account.test_runner.email

    environment_variables = {
      ROOT_ROUTER_URL = var.root_router_url
    }
  }
}
