# Application Architecture & service Mesh Guide

This document covers the overall design logic, component breakdowns, and call paths running cross-service links inside the **agent-testbed**.

---

## 🏗️ Core Architecture Overview

The application demonstrates a **Hybrid Serverless & Kubernetes Topology** stress-testing multi-agent and MCP chains transparently.

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

---

## 🧩 1. Components & Roles

| Service Type | Service Name | Runtime | Role |
| :--- | :--- | :--- | :--- |
| **Agent** (ADK) | `RootRouter` | Agent Engine | Top-level gateway routing prompt links addressing downstreams. |
| **Agent** (ADK) | `BookingOrchestrator` | Agent Engine | Coordinates backend specialists transparently. |
| **Agent** (HTTP) | `FlightSpecialist` | Cloud Run | Handles Flight lookup chains with conditional routing logic. |
| **Agent** (HTTP) | `HotelSpecialist` | GKE | Stateful logic scaling addressing lodging requests. |
| **MCP** (SSE) | `Profile_MCP` | Cloud Run | Serves User Profile context payloads. |
| **MCP** (SSE) | `Inventory_MCP` | GKE | Serves Inventory/Stock contextual state payloads. |

---

## 📞 2. Component Call Graph & Protocols

The chain is structured to exercise multiple recursive traversal loops.

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

### 🔗 Protocols Leveraged:
1.  **Agent-to-Agent (A2A)**: HTTP/JSON passing standard W3C `traceparent` context hooks ensuring telemetry headers link correctly.
2.  **Agent-to-MCP (MCP)**: FastMCP over SSE connection addressing payloads positionally. Context propagation manually injects headers inside the generic `_meta` bag envelope transparently.

---

## 🔒 3. Environment Configs (In-VPC Mesh)

Full topology diagrams supporting strict routing without internet escapes leverage **Private Service Connect interfaces (PSC-I)** allocated positional bounds making Agent Engine workloads egress into VPC subnetwork edge maps cleanly:

1.  **Agent Egress Path**: Reasoning engine creates dedicate endpoints addressing `*.run.app` lookup coordinates fully internally.
2.  **Compute Works**: Cloud Run leverages direct VPC Egress addressing Internal Load Balancers bounds positionally binding GKE nodes securely.

See `docs/NETWORKING.md` for full detailed VPC edge resolution.
