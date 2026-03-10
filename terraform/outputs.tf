output "flight_specialist_url" {
  value = google_cloud_run_v2_service.flight_specialist.uri
}

output "weather_specialist_url" {
  value = google_cloud_run_v2_service.weather_specialist.uri
}

output "profile_mcp_url" {
  value = google_cloud_run_v2_service.profile_mcp.uri
}

output "traffic_generator_url" {
  value = google_cloudfunctions2_function.traffic_generator.url
}

output "test_runner_sa" {
  value       = google_service_account.test_runner.email
  description = "Service Account email to use for running the integration tests."
}
