# --- Cloud Run service URLs (native) ---

output "flight_specialist_url" {
  value = google_cloud_run_v2_service.flight_specialist.uri
}

output "weather_specialist_url" {
  value = google_cloud_run_v2_service.weather_specialist.uri
}

output "profile_mcp_url" {
  value = google_cloud_run_v2_service.profile_mcp.uri
}

# --- Stable custom domain URLs ---

output "flight_specialist_custom_url" {
  value       = "https://flight-specialist.${var.custom_domain}"
  description = "Stable custom domain URL for FlightSpecialist"
}

output "weather_specialist_custom_url" {
  value       = "https://weather-specialist.${var.custom_domain}"
  description = "Stable custom domain URL for WeatherSpecialist"
}

output "profile_mcp_custom_url" {
  value       = "https://profile-mcp.${var.custom_domain}"
  description = "Stable custom domain URL for Profile MCP"
}

output "hotel_specialist_custom_url" {
  value       = "https://hotel-specialist.${var.custom_domain}"
  description = "Stable custom domain URL for HotelSpecialist (GKE via NEG)"
}

output "car_rental_custom_url" {
  value       = "https://car-rental.${var.custom_domain}"
  description = "Stable custom domain URL for CarRentalSpecialist (GKE via NEG)"
}

output "inventory_mcp_custom_url" {
  value       = "https://inventory-mcp.${var.custom_domain}"
  description = "Stable custom domain URL for Inventory MCP (GKE via NEG)"
}

# --- Load Balancer IPs (for DNS configuration) ---

output "cloud_run_lb_ip" {
  value       = google_compute_global_address.cloud_run_lb.address
  description = "Global IP for the Cloud Run LB. Create A records for flight-specialist/weather-specialist/profile-mcp subdomains."
}

output "gke_lb_ip" {
  value       = google_compute_global_address.gke_lb.address
  description = "Global IP for the GKE Ingress LB. Create A records for hotel-specialist/car-rental/inventory-mcp subdomains."
}

# --- Other ---

output "traffic_generator_url" {
  value = google_cloudfunctions2_function.traffic_generator.url
}

output "test_runner_sa" {
  value       = google_service_account.test_runner.email
  description = "Service Account email to use for running the integration tests."
}
