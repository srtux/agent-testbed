data "google_compute_zones" "available" {
  project = var.project_id
  region  = var.region
}

resource "google_compute_instance" "bastion" {
  name         = "testbed-bastion"
  machine_type = "e2-micro"
  zone         = data.google_compute_zones.available.names[0]
  project      = var.project_id

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 10
    }
  }

  network_interface {
    network    = data.google_container_cluster.primary.network
    subnetwork = data.google_container_cluster.primary.subnetwork
    # No access_config = no public IP (secure)
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  tags = ["bastion"]

  depends_on = [data.google_container_cluster.primary]
}

resource "google_compute_firewall" "iap_ssh" {
  name    = "testbed-allow-iap-ssh-to-bastion"
  network = data.google_container_cluster.primary.network
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["bastion"]
}
