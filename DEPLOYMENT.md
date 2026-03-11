# Deployment Guide

This guide covers deploying the Agent Testbed across **Agent Engine**, **GKE**, and **Cloud Run** with full A2A and MCP protocol support.

## Architecture Overview

```
                    ┌──────────────────────────┐
                    │    Agent Engine (Vertex)  │
                    │  RootRouter               │
                    │  BookingOrchestrator      │
                    └──────┬───────────────┬────┘
                           │ A2A (HTTP)    │ A2A (HTTP)
              ┌────────────▼───┐     ┌─────▼──────────────┐
              │   Cloud Run    │     │       GKE          │
              │ FlightSpecial. │     │ HotelSpecialist    │
              │ WeatherSpecial.│     │ CarRentalSpecial.  │
              │ Profile_MCP    │     │ Inventory_MCP      │
              └────────────────┘     └────────────────────┘
                    │ MCP (SSE)            │ MCP (SSE)
                    └──────────────────────┘
```

**Protocols:**
- **A2A**: HTTP/JSON with W3C traceparent headers between all agents
- **MCP**: FastMCP over SSE between agents and MCP servers
- **Observability**: OpenTelemetry with Cloud Trace exporter across all environments

## Prerequisites

- GCP project with billing enabled
- GKE cluster (Standard or Autopilot)
- `gcloud`, `terraform`, `uv` CLI tools installed
- Docker (optional; falls back to Cloud Build)

## Two Deployment Modes

### Mode 1: Custom Domain (Recommended for production-like testing)

Uses a stable custom domain with HTTPS load balancers, Google-managed SSL certs, and GKE Ingress with container-native NEGs.

### Mode 2: Direct (Quick start, no domain needed)

Uses Cloud Run's native `*.run.app` URLs and GKE LoadBalancer IPs. No SSL cert provisioning wait. Best for quick iteration.

## Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required
PROJECT_ID=your-project-id
GOOGLE_CLOUD_PROJECT=your-project-id
CLUSTER_NAME=your-gke-cluster

# Optional - omit for "direct" mode
CUSTOM_DOMAIN=testbed.example.com

# Optional - defaults to ${PROJECT_ID}-tf-state
TF_STATE_BUCKET=your-project-id-tf-state
```

### 2. Create the Terraform state bucket

```bash
PROJECT_ID=$(grep PROJECT_ID .env | head -1 | cut -d= -f2)
gsutil mb -l us-central1 gs://${PROJECT_ID}-tf-state
```

### 3. Deploy

```bash
uv run deploy
```

This runs 4 phases automatically:
1. **Build** - Docker images for all 6 services (parallel)
2. **Terraform** - Provisions Cloud Run, GKE, LBs, Cloud Functions
3. **Agent Engine** - Deploys RootRouter and BookingOrchestrator to Vertex AI
4. **Re-apply** - Updates Terraform with Agent Engine URLs

### 💡 Understanding the Phase State Bridge (Portability)

Because some resources depend on each other cyclically (e.g., Cloud Functions need the Agent Engine address, but Agent Engine needs Terraform backend IPs deployed first), the script serializes state using **local JSON cache files**:

*   **`terraform_service_urls.json`**:
    *   *Generated after Phase 2* containing computed outputs from Terraform (the newly minted Cloud Run/GKE routes).
    *   *Consumed in Phase 3* to build self-contained `env_vars` for Agent Engine scripts so specialists find routers safely.
*   **`agent_engine_outputs.json`**:
    *   *Generated after Phase 3* containing mapped Vertex AI resourceIDs (the deployed ADK roots).
    *   *Consumed in Phase 4* to pass coordinates back into Terraform variables with final bounds.

> [!IMPORTANT]
> **These files are dynamically generated and are added to `.gitignore`.** They are strictly workspace-specific and do not need to be committed. Any engineer running the deployment loops from scratch will rebuild their state locally on launch cleanly.

### 4. (Custom domain mode only) Configure DNS


After Phase 2, the deploy script prints the required DNS records:

```
Configure DNS A records:
  flight-specialist.testbed.example.com -> <CLOUD_RUN_LB_IP>
  weather-specialist.testbed.example.com -> <CLOUD_RUN_LB_IP>
  profile-mcp.testbed.example.com        -> <CLOUD_RUN_LB_IP>
  hotel-specialist.testbed.example.com    -> <GKE_LB_IP>
  car-rental.testbed.example.com          -> <GKE_LB_IP>
  inventory-mcp.testbed.example.com       -> <GKE_LB_IP>
```

## Setting Up a Custom Domain with GCP

### Option A: Using Cloud DNS (managed DNS)

1. **Register or transfer your domain** to any registrar.

2. **Create a Cloud DNS managed zone:**

```bash
gcloud dns managed-zones create testbed-zone \
  --dns-name="testbed.example.com." \
  --description="Agent testbed DNS zone" \
  --project=$PROJECT_ID
```

3. **Update your registrar's NS records** to point to the Cloud DNS nameservers:

```bash
gcloud dns managed-zones describe testbed-zone --format="value(nameServers)"
```

4. **Add A records** after deployment (the IPs come from terraform output):

```bash
# Get the IPs
cd terraform
CLOUD_RUN_IP=$(terraform output -raw cloud_run_lb_ip)
GKE_IP=$(terraform output -raw gke_lb_ip)

# Cloud Run services
gcloud dns record-sets create flight-specialist.testbed.example.com. \
  --type=A --ttl=300 --rrdatas=$CLOUD_RUN_IP \
  --zone=testbed-zone

gcloud dns record-sets create weather-specialist.testbed.example.com. \
  --type=A --ttl=300 --rrdatas=$CLOUD_RUN_IP \
  --zone=testbed-zone

gcloud dns record-sets create profile-mcp.testbed.example.com. \
  --type=A --ttl=300 --rrdatas=$CLOUD_RUN_IP \
  --zone=testbed-zone

# GKE services
gcloud dns record-sets create hotel-specialist.testbed.example.com. \
  --type=A --ttl=300 --rrdatas=$GKE_IP \
  --zone=testbed-zone

gcloud dns record-sets create car-rental.testbed.example.com. \
  --type=A --ttl=300 --rrdatas=$GKE_IP \
  --zone=testbed-zone

gcloud dns record-sets create inventory-mcp.testbed.example.com. \
  --type=A --ttl=300 --rrdatas=$GKE_IP \
  --zone=testbed-zone
```

5. **Wait for SSL certs to provision** (15-60 minutes). Check status:

```bash
gcloud compute ssl-certificates describe testbed-cloud-run-cert --format="value(managed.status)"
gcloud compute ssl-certificates describe testbed-gke-cert --format="value(managed.status)"
```

### Option B: Using an external DNS provider

Simply create AAAA/A records at your DNS provider pointing the subdomains to the IPs printed by the deploy script.

### Option C: Using nip.io for quick testing (no domain purchase needed)

For testing only, you can use [nip.io](https://nip.io) which provides wildcard DNS:

```bash
# Set custom_domain to use nip.io with the Cloud Run LB IP
# Note: Google-managed certs won't work with nip.io, so this is HTTP-only
CUSTOM_DOMAIN=<CLOUD_RUN_LB_IP>.nip.io
```

## Direct Mode (No Custom Domain)

If you don't have a domain or want to iterate quickly:

1. **Leave `CUSTOM_DOMAIN` empty** in `.env`
2. Run `uv run deploy`
3. Cloud Run services use their native `*.run.app` URLs
4. GKE services get individual LoadBalancer external IPs
5. No SSL cert provisioning wait

**Trade-offs:**
- Cloud Run URLs are auto-generated (e.g., `https://flight-specialist-abc123-uc.a.run.app`)
- GKE services are exposed over HTTP (not HTTPS) via LoadBalancer IPs
- URLs change if services are recreated

## Running Tests

```bash
# Local testing (requires all services running locally)
uv run run-all  # Start all services
uv run test-local

# Remote testing (against deployed services)
uv run test-remote
```

## Service Map

| Service | Environment | Protocol | Port (local) |
|---------|-------------|----------|-------------|
| RootRouter | Agent Engine | A2A | 8080 |
| BookingOrchestrator | Agent Engine | A2A | 8081 |
| FlightSpecialist | Cloud Run | A2A | 8082 |
| WeatherSpecialist | Cloud Run | A2A | 8083 |
| HotelSpecialist | GKE | A2A | 8084 |
| CarRentalSpecialist | GKE | A2A | 8085 |
| Profile_MCP | Cloud Run | MCP/SSE | 8090 |
| Inventory_MCP | GKE | MCP/SSE | 8091 |
| TrafficGenerator | Cloud Function | HTTP | - |

## Call Graph

```
TrafficGenerator -> RootRouter (Agent Engine)
  └─> FlightSpecialist (Cloud Run) [A2A]
        ├─> HotelSpecialist (GKE) [A2A]
        │     ├─> Inventory_MCP (GKE) [MCP/SSE]
        │     └─> CarRentalSpecialist (GKE) [A2A]
        │           └─> Profile_MCP (Cloud Run) [MCP/SSE]
        └─> WeatherSpecialist (Cloud Run) [A2A]
              ├─> Inventory_MCP (GKE) [MCP/SSE]
              └─> BookingOrchestrator (Agent Engine) [A2A]
                    └─> Inventory_MCP (GKE) [MCP/SSE]
```

## Terraform Structure

| File | Purpose |
|------|---------|
| `main.tf` | Provider config, GCS backend, GKE data source |
| `variables.tf` | All input variables |
| `locals.tf` | Computed service URLs (adapts to deployment mode) |
| `cloud_run.tf` | 3 Cloud Run services |
| `gke.tf` | 3 GKE deployments + services + KSA |
| `networking.tf` | LBs, NEGs, SSL certs, Ingress (conditional on custom_domain) |
| `iam.tf` | Service accounts, per-service IAM bindings, Workload Identity |
| `functions.tf` | Traffic generator Cloud Function |
| `outputs.tf` | Service URLs, LB IPs, deployment mode |
| `vertex_agents.tf` | Notes on Agent Engine deployment approach |

## 🌐 Infrastructure & Networking Deep Dive

The deployment utilizes a Hybrid Serverless & Kubernetes topology designed to stress both types of endpoints.

### 1. compute primitives
* **Agent Engine (Vertex AI):** Hosts logic scripts directly inside Google's sandboxed Reasoning Environment with access to Gemini LLM execution pathways safely.
* **Cloud Run:** Drives stateless components (`FlightSpecialist`, `WeatherSpecialist`, `Profile_MCP`). Built using Standard container sets on serverless NEG binds.
* **GKE (Google Kubernetes Engine):** Hosts heavier internal state loads (`HotelSpecialist`, `CarRental`, `Inventory_MCP`). Scaled linearly behind Standard Load-Balancing nodes.

### 2. Networking Routing (Mode Discrepency)

#### **🔵 Mode 1: Custom Domain Mode (Production Grade)**
Uses global Host-Based HTTPS routing with conditional certificate hooks:
*   **For Cloud Run:** Global External HTTPS Load Balancer maps requests via **Serverless NEGs**.
    *   Example: `flight-specialist.${CUSTOM_DOMAIN}` binds to the serverless NEG addressing the underlying run template node routing accurately.
*   **For GKE:** Google Compute **Ingress controller (`gce`)** acts as the gateway wrapper mapped into static targets utilizing `kubernetes_ingress_v1` mappings directly at ports `80`.

#### **🟢 Mode 2: Direct Mode (Standard/Quick)**
For debugging quickly without waiting on static proxy binding Certificate provision times:
*   **Cloud Run:** Exposes standard default `*.run.app` naked URLs natively.
*   **GKE Services:** Operates with service descriptions set positionally to `type = "LoadBalancer"`. This spawns independent target IP gateways for each pod cluster bundle autonomously to speed iteration loops.

### 3. Service Mesh bindings (In-Cluster vs cross-cluster)
*   **Within GKE:** Services like `HotelSpecialist` address `Inventory_MCP` utilizing standard cluster DNS pointers (e.g., `http://gke-inventory-mcp-service/sse`) completely avoiding load balancer delays.
*   **Cross-Cluster calls:** Cloud Run components or Agent Engine run loops evaluate against full absolute endpoints (extracted through Terraform state bridge JSON caches locally).


## Troubleshooting

**SSL cert stuck in PROVISIONING:**
DNS must resolve to the LB IP before Google can issue the cert. Verify with:
```bash
dig +short flight-specialist.testbed.example.com
```

**GKE pods not ready:**
All services expose `/health` endpoints. Check:
```bash
kubectl get pods -l app=gke-hotel-specialist
kubectl logs -l app=gke-hotel-specialist
```

**Agent Engine can't reach GKE services:**
In custom domain mode, ensure DNS and SSL certs are fully provisioned.
In direct mode, ensure GKE LoadBalancer IPs are accessible (check firewall rules).

**Cloud Run 403 errors:**
IAM bindings are per-service. Check that the calling service account has `roles/run.invoker` on the target service:
```bash
gcloud run services get-iam-policy flight-specialist --region=us-central1
```

## 📈 AppHub Application Setup

The application resources are grouped together into a cohesive view in **Google Cloud AppHub** (`testbed-app1` in the `global` region). This helps track endpoints, metadata, and dependencies natively.

### 1. Structure
Within AppHub, components are split across:
*   **Services**: Exposes the actual connection URL endpoints (Cloud Run and GKE standard Service LoadBalancers).
*   **Workloads**: The underlying backing compute nodes/pods running the loads (GKE Deployments and Vertex AI Reasoning Engine allocations).

### 2. Management (Terraform)
To maintain declarative reproducibility, resource registration can be managed seamlessly combining your endpoints via `@google-beta` **discovered metadata lookups**:

See `/terraform/apphub.tf` for uncommented usage:
```hcl
data "google_apphub_discovered_service" "weather_specialist" {
  location    = "us-central1"
  service_uri = "//run.googleapis.com/projects/${var.project_id}/locations/${var.region}/services/weather-specialist"
}

resource "google_apphub_service" "weather_specialist" {
   application_id      = "testbed-app1"
   location            = "global"
   service_id          = "weather-specialist"
   discovered_service   = data.google_apphub_discovered_service.weather_specialist.name
}
```
If you integrate manual creates later back into Terraform apply cycles, run `terraform import` corresponding nodes strictly to prevent creation item duplicate collisions.

