# =============================================================================
# Network Attachment for Vertex AI Reasoning Engine (PSC-I Egress)
# =============================================================================

# Lookup the existing pre-managed default subnetwork
data "google_compute_subnetwork" "default" {
  name   = "default"
  region = var.region
}

# Declarative allocation for the PSC-I anchor point
resource "google_compute_network_attachment" "reasoning_engine" {
  name                  = "reasoning-engine-attachment"
  region                = var.region
  subnetworks           = [data.google_compute_subnetwork.default.self_link]
  connection_preference = "ACCEPT_AUTOMATIC"
  project               = var.project_id
}
