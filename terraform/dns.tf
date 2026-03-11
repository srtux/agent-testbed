data "google_compute_network" "main" {
  name    = var.vpc_name != "" ? var.vpc_name : element(split("/", data.google_container_cluster.primary.network), length(split("/", data.google_container_cluster.primary.network)) - 1)
  project = var.project_id
}

resource "google_dns_managed_zone" "run_app_internal" {
  name        = "run-app-internal"
  dns_name    = "a.run.app."
  description = "Internal DNS zone for Cloud Run .a.run.app routing"
  project     = var.project_id
  visibility  = "private"

  private_visibility_config {
    networks {
      network_url = data.google_compute_network.main.id
    }
  }
}

resource "google_dns_record_set" "run_app_a" {
  name         = "*.a.run.app."
  managed_zone = google_dns_managed_zone.run_app_internal.name
  type         = "A"
  ttl          = 300
  project      = var.project_id

  rrdatas = [
    "199.36.153.8",
    "199.36.153.9",
    "199.36.153.10",
    "199.36.153.11"
  ]
}
