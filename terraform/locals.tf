locals {
  use_custom_domain = var.custom_domain != ""

  # --- Cloud Run service URLs ---
  # With custom domain: use the LB-backed subdomain
  # Without: use Cloud Run's native *.run.app URI
  flight_specialist_url  = local.use_custom_domain ? "https://flight-specialist.${var.custom_domain}" : "http://${google_compute_forwarding_rule.flight_specialist_ilb[0].ip_address}"
  weather_specialist_url = local.use_custom_domain ? "https://weather-specialist.${var.custom_domain}" : "http://${google_compute_forwarding_rule.weather_specialist_ilb[0].ip_address}"
  profile_mcp_url       = local.use_custom_domain ? "https://profile-mcp.${var.custom_domain}" : "http://${google_compute_forwarding_rule.profile_mcp_ilb[0].ip_address}"

  # --- GKE service URLs ---
  # With custom domain: use the Ingress-backed subdomain
  # Without: use LoadBalancer external IPs directly
  hotel_specialist_url    = local.use_custom_domain ? "https://hotel-specialist.${var.custom_domain}" : try("http://${kubernetes_service.hotel_specialist.status[0].load_balancer[0].ingress[0].ip}", "")
  car_rental_url          = local.use_custom_domain ? "https://car-rental.${var.custom_domain}" : try("http://${kubernetes_service.car_rental_specialist.status[0].load_balancer[0].ingress[0].ip}", "")
  inventory_mcp_url       = local.use_custom_domain ? "https://inventory-mcp.${var.custom_domain}" : try("http://${kubernetes_service.inventory_mcp.status[0].load_balancer[0].ingress[0].ip}", "")
}
