resource "google_cloudfunctions2_function" "traffic_generator" {
  name        = "travel-traffic-generator"
  location    = var.region
  description = "Simulates travel traffic for the testbed"
  project     = var.project_id

  build_config {
    runtime     = "python312"
    entry_point = "generate_traffic"
    source {
      storage_source {
        bucket = var.deploy_bucket_name
        object = var.traffic_generator_source_zip
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256M"
    timeout_seconds    = 60
    ingress_settings   = "ALLOW_INTERNAL_ONLY"

    # Do not allow unauthenticated access
    service_account_email = google_service_account.test_runner.email

    environment_variables = {
      ROOT_ROUTER_URL = var.root_router_url
    }
  }

  depends_on = [
    google_storage_bucket_iam_member.gcf_admin_storage_viewer,
    google_storage_bucket_iam_member.cloudbuild_storage_viewer
  ]
}

