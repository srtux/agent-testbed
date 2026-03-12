# =============================================================================
# Internal Load Balancers for Cloud Run in Direct Mode
# =============================================================================

# 1. Proxy-Only Subnet (Required for Region L7 Internal Load Balancers)
# Using a range OUTSIDE 10.128.0.0/9 (Auto Subnets area)
resource "google_compute_subnetwork" "ilb_proxy_only" {
  count         = local.use_custom_domain ? 0 : 1
  name          = "ilb-proxy-only-subnet"
  ip_cidr_range = "10.0.0.0/23" # SAFE outside 10.128.0.0/9
  network       = data.google_compute_network.main.id
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
  region        = var.region
  project       = var.project_id
}

# --- Flight Specialist ILB ---

resource "google_compute_region_backend_service" "flight_specialist_ilb" {
  count                 = local.use_custom_domain ? 0 : 1
  name                  = "flight-specialist-ilb-backend"
  region                = var.region
  project               = var.project_id
  load_balancing_scheme = "INTERNAL_MANAGED"
  protocol              = "HTTP"

  backend {
    group          = google_compute_region_network_endpoint_group.flight_specialist[0].id
    balancing_mode = "UTILIZATION" # Try forcing UTILIZATION to avoid CONNECTION default bug
  }
}

resource "google_compute_region_url_map" "flight_specialist_ilb" {
  count           = local.use_custom_domain ? 0 : 1
  name            = "flight-specialist-ilb-map"
  region          = var.region
  project         = var.project_id
  default_service = google_compute_region_backend_service.flight_specialist_ilb[0].id
}

resource "google_compute_region_target_http_proxy" "flight_specialist_ilb" {
  count   = local.use_custom_domain ? 0 : 1
  name    = "flight-specialist-ilb-proxy"
  region  = var.region
  project = var.project_id
  url_map = google_compute_region_url_map.flight_specialist_ilb[0].id
}

resource "google_compute_forwarding_rule" "flight_specialist_ilb" {
  count                 = local.use_custom_domain ? 0 : 1
  name                  = "flight-specialist-ilb-rule"
  region                = var.region
  project               = var.project_id
  load_balancing_scheme = "INTERNAL_MANAGED"
  network               = data.google_compute_network.main.id
  subnetwork            = data.google_compute_subnetwork.default.id
  target                = google_compute_region_target_http_proxy.flight_specialist_ilb[0].id
  port_range            = "80"

  depends_on = [google_compute_subnetwork.ilb_proxy_only]
}

# --- Weather Specialist ILB ---

resource "google_compute_region_backend_service" "weather_specialist_ilb" {
  count                 = local.use_custom_domain ? 0 : 1
  name                  = "weather-specialist-ilb-backend"
  region                = var.region
  project               = var.project_id
  load_balancing_scheme = "INTERNAL_MANAGED"
  protocol              = "HTTP"

  backend {
    group          = google_compute_region_network_endpoint_group.weather_specialist[0].id
    balancing_mode = "UTILIZATION"
  }
}

resource "google_compute_region_url_map" "weather_specialist_ilb" {
  count           = local.use_custom_domain ? 0 : 1
  name            = "weather-specialist-ilb-map"
  region          = var.region
  project         = var.project_id
  default_service = google_compute_region_backend_service.weather_specialist_ilb[0].id
}

resource "google_compute_region_target_http_proxy" "weather_specialist_ilb" {
  count   = local.use_custom_domain ? 0 : 1
  name    = "weather-specialist-ilb-proxy"
  region  = var.region
  project = var.project_id
  url_map = google_compute_region_url_map.weather_specialist_ilb[0].id
}

resource "google_compute_forwarding_rule" "weather_specialist_ilb" {
  count                 = local.use_custom_domain ? 0 : 1
  name                  = "weather-specialist-ilb-rule"
  region                = var.region
  project               = var.project_id
  load_balancing_scheme = "INTERNAL_MANAGED"
  network               = data.google_compute_network.main.id
  subnetwork            = data.google_compute_subnetwork.default.id
  target                = google_compute_region_target_http_proxy.weather_specialist_ilb[0].id
  port_range            = "80"

  depends_on = [google_compute_subnetwork.ilb_proxy_only]
}

# --- Profile MCP ILB ---

resource "google_compute_region_backend_service" "profile_mcp_ilb" {
  count                 = local.use_custom_domain ? 0 : 1
  name                  = "profile-mcp-ilb-backend"
  region                = var.region
  project               = var.project_id
  load_balancing_scheme = "INTERNAL_MANAGED"
  protocol              = "HTTP"

  backend {
    group          = google_compute_region_network_endpoint_group.profile_mcp[0].id
    balancing_mode = "UTILIZATION"
  }
}

resource "google_compute_region_url_map" "profile_mcp_ilb" {
  count           = local.use_custom_domain ? 0 : 1
  name            = "profile-mcp-ilb-map"
  region          = var.region
  project         = var.project_id
  default_service = google_compute_region_backend_service.profile_mcp_ilb[0].id
}

resource "google_compute_region_target_http_proxy" "profile_mcp_ilb" {
  count   = local.use_custom_domain ? 0 : 1
  name    = "profile-mcp-ilb-proxy"
  region  = var.region
  project = var.project_id
  url_map = google_compute_region_url_map.profile_mcp_ilb[0].id
}

resource "google_compute_forwarding_rule" "profile_mcp_ilb" {
  count                 = local.use_custom_domain ? 0 : 1
  name                  = "profile-mcp-ilb-rule"
  region                = var.region
  project               = var.project_id
  load_balancing_scheme = "INTERNAL_MANAGED"
  network               = data.google_compute_network.main.id
  subnetwork            = data.google_compute_subnetwork.default.id
  target                = google_compute_region_target_http_proxy.profile_mcp_ilb[0].id
  port_range            = "80"

  depends_on = [google_compute_subnetwork.ilb_proxy_only]
}
