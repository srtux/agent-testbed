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

# --- Service-to-Service Invocations ---

# Authorize Flight Specialist to invoke Cloud Run
resource "google_project_iam_member" "flight_specialist_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.flight_specialist.email}"
}

# Authorize Weather Specialist to invoke Cloud Run 
resource "google_project_iam_member" "weather_specialist_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.weather_specialist.email}"
}

# Authorize Profile MCP to invoke Cloud Run
resource "google_project_iam_member" "profile_mcp_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.profile_mcp.email}"
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

resource "google_service_account_iam_member" "inventory_mcp_workload_identity" {
  service_account_id = google_service_account.inventory_mcp_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/inventory-mcp-ksah]"
}
