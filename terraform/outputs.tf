# --- Cloud Run service URLs (native) ---

output "flight_specialist_url" {
  value       = local.flight_specialist_url
  description = "URL for FlightSpecialist (custom domain or native Cloud Run)"
}

output "weather_specialist_url" {
  value       = local.weather_specialist_url
  description = "URL for WeatherSpecialist (custom domain or native Cloud Run)"
}

output "profile_mcp_url" {
  value       = local.profile_mcp_url
  description = "URL for Profile MCP (custom domain or native Cloud Run)"
}

# --- GKE service URLs ---

output "hotel_specialist_url" {
  value       = local.hotel_specialist_url
  description = "URL for HotelSpecialist (custom domain or GKE LoadBalancer IP)"
}

output "car_rental_url" {
  value       = local.car_rental_url
  description = "URL for CarRentalSpecialist (custom domain or GKE LoadBalancer IP)"
}

output "inventory_mcp_url" {
  value       = local.inventory_mcp_url
  description = "URL for Inventory MCP (custom domain or GKE LoadBalancer IP)"
}

output "flight_specialist_audience" {
  value       = google_cloud_run_v2_service.flight_specialist.uri
  description = "Audience for FlightSpecialist OIDC tokens"
}

output "weather_specialist_audience" {
  value       = google_cloud_run_v2_service.weather_specialist.uri
  description = "Audience for WeatherSpecialist OIDC tokens"
}

output "profile_mcp_audience" {
  value       = google_cloud_run_v2_service.profile_mcp.uri
  description = "Audience for Profile MCP OIDC tokens"
}

# --- Load Balancer IPs (only with custom domain) ---

output "cloud_run_lb_ip" {
  value       = local.use_custom_domain ? google_compute_global_address.cloud_run_lb[0].address : ""
  description = "Global IP for the Cloud Run LB (empty if not using custom domain)."
}

output "gke_lb_ip" {
  value       = local.use_custom_domain ? google_compute_global_address.gke_lb[0].address : ""
  description = "Global IP for the GKE Ingress LB (empty if not using custom domain)."
}

# --- Other ---

# output "traffic_generator_url" {
#   value = google_cloudfunctions2_function.traffic_generator.url
# }

output "test_runner_sa" {
  value       = google_service_account.test_runner.email
  description = "Service Account email to use for running the integration tests."
}

output "mode" {
  value       = local.use_custom_domain ? "custom_domain" : "direct"
  description = "Deployment mode: custom_domain (LBs + SSL) or direct (native URLs + LoadBalancer IPs)."
}

# output "bastion_ssh_command" {
#   value       = "gcloud compute ssh ${google_compute_instance.bastion.name} --tunnel-through-iap --zone ${google_compute_instance.bastion.zone} --project ${var.project_id} -- -D 8888 -N"
#   description = "Command to establish a SOCKS5 proxy tunnel to the Bastion host."
# }

output "psc_network_attachment" {
  value       = google_compute_network_attachment.reasoning_engine.id
  description = "The PSC Network Attachment ID for Agent Engine egress"
}

output "vpc_name" {
  value       = element(split("/", data.google_container_cluster.primary.network), length(split("/", data.google_container_cluster.primary.network)) - 1)
  description = "The short name of the VPC network"
}

output "vpc_project_id" {
  value       = var.project_id
  description = "Project ID containing the VPC"
}
