# Network Topology & Routing Guide

This document describes the networking architecture, deployment modes, and internal mesh routing for the **agent-testbed**, covering Agent Engine, Cloud Run, and GKE.

---

## 🗺️ High-Level Topology

The testbed utilizes a **Hybrid Serverless & Kubernetes** topology designed to exercise multiple routing pathways.

*   **Agent Engine (Vertex AI)**: Runs in a Google-managed tenant with secure VPC bindings.
*   **Cloud Run**: Stateless microservices.
*   **GKE**: Stateful or heavier loads scale behind Kubernetes load balancers.

---

## 🚦 1. Deployment Modes

You can deploy the infrastructure in one of two modes depending on verification speed and realism requirements.

### 🔵 Mode 1: Custom Domain (Production Grade)
Uses global Host-Based HTTPS routing with conditional certificate hooks.
*   **Cloud Run**: Global External HTTPS Load Balancer routes traffic via **Serverless NEGs**.
*   **GKE**: Google Compute **Ingress controller (`gce`)** maps static targets to port `80`.

### 🟢 Mode 2: Direct Mode (Quick Start)
Avoids certificate wait times for debugging.
*   **Cloud Run**: Exposes standard default `*.run.app` naked URLs.
*   **GKE Services**: Configured with `type = "LoadBalancer"` giving independent public/internal IPs to pods bundles.

---

## 🔒 2. Internal VPC Full-Mesh Mesh (Secure Routing)

For locked-down environments blocking external endpoints, the testbed supports full symmetric routing **inside your VPC**.

### A. Agent Engine (Vertex AI) Egress
To reach internal resources from Vertex AI, the setup utilizes **Private Service Connect interfaces (PSC-I)**.
*   **Mechanism**: The runner allocates a dedicated IP gateway into your VPC.
*   **Subnetting**: Anchored to a dedicated subnetwork (e.g., `10.10.0.0/24`) specifically for Reasoning Engine PSC Egress, separate from destination pool bundles to avoid collisions.
*   **DNS**: Dynamic DNS Scoped Peering resolves `*.run.app` inside the VPC over PGA routers natively.
*   **Firewall Rules**: Requires a firewall rule to allow traffic from the PSC subnet (e.g., `10.10.0.0/24`) to the resources in your VPC (e.g., GKE nodes on port 8080 or LoadBalancers on port 80).

### B. Cloud Run Direct VPC Egress
To allow Cloud Run to call internal GKE pods without leaving the backbone:
*   **Mechanism**: Configured with optional **Direct VPC Egress** in Terraform, routing all outbound requests into your subnet router.

### C. GKE Internal balancing
GKE services can be restricted from leasing public IPs leveraging Internal Load Balancers annotations:
`cloud.google.com/load-balancer-type = "Internal"`

---

## 💻 3. Local Development Access (Secure Tunneling)

Since microservices are often locked to internal-only ingress, developers can access endpoints using the **Bastion Host** as a gateway.

### Establishing the SOCKS5 Tunnel
Run in a background terminal:
```bash
gcloud compute ssh testbed-bastion \
    --tunnel-through-iap \
    --zone [ZONE] \
    --project [PROJECT] \
    -- -D 8888 -N
```

### Routing Traffic
*   **Curl**: `curl --proxy socks5h://localhost:8888 https://[internal-url]`
*   **Python (`httpx`)**: Requires `pip install "httpx[socks]"`. Add proxy configuration:
    ```python
    proxies = {"all://": "socks5://localhost:8888"}
    ```

---

## 🧹 Troubleshooting

*   **Timeout on SSH to Bastion**: Verify the `testbed-allow-iap-ssh-to-bastion` firewall rule exists allowing traffic from `35.235.240.0/20`.
*   **Agent Engine Creation Failed (VPC Egress)**: Verify the **Vertex AI Service Agent** holds `roles/compute.networkAdmin` and `roles/dns.peer` to bind `networkAttachments` accurately.
*   **SSL stuck PROVISIONING**: Ensure DNS record exactly resolves to the Load Balancer IP prior to Google issuer approval triggers.
