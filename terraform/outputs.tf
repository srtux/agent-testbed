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

output "traffic_generator_url" {
  value = google_cloudfunctions2_function.traffic_generator.url
}

output "test_runner_sa" {
  value       = google_service_account.test_runner.email
  description = "Service Account email to use for running the integration tests."
}

output "mode" {
  value       = local.use_custom_domain ? "custom_domain" : "direct"
  description = "Deployment mode: custom_domain (LBs + SSL) or direct (native URLs + LoadBalancer IPs)."
}
