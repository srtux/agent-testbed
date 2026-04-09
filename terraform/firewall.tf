resource "google_compute_firewall" "allow_psc_to_gke" {
  name    = "allow-psc-to-gke"
  network = data.google_compute_network.main.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["80", "8080"]
  }

  source_ranges = ["10.10.0.0/24"] # PSC subnet
}
