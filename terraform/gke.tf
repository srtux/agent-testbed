# --- Hotel Specialist ---

resource "kubernetes_deployment" "hotel_specialist" {
  metadata {
    name = "gke-hotel-specialist"
    labels = {
      app = "gke-hotel-specialist"
    }
  }

  spec {
    replicas = 1
    selector {
      match_labels = {
        app = "gke-hotel-specialist"
      }
    }
    template {
      metadata {
        labels = {
          app = "gke-hotel-specialist"
        }
      }
      spec {
        service_account_name = "inventory-mcp-ksah"
        container {
          name  = "hotel-specialist"
          image = var.hotel_specialist_image

          port {
            container_port = 8080
          }

          env {
            name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
            value = "gen_ai_latest_experimental"
          }
          env {
            name  = "INVENTORY_MCP_URL"
            value = "http://gke-inventory-mcp-service/sse"
          }
          env {
            name  = "CAR_RENTAL_SPECIALIST_URL"
            value = "http://gke-car-rental-service/chat"
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "512Mi"
            }
            limits = {
              cpu    = "1"
              memory = "1Gi"
            }
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 10
            period_seconds        = 10
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 15
            period_seconds        = 20
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "hotel_specialist" {
  metadata {
    name = "gke-hotel-specialist-service"
    annotations = local.use_custom_domain ? {
      "cloud.google.com/neg" = jsonencode({ ingress = true })
    } : {}
  }
  spec {
    selector = {
      app = "gke-hotel-specialist"
    }
    port {
      port        = 80
      target_port = 8080
    }
    type = local.use_custom_domain ? "ClusterIP" : "LoadBalancer"
  }
}

# --- Car Rental Specialist ---

resource "kubernetes_deployment" "car_rental_specialist" {
  metadata {
    name = "gke-car-rental"
    labels = {
      app = "gke-car-rental"
    }
  }

  spec {
    replicas = 1
    selector {
      match_labels = {
        app = "gke-car-rental"
      }
    }
    template {
      metadata {
        labels = {
          app = "gke-car-rental"
        }
      }
      spec {
        service_account_name = "inventory-mcp-ksah"
        container {
          name  = "car-rental-specialist"
          image = var.car_rental_specialist_image

          port {
            container_port = 8080
          }

          env {
            name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
            value = "gen_ai_latest_experimental"
          }
          env {
            name  = "PROFILE_MCP_URL"
            value = "${local.profile_mcp_url}/sse"
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "512Mi"
            }
            limits = {
              cpu    = "1"
              memory = "1Gi"
            }
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 10
            period_seconds        = 10
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 15
            period_seconds        = 20
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "car_rental_specialist" {
  metadata {
    name = "gke-car-rental-service"
    annotations = local.use_custom_domain ? {
      "cloud.google.com/neg" = jsonencode({ ingress = true })
    } : {}
  }
  spec {
    selector = {
      app = "gke-car-rental"
    }
    port {
      port        = 80
      target_port = 8080
    }
    type = local.use_custom_domain ? "ClusterIP" : "LoadBalancer"
  }
}

# --- Inventory MCP ---

resource "kubernetes_deployment" "inventory_mcp" {
  metadata {
    name = "gke-inventory-mcp"
    labels = {
      app = "gke-inventory-mcp"
    }
  }

  spec {
    replicas = 1
    selector {
      match_labels = {
        app = "gke-inventory-mcp"
      }
    }
    template {
      metadata {
        labels = {
          app = "gke-inventory-mcp"
        }
      }
      spec {
        service_account_name = "inventory-mcp-ksah"
        container {
          name  = "inventory-mcp"
          image = var.inventory_mcp_image

          port {
            container_port = 8080
          }

          env {
            name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
            value = "gen_ai_latest_experimental"
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "500m"
              memory = "512Mi"
            }
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 10
            period_seconds        = 10
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 15
            period_seconds        = 20
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "inventory_mcp" {
  metadata {
    name = "gke-inventory-mcp-service"
    annotations = local.use_custom_domain ? {
      "cloud.google.com/neg" = jsonencode({ ingress = true })
    } : {}
  }
  spec {
    selector = {
      app = "gke-inventory-mcp"
    }
    port {
      port        = 80
      target_port = 8080
    }
    type = local.use_custom_domain ? "ClusterIP" : "LoadBalancer"
  }
}

# Ensure the KSA exists
resource "kubernetes_service_account" "inventory_mcp_ksah" {
  metadata {
    name      = "inventory-mcp-ksah"
    namespace = "default"
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.inventory_mcp_gsa.email
    }
  }
  depends_on = [
    google_service_account_iam_member.inventory_mcp_workload_identity
  ]
}
