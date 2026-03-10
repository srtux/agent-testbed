# --- Service Accounts ---

resource "google_service_account" "flight_specialist" {
  account_id   = "flight-specialist"
  display_name = "FlightSpecialist Service Account"
}

resource "google_service_account" "weather_specialist" {
  account_id   = "weather-specialist"
  display_name = "WeatherSpecialist Service Account"
}

resource "google_service_account" "profile_mcp" {
  account_id   = "profile-mcp"
  display_name = "Profile_MCP Service Account"
}

resource "google_service_account" "test_runner" {
  account_id   = "travel-test-runner"
  display_name = "Travel Concierge Test Runner"
}

# GKE Workload Identity GSA
resource "google_service_account" "inventory_mcp_gsa" {
  account_id   = "inventory-mcp-gsa"
  display_name = "Inventory MCP GSA for Workload Identity"
}

# --- Per-service Cloud Run invocation bindings (least privilege) ---

resource "google_cloud_run_v2_service_iam_member" "flight_specialist_invoke_hotel" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.weather_specialist.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.flight_specialist.email}"
}

resource "google_cloud_run_v2_service_iam_member" "flight_specialist_invoke_weather" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.weather_specialist.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.flight_specialist.email}"
}

resource "google_cloud_run_v2_service_iam_member" "weather_specialist_invoke_profile_mcp" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.profile_mcp.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.weather_specialist.email}"
}

resource "google_cloud_run_v2_service_iam_member" "gke_gsa_invoke_profile_mcp" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.profile_mcp.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.inventory_mcp_gsa.email}"
}

# --- Test Runner Permissions ---

resource "google_project_iam_member" "test_runner_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.test_runner.email}"
}

resource "google_project_iam_member" "test_runner_cf_invoker" {
  project = var.project_id
  role    = "roles/cloudfunctions.invoker"
  member  = "serviceAccount:${google_service_account.test_runner.email}"
}

resource "google_project_iam_member" "test_runner_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.test_runner.email}"
}

# --- GKE Workload Identity Configuration ---

resource "google_project_iam_member" "inventory_mcp_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.inventory_mcp_gsa.email}"
}

resource "google_project_iam_member" "inventory_mcp_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.inventory_mcp_gsa.email}"
}

resource "google_service_account_iam_member" "inventory_mcp_workload_identity" {
  service_account_id = google_service_account.inventory_mcp_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/inventory-mcp-ksah]"
}
