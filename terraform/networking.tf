# =============================================================================
# Global HTTPS Load Balancer for Cloud Run services (Serverless NEGs)
# =============================================================================

resource "google_compute_global_address" "cloud_run_lb" {
  name    = "testbed-cloud-run-lb-ip"
  project = var.project_id
}

# --- Serverless NEGs for Cloud Run ---

resource "google_compute_region_network_endpoint_group" "flight_specialist" {
  name                  = "flight-specialist-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.flight_specialist.name
  }
}

resource "google_compute_region_network_endpoint_group" "weather_specialist" {
  name                  = "weather-specialist-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.weather_specialist.name
  }
}

resource "google_compute_region_network_endpoint_group" "profile_mcp" {
  name                  = "profile-mcp-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.profile_mcp.name
  }
}

# --- Backend Services for Cloud Run ---

resource "google_compute_backend_service" "flight_specialist" {
  name    = "flight-specialist-backend"
  project = var.project_id

  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.flight_specialist.id
  }
}

resource "google_compute_backend_service" "weather_specialist" {
  name    = "weather-specialist-backend"
  project = var.project_id

  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.weather_specialist.id
  }
}

resource "google_compute_backend_service" "profile_mcp" {
  name    = "profile-mcp-backend"
  project = var.project_id

  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.profile_mcp.id
  }
}

# --- URL Map (host-based routing) ---

resource "google_compute_url_map" "cloud_run_lb" {
  name            = "testbed-cloud-run-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.flight_specialist.id

  host_rule {
    hosts        = ["flight-specialist.${var.custom_domain}"]
    path_matcher = "flight-specialist"
  }

  host_rule {
    hosts        = ["weather-specialist.${var.custom_domain}"]
    path_matcher = "weather-specialist"
  }

  host_rule {
    hosts        = ["profile-mcp.${var.custom_domain}"]
    path_matcher = "profile-mcp"
  }

  path_matcher {
    name            = "flight-specialist"
    default_service = google_compute_backend_service.flight_specialist.id
  }

  path_matcher {
    name            = "weather-specialist"
    default_service = google_compute_backend_service.weather_specialist.id
  }

  path_matcher {
    name            = "profile-mcp"
    default_service = google_compute_backend_service.profile_mcp.id
  }
}

# --- SSL Certificate (Google-managed) ---

resource "google_compute_managed_ssl_certificate" "cloud_run_lb" {
  name    = "testbed-cloud-run-cert"
  project = var.project_id

  managed {
    domains = [
      "flight-specialist.${var.custom_domain}",
      "weather-specialist.${var.custom_domain}",
      "profile-mcp.${var.custom_domain}",
    ]
  }
}

# --- HTTPS Proxy and Forwarding Rule ---

resource "google_compute_target_https_proxy" "cloud_run_lb" {
  name    = "testbed-cloud-run-https-proxy"
  project = var.project_id

  url_map          = google_compute_url_map.cloud_run_lb.id
  ssl_certificates = [google_compute_managed_ssl_certificate.cloud_run_lb.id]
}

resource "google_compute_global_forwarding_rule" "cloud_run_lb" {
  name    = "testbed-cloud-run-forwarding-rule"
  project = var.project_id

  target     = google_compute_target_https_proxy.cloud_run_lb.id
  port_range = "443"
  ip_address = google_compute_global_address.cloud_run_lb.address

  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# =============================================================================
# GKE Ingress with container-native NEGs
# =============================================================================

resource "google_compute_global_address" "gke_lb" {
  name    = "testbed-gke-lb-ip"
  project = var.project_id
}

resource "google_compute_managed_ssl_certificate" "gke_lb" {
  name    = "testbed-gke-cert"
  project = var.project_id

  managed {
    domains = [
      "hotel-specialist.${var.custom_domain}",
      "car-rental.${var.custom_domain}",
      "inventory-mcp.${var.custom_domain}",
    ]
  }
}

# GKE Ingress - the GKE ingress controller creates NEG-backed backend services automatically
resource "kubernetes_ingress_v1" "testbed_gke" {
  metadata {
    name      = "testbed-gke-ingress"
    namespace = "default"
    annotations = {
      "kubernetes.io/ingress.class"                = "gce"
      "kubernetes.io/ingress.global-static-ip-name" = google_compute_global_address.gke_lb.name
      "networking.gke.io/pre-shared-cert"          = google_compute_managed_ssl_certificate.gke_lb.name
    }
  }

  spec {
    rule {
      host = "hotel-specialist.${var.custom_domain}"
      http {
        path {
          path      = "/*"
          path_type = "ImplementationSpecific"
          backend {
            service {
              name = kubernetes_service.hotel_specialist.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }

    rule {
      host = "car-rental.${var.custom_domain}"
      http {
        path {
          path      = "/*"
          path_type = "ImplementationSpecific"
          backend {
            service {
              name = kubernetes_service.car_rental_specialist.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }

    rule {
      host = "inventory-mcp.${var.custom_domain}"
      http {
        path {
          path      = "/*"
          path_type = "ImplementationSpecific"
          backend {
            service {
              name = kubernetes_service.inventory_mcp.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_service.hotel_specialist,
    kubernetes_service.car_rental_specialist,
    kubernetes_service.inventory_mcp,
  ]
}
