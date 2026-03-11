# =============================================================================
# Global HTTPS Load Balancer for Cloud Run services (Serverless NEGs)
# Only created when custom_domain is set.
# =============================================================================

resource "google_compute_global_address" "cloud_run_lb" {
  count   = local.use_custom_domain ? 1 : 0
  name    = "testbed-cloud-run-lb-ip"
  project = var.project_id
}

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

# --- Backend Services for Cloud Run ---

resource "google_compute_backend_service" "flight_specialist" {
  count   = local.use_custom_domain ? 1 : 0
  name    = "flight-specialist-backend"
  project = var.project_id

  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.flight_specialist[0].id
  }
}

resource "google_compute_backend_service" "weather_specialist" {
  count   = local.use_custom_domain ? 1 : 0
  name    = "weather-specialist-backend"
  project = var.project_id

  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.weather_specialist[0].id
  }
}

resource "google_compute_backend_service" "profile_mcp" {
  count   = local.use_custom_domain ? 1 : 0
  name    = "profile-mcp-backend"
  project = var.project_id

  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.profile_mcp[0].id
  }
}

# --- URL Map (host-based routing) ---

resource "google_compute_url_map" "cloud_run_lb" {
  count           = local.use_custom_domain ? 1 : 0
  name            = "testbed-cloud-run-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.flight_specialist[0].id

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
    default_service = google_compute_backend_service.flight_specialist[0].id
  }

  path_matcher {
    name            = "weather-specialist"
    default_service = google_compute_backend_service.weather_specialist[0].id
  }

  path_matcher {
    name            = "profile-mcp"
    default_service = google_compute_backend_service.profile_mcp[0].id
  }
}

# --- SSL Certificate (Google-managed) ---

resource "google_compute_managed_ssl_certificate" "cloud_run_lb" {
  count   = local.use_custom_domain ? 1 : 0
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
  count   = local.use_custom_domain ? 1 : 0
  name    = "testbed-cloud-run-https-proxy"
  project = var.project_id

  url_map          = google_compute_url_map.cloud_run_lb[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.cloud_run_lb[0].id]
}

resource "google_compute_global_forwarding_rule" "cloud_run_lb" {
  count   = local.use_custom_domain ? 1 : 0
  name    = "testbed-cloud-run-forwarding-rule"
  project = var.project_id

  target     = google_compute_target_https_proxy.cloud_run_lb[0].id
  port_range = "443"
  ip_address = google_compute_global_address.cloud_run_lb[0].address

  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# =============================================================================
# GKE Ingress with container-native NEGs (only with custom domain)
# Without custom domain, GKE services use LoadBalancer type directly.
# =============================================================================

resource "google_compute_global_address" "gke_lb" {
  count   = local.use_custom_domain ? 1 : 0
  name    = "testbed-gke-lb-ip"
  project = var.project_id
}

resource "google_compute_managed_ssl_certificate" "gke_lb" {
  count   = local.use_custom_domain ? 1 : 0
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

resource "kubernetes_ingress_v1" "testbed_gke" {
  count = local.use_custom_domain ? 1 : 0

  metadata {
    name      = "testbed-gke-ingress"
    namespace = "default"
    annotations = {
      "kubernetes.io/ingress.class"                  = "gce"
      "kubernetes.io/ingress.global-static-ip-name"  = google_compute_global_address.gke_lb[0].name
      "networking.gke.io/pre-shared-cert"            = google_compute_managed_ssl_certificate.gke_lb[0].name
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
