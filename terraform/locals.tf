locals {
  # --- Cloud Run service URLs ---
  # Use Internal Load Balancer IP addresses directly
  flight_specialist_url  = "http://${google_compute_forwarding_rule.flight_specialist_ilb.ip_address}"
  weather_specialist_url = "http://${google_compute_forwarding_rule.weather_specialist_ilb.ip_address}"
  profile_mcp_url       = "http://${google_compute_forwarding_rule.profile_mcp_ilb.ip_address}"

  # --- GKE service URLs ---
  # Use LoadBalancer external IPs directly
  hotel_specialist_url    = try("http://${kubernetes_service.hotel_specialist.status[0].load_balancer[0].ingress[0].ip}", "")
  car_rental_url          = try("http://${kubernetes_service.car_rental_specialist.status[0].load_balancer[0].ingress[0].ip}", "")
  inventory_mcp_url       = try("http://${kubernetes_service.inventory_mcp.status[0].load_balancer[0].ingress[0].ip}", "")
}
