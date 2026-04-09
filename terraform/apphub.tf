# --- AppHub Application Setup ---
# Manages the overall Application structure and incorporates your items.

# 1. Create or Manage the host AppHub Application
resource "google_apphub_application" "main" {
  location = "global"
  application_id = "testbed-app1"
  project        = var.project_id
  display_name   = "Testbed Application"

  scope {
    type = "GLOBAL"
  }
}

# --- Cloud Run Services ---

data "google_apphub_discovered_service" "weather_specialist" {
  location = "global"
  service_uri = "//run.googleapis.com/projects/${var.project_id}/locations/${var.region}/services/weather-specialist"
  project     = var.project_id
}

resource "google_apphub_service" "weather_specialist" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  service_id          = "weather-specialist"
  discovered_service   = data.google_apphub_discovered_service.weather_specialist.name
  display_name        = "WeatherSpecialist"
}

data "google_apphub_discovered_service" "flight_specialist" {
  location = "global"
  service_uri = "//run.googleapis.com/projects/${var.project_id}/locations/${var.region}/services/flight-specialist"
  project     = var.project_id
}

resource "google_apphub_service" "flight_specialist" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  service_id          = "flight-specialist"
  discovered_service   = data.google_apphub_discovered_service.flight_specialist.name
  display_name        = "FlightSpecialist"
}

data "google_apphub_discovered_service" "profile_mcp" {
  location = "global"
  service_uri = "//run.googleapis.com/projects/${var.project_id}/locations/${var.region}/services/profile-mcp"
  project     = var.project_id
}

resource "google_apphub_service" "profile_mcp" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  service_id          = "profile-mcp"
  discovered_service   = data.google_apphub_discovered_service.profile_mcp.name
  display_name        = "ProfileMCP"
}

# --- GKE Services ---

data "google_apphub_discovered_service" "gke_hotel_specialist" {
  location = "global"
  service_uri = "//container.googleapis.com/projects/${var.project_id}/locations/${var.region}/clusters/${var.cluster_name}/k8s/namespaces/default/services/gke-hotel-specialist-service"
  project     = var.project_id
}

resource "google_apphub_service" "gke_hotel_specialist" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  service_id          = "gke-hotel-specialist"
  discovered_service   = data.google_apphub_discovered_service.gke_hotel_specialist.name
  display_name        = "GkeHotelSpecialist"
}

data "google_apphub_discovered_service" "gke_car_rental" {
  location = "global"
  service_uri = "//container.googleapis.com/projects/${var.project_id}/locations/${var.region}/clusters/${var.cluster_name}/k8s/namespaces/default/services/gke-car-rental-service"
  project     = var.project_id
}

resource "google_apphub_service" "gke_car_rental" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  service_id          = "gke-car-rental"
  discovered_service   = data.google_apphub_discovered_service.gke_car_rental.name
  display_name        = "GkeCarRental"
}

data "google_apphub_discovered_service" "gke_inventory_mcp" {
  location = "global"
  service_uri = "//container.googleapis.com/projects/${var.project_id}/locations/${var.region}/clusters/${var.cluster_name}/k8s/namespaces/default/services/gke-inventory-mcp-service"
  project     = var.project_id
}

resource "google_apphub_service" "gke_inventory_mcp" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  service_id          = "gke-inventory-mcp"
  discovered_service   = data.google_apphub_discovered_service.gke_inventory_mcp.name
  display_name        = "GkeInventoryMCP"
}

# --- GKE Workloads ---

data "google_apphub_discovered_workload" "gke_hotel_specialist" {
  location = "global"
  workload_uri = "//container.googleapis.com/projects/${var.project_id}/locations/${var.region}/clusters/${var.cluster_name}/k8s/namespaces/default/apps/deployments/gke-hotel-specialist"
  project      = var.project_id
}

resource "google_apphub_workload" "gke_hotel_specialist" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  workload_id         = "gke-hotel-specialist"
  discovered_workload  = data.google_apphub_discovered_workload.gke_hotel_specialist.name
  display_name        = "HotelSpecialistPod"
}

data "google_apphub_discovered_workload" "gke_car_rental" {
  location = "global"
  workload_uri = "//container.googleapis.com/projects/${var.project_id}/locations/${var.region}/clusters/${var.cluster_name}/k8s/namespaces/default/apps/deployments/gke-car-rental"
  project      = var.project_id
}

resource "google_apphub_workload" "gke_car_rental" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  workload_id         = "gke-car-rental"
  discovered_workload  = data.google_apphub_discovered_workload.gke_car_rental.name
  display_name        = "CarRentalPod"
}

data "google_apphub_discovered_workload" "gke_inventory_mcp" {
  location = "global"
  workload_uri = "//container.googleapis.com/projects/${var.project_id}/locations/${var.region}/clusters/${var.cluster_name}/k8s/namespaces/default/apps/deployments/gke-inventory-mcp"
  project      = var.project_id
}

resource "google_apphub_workload" "gke_inventory_mcp" {
  application_id      = google_apphub_application.main.application_id
  location = "global"
  workload_id         = "gke-inventory-mcp"
  discovered_workload  = data.google_apphub_discovered_workload.gke_inventory_mcp.name
  display_name        = "InventoryMcpPod"
}

# --- Vertex AI Agent Engine Workloads ---
# Require numeric IDs passed from agent state bridge to function properly if integrated.
# Example: 
#
# variable "booking_orchestrator_numeric_id" { type = string }
#
# data "google_apphub_discovered_workload" "booking_orchestrator" {
#   location = "global"
#   workload_uri = "//aiplatform.googleapis.com/projects/${var.project_id}/locations/${var.region}/reasoningEngines/${var.booking_orchestrator_numeric_id}"
#   project      = var.project_id
# }
