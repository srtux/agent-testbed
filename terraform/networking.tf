# =============================================================================
# Global HTTPS Load Balancer for Cloud Run services (Serverless NEGs)
# Only created when custom_domain is set.
# =============================================================================



# --- Serverless NEGs for Cloud Run ---

resource "google_compute_region_network_endpoint_group" "flight_specialist" {
  count                 = 1
  name                  = "flight-specialist-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.flight_specialist.name
  }
}

resource "google_compute_region_network_endpoint_group" "weather_specialist" {
  count                 = 1
  name                  = "weather-specialist-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.weather_specialist.name
  }
}

resource "google_compute_region_network_endpoint_group" "profile_mcp" {
  count                 = 1
  name                  = "profile-mcp-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.profile_mcp.name
  }
}


