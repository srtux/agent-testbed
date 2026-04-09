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

# GKE Workload Identity GSA for Inventory MCP
resource "google_service_account" "inventory_mcp_gsa" {
  account_id   = "inventory-mcp-gsa"
  display_name = "Inventory MCP GSA for Workload Identity"
}

# Separate GSA for Hotel and Car Rental agents on GKE
resource "google_service_account" "gke_agents_gsa" {
  account_id   = "gke-agents-gsa"
  display_name = "GKE Agents GSA for Hotel and Car Rental Specialists"
}

# --- Per-service Cloud Run invocation bindings (least privilege) ---

# FlightSpecialist (Cloud Run) -> WeatherSpecialist (Cloud Run)
resource "google_cloud_run_v2_service_iam_member" "flight_specialist_invoke_weather" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.weather_specialist.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.flight_specialist.email}"
}

# GKE Agents GSA -> Profile_MCP (Cloud Run) for CarRentalSpecialist
resource "google_cloud_run_v2_service_iam_member" "gke_agents_invoke_profile_mcp" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.profile_mcp.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.gke_agents_gsa.email}"
}

# Inventory MCP GSA -> Profile_MCP (Cloud Run) — kept for backward compatibility
resource "google_cloud_run_v2_service_iam_member" "gke_gsa_invoke_profile_mcp" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.profile_mcp.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.inventory_mcp_gsa.email}"
}

# --- Agent Engine -> Cloud Run invocation bindings ---
# Vertex AI Agent Engine uses the default compute service account
# (PROJECT_NUMBER-compute@developer.gserviceaccount.com) to call downstream services.

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  agent_engine_sa = "${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}

# Agent Engine -> FlightSpecialist (Cloud Run)
resource "google_cloud_run_v2_service_iam_member" "agent_engine_invoke_flight" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.flight_specialist.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.agent_engine_sa}"
}

# Agent Engine -> WeatherSpecialist (Cloud Run)
resource "google_cloud_run_v2_service_iam_member" "agent_engine_invoke_weather" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.weather_specialist.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.agent_engine_sa}"
}

# Agent Engine -> Profile_MCP (Cloud Run)
resource "google_cloud_run_v2_service_iam_member" "agent_engine_invoke_profile_mcp" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.profile_mcp.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.agent_engine_sa}"
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

# --- Cloud Run Service Account Trace Permissions ---
# Cloud Run SAs need cloudtrace.agent to export OTLP spans

resource "google_project_iam_member" "flight_specialist_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.flight_specialist.email}"
}

resource "google_project_iam_member" "weather_specialist_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.weather_specialist.email}"
}

resource "google_project_iam_member" "profile_mcp_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.profile_mcp.email}"
}

# --- Agent Engine Service Account Trace Permissions ---
resource "google_project_iam_member" "agent_engine_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${local.agent_engine_sa}"
}

# --- GKE Workload Identity Configuration ---

# Inventory MCP GSA permissions
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
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/inventory-mcp-ksa]"
}

# GKE Agents GSA permissions (for HotelSpecialist and CarRentalSpecialist)
resource "google_project_iam_member" "gke_agents_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.gke_agents_gsa.email}"
}

resource "google_project_iam_member" "gke_agents_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.gke_agents_gsa.email}"
}

resource "google_service_account_iam_member" "gke_agents_workload_identity" {
  service_account_id = google_service_account.gke_agents_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/gke-agents-ksa]"
}

# --- Vertex AI Service Agent Permissions ---
# Vertex AI Service Agent needs compute.networkAdmin to update the PSC network attachment
# to accept connections when creating the PSC interface.
resource "google_project_iam_member" "vertex_service_agent_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "vertex_service_agent_dns_peer" {
  project = var.project_id
  role    = "roles/dns.peer"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "vertex_service_agent_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# resource "google_project_iam_member" "vertex_service_agent_re_trace_agent" {
#   project = var.project_id
#   role    = "roles/cloudtrace.agent"
#   member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
# }
# 
# resource "google_project_iam_member" "vertex_service_agent_re_network_admin" {
#   project = var.project_id
#   role    = "roles/compute.networkAdmin"
#   member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
# }
# 
# resource "google_project_iam_member" "vertex_service_agent_re_dns_peer" {
#   project = var.project_id
#   role    = "roles/dns.peer"
#   member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
# }

# --- Bucket-level permissions for Vertex AI Service Agent ---
resource "google_project_iam_member" "vertex_service_agent_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# --- Cloud Functions v2 Deployment Permissions ---
# The Cloud Functions service agent needs read access to the source bucket.
# Using bucket-level IAM as the bucket may reside in a different project.
resource "google_storage_bucket_iam_member" "gcf_admin_storage_viewer" {
  bucket = var.deploy_bucket_name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:service-${data.google_project.current.number}@gcf-admin-robot.iam.gserviceaccount.com"
}

# Cloud Functions v2 uses Cloud Build under the hood, which also needs read access to the source bucket
resource "google_storage_bucket_iam_member" "cloudbuild_storage_viewer" {
  bucket = var.deploy_bucket_name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}


