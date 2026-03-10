terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.45.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.45.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35.0"
    }
  }

  backend "gcs" {
    bucket = "" # Set via -backend-config="bucket=<PROJECT_ID>-tf-state" during terraform init
    prefix = "agent-testbed"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_client_config" "default" {}

data "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region
}

provider "kubernetes" {
  host                   = "https://${data.google_container_cluster.primary.endpoint}"
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(data.google_container_cluster.primary.master_auth[0].cluster_ca_certificate)
}
