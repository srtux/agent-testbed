# Google Cloud App Hub Setup

This document describes the **Google Cloud App Hub** configuration and registered components for the **agent-testbed**.

App Hub is used to group related services and workloads into a cohesive view (`testbed-app1` in the `us-central1` region) to track endpoints, metadata, and dependencies natively.

---

## 🏗️ Registered Components

The following workspace resources are actively registered and **ACTIVE** in the App Hub configuration:

### ☁️ Cloud Run Services
-   **`weather-specialist`**: Coordinates weather lookups.
-   **`flight-specialist`**: Coordinates flight lookup chains.
-   **`profile-mcp`**: Serves User Profile context.

### ☸️ GKE (Google Kubernetes Engine)

| Service ID | Service Name (Kubernetes) | Workload ID (Deployment) |
| :--- | :--- | :--- |
| `gke-hotel-specialist` | `gke-hotel-specialist-service` | `gke-hotel-specialist` |
| `gke-car-rental` | `gke-car-rental-service` | `gke-car-rental` |
| `gke-inventory-mcp` | `gke-inventory-mcp-service` | `gke-inventory-mcp` |

---

## ⚠️ Omitted Components

### Agent Engine Workloads
-   `RootRouter`
-   `BookingOrchestrator`

> [!NOTE]
> Agent Engine workloads are **not registered** in App Hub. They are commented out in `/terraform/apphub.tf` because discoverability requires leveraging static numeric Reasoning Engine IDs, which are dynamically allocated during deploy script phases.

---

## 🔍 Verification & Inspection

Due to limited direct list support in the standard `gcloud apphub` CLI for attached resources, full inspection requires querying the REST API with structured `curl` iterations.

To verify registration statuses accurately, run the following loop from your authenticated workspace:

```bash
PROJECT_ID=$(gcloud config get-value project)
ACCESS_TOKEN=$(gcloud auth print-access-token)
BASE_URL="https://apphub.googleapis.com/v1/projects/$PROJECT_ID/locations/us-central1/applications/testbed-app1"

echo "=== Verifying Services ==="
for svc in weather-specialist flight-specialist profile-mcp gke-hotel-specialist gke-car-rental gke-inventory-mcp; do
  echo -n "Checking Service $svc... "
  STATUS=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/services/$svc" | grep '"state"' | sed 's/.*: "//;s/".*//')
  echo "$STATUS"
done

echo "=== Verifying Workloads ==="
for wl in gke-hotel-specialist gke-car-rental gke-inventory-mcp; do
  echo -n "Checking Workload $wl... "
  STATUS=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/workloads/$wl" | grep '"state"' | sed 's/.*: "//;s/".*//')
  echo "$STATUS"
done
```

All outputs should return `ACTIVE` confirming symmetric replication.
