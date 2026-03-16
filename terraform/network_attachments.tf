# =============================================================================
# Network Attachment for Vertex AI Reasoning Engine (PSC-I Egress)
# =============================================================================

# Lookup the existing pre-managed default subnetwork (kept for fallback or reference)
data "google_compute_subnetwork" "default" {
  name   = "default"
  region = var.region
}

# Dedicated subnet for Vertex AI Agent Engine PSC Egress anchoring
resource "google_compute_subnetwork" "psc_subnet" {
  name                     = "reasoning-engine-psc-subnet"
  network                  = "default" # Use the default network
  ip_cidr_range            = "10.10.0.0/24"
  region                   = var.region
  private_ip_google_access = true
  project                  = var.project_id
}

# Declarative allocation for the PSC-I anchor point (using dedicated subnet)
resource "google_compute_network_attachment" "reasoning_engine" {
  name                  = "reasoning-engine-attachment"
  region                = var.region
  subnetworks           = [google_compute_subnetwork.psc_subnet.self_link]
  connection_preference = "ACCEPT_AUTOMATIC"
  project               = var.project_id
}
