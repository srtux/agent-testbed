resource "google_cloud_run_v2_service" "flight_specialist" {
  name     = "flight-specialist"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  labels = {
    testbed = "my-agent-testbed"
  }

  template {
    service_account = google_service_account.flight_specialist.email

    dynamic "vpc_access" {
      for_each = var.vpc_subnetwork != "" ? [1] : []
      content {
        network_interfaces {
          network    = var.vpc_name
          subnetwork = var.vpc_subnetwork
        }
        egress = "ALL_TRAFFIC"
      }
    }

    containers {
      image = var.flight_specialist_image

      ports {
        container_port = 8080
      }

      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = "https://telemetry.googleapis.com"
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "flight-specialist"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "HOTEL_SPECIALIST_URL"
        value = "${local.hotel_specialist_url}/chat"
      }
      env {
        name  = "WEATHER_SPECIALIST_URL"
        value = "${local.weather_specialist_url}/chat"
      }
    }
  }
}

resource "google_cloud_run_v2_service" "weather_specialist" {
  name     = "weather-specialist"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  labels = {
    testbed = "my-agent-testbed"
  }

  template {
    service_account = google_service_account.weather_specialist.email

    dynamic "vpc_access" {
      for_each = var.vpc_subnetwork != "" ? [1] : []
      content {
        network_interfaces {
          network    = var.vpc_name
          subnetwork = var.vpc_subnetwork
        }
        egress = "ALL_TRAFFIC"
      }
    }

    containers {
      image = var.weather_specialist_image

      ports {
        container_port = 8080
      }

      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = "https://telemetry.googleapis.com"
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "weather-specialist"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "INVENTORY_MCP_URL"
        value = "${local.inventory_mcp_url}/sse"
      }
      env {
        name  = "BOOKING_ORCHESTRATOR_URL"
        value = var.booking_orchestrator_url
      }
    }
  }
}

resource "google_cloud_run_v2_service" "profile_mcp" {
  name     = "profile-mcp"
  location = var.region
  project  = var.project_id
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  labels = {
    testbed = "my-agent-testbed"
  }

  template {
    service_account = google_service_account.profile_mcp.email

    dynamic "vpc_access" {
      for_each = var.vpc_subnetwork != "" ? [1] : []
      content {
        network_interfaces {
          network    = var.vpc_name
          subnetwork = var.vpc_subnetwork
        }
        egress = "ALL_TRAFFIC"
      }
    }

    containers {
      image = var.profile_mcp_image

      ports {
        container_port = 8080
      }

      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = "https://telemetry.googleapis.com"
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "profile-mcp"
      }
    }
  }
}

# Explicitly restrict unauthenticated access by not having a google_cloud_run_v2_service_iam_member with allUsers
