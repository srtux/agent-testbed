resource "google_cloud_run_v2_service" "flight_specialist" {
  name     = "flight-specialist"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.flight_specialist.email
    
    containers {
      image = var.flight_specialist_image
      
      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
    }
  }
}

resource "google_cloud_run_v2_service" "weather_specialist" {
  name     = "weather-specialist"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.weather_specialist.email
    
    containers {
      image = var.weather_specialist_image
      
      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
    }
  }
}

resource "google_cloud_run_v2_service" "profile_mcp" {
  name     = "profile-mcp"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.profile_mcp.email
    
    containers {
      image = var.profile_mcp_image
      
      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
    }
  }
}

# Explicitly restrict unauthenticated access by not having a google_cloud_run_v2_service_iam_member with allUsers
