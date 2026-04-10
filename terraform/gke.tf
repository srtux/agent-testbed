# --- Hotel Specialist ---

resource "kubernetes_deployment" "hotel_specialist" {
  timeouts {
    create = "20m"
    update = "20m"
  }
  metadata {
    name = "gke-hotel-specialist"
    labels = {
      app     = "gke-hotel-specialist"
      testbed = "my-agent-testbed"
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
          app                                 = "gke-hotel-specialist"
          "registry.gke.io/functional-type" = "AGENT"
          "iam.gke.io/identity-type"      = "agent_identity"
        }
        annotations = {
          "iam.gke.io/identity" = "spiffe://${var.project_id}.svc.id.goog/*"
        }
      }
      spec {
        service_account_name = "gke-agents-ksa"
        
        node_selector = {
          "iam.gke.io/gke-metadata-server-enabled" = "true"
        }



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
            name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
            value = "https://telemetry.googleapis.com"
          }
          env {
            name  = "OTEL_SERVICE_NAME"
            value = "hotel-specialist"
          }
          env {
            name  = "GOOGLE_CLOUD_PROJECT"
            value = var.project_id
          }
          env {
            name  = "GOOGLE_GENAI_USE_VERTEXAI"
            value = "true"
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
    labels = {
      testbed = "my-agent-testbed"
    }
    annotations = local.use_custom_domain ? {
      "cloud.google.com/neg" = jsonencode({ ingress = true })
    } : {
      "cloud.google.com/load-balancer-type" = "Internal"
    }
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
  timeouts {
    create = "20m"
    update = "20m"
  }
  metadata {
    name = "gke-car-rental"
    labels = {
      app     = "gke-car-rental"
      testbed = "my-agent-testbed"
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
          app                                 = "gke-car-rental"
          "registry.gke.io/functional-type" = "AGENT"
          "iam.gke.io/identity-type"      = "agent_identity"
        }
        annotations = {
          "iam.gke.io/identity" = "spiffe://${var.project_id}.svc.id.goog/*"
        }
      }
      spec {
        service_account_name = "gke-agents-ksa"
        
        node_selector = {
          "iam.gke.io/gke-metadata-server-enabled" = "true"
        }



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
            name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
            value = "https://telemetry.googleapis.com"
          }
          env {
            name  = "OTEL_SERVICE_NAME"
            value = "car-rental-specialist"
          }
          env {
            name  = "GOOGLE_CLOUD_PROJECT"
            value = var.project_id
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
    labels = {
      testbed = "my-agent-testbed"
    }
    annotations = local.use_custom_domain ? {
      "cloud.google.com/neg" = jsonencode({ ingress = true })
    } : {
      "cloud.google.com/load-balancer-type" = "Internal"
    }
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
  timeouts {
    create = "20m"
    update = "20m"
  }
  metadata {
    name = "gke-inventory-mcp"
    labels = {
      app     = "gke-inventory-mcp"
      testbed = "my-agent-testbed"
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
          app                                 = "gke-inventory-mcp"
          "registry.gke.io/functional-type" = "MCP_SERVER"
          "iam.gke.io/identity-type"      = "agent_identity"
        }
        annotations = {
          "iam.gke.io/identity" = "spiffe://agents.global.org-$${ORGNUM}.system.id.goog/*"
        }
      }
      spec {
        service_account_name = "inventory-mcp-ksa"
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
          env {
            name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
            value = "https://telemetry.googleapis.com"
          }
          env {
            name  = "OTEL_SERVICE_NAME"
            value = "inventory-mcp"
          }
          env {
            name  = "GOOGLE_CLOUD_PROJECT"
            value = var.project_id
          }
          env {
            name  = "OTEL_LOG_LEVEL"
            value = "debug"
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
    labels = {
      testbed = "my-agent-testbed"
    }
    annotations = local.use_custom_domain ? {
      "cloud.google.com/neg" = jsonencode({ ingress = true })
    } : {
      "cloud.google.com/load-balancer-type" = "Internal"
    }
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

# --- Kubernetes Service Accounts ---

# KSA for Inventory MCP (maps to inventory_mcp_gsa via Workload Identity)
resource "kubernetes_service_account" "inventory_mcp_ksa" {
  metadata {
    name      = "inventory-mcp-ksa"
    namespace = "default"
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.inventory_mcp_gsa.email
    }
  }
  depends_on = [
    google_service_account_iam_member.inventory_mcp_workload_identity
  ]
}

# KSA for Hotel and Car Rental agents (maps to gke_agents_gsa via Workload Identity)
resource "kubernetes_service_account" "gke_agents_ksa" {
  metadata {
    name      = "gke-agents-ksa"
    namespace = "default"
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.gke_agents_gsa.email
    }
  }
  depends_on = [
    google_service_account_iam_member.gke_agents_workload_identity
  ]
}
