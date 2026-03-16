# Continuous Load & Traffic Generator Guide

This document describes the **Traffic Generator** component found in `traffic_generator/`, detailing how it simulates continuous user loads for benchmarking tracing cascading waterfalls.

---

## 🛰️ 1. Concept: Cloud Scheduler Triggered Stress Test

The Traffic Generator mimics live users querying the system repeatedly to ensure OpenTelemetry setups export linking cascade charts comprehensively under loading pressure without memory leak drops.

*   **Mode**: Runs as a Cloud Function or Flask endpoint hook frequently triggered by Google Cloud Scheduler intervals securely.
*   **Instrumentation**: Uses `RequestsInstrumentor` wrapping the standard Python `requests` library automatically, guaranteeing every trigger session creates a fresh parent W3C `traceparent` root accurately inwards backwards.

---

## 💻 2. Execution Logic Waterfall

The generator executes a **Stateful Scenario Simulation** mimicking distinct human personas iteratively forwards securely targeting `ROOT_ROUTER_URL` forwards backwards:

### 🌟 Track 1: The Explorer (5-7 Turns)
Simulates a user who does not know where to go.
1.  **Turn 1**: Asks for suggestions based on a category (e.g., `"Suggest historic cities"`).
2.  **Turn 2**: Satisfies Authentication Gate (`My member ID is M-12345`).
3.  **Turn 3**: Locks in coordinates: `"Let's go with {destination}!"`.
4.  **Turns 4+**: Drills downstream consecutively querying Flights paths, Hotels setups, and Rental Cars updates iteratively backwards securely.

---

### 🌟 Track 2: The Decided Traveler (4-6 Turns)
Simulates a user targeting a pre-scripted world coordinates folder.
1.  **Turn 1**: `"I want to book a trip to {destination}."` (Picks random Global hubs).
2.  **Turn 2**: Satisfies Authentication Gate.
3.  **Turns 3+**: Standard consecutive iterations updates querying Flights and Hotels positionally backwards.



---

## 🚀 3. Configuration & Deployment

*   **Environment Variables**:
    *   `ROOT_ROUTER_URL`: Remote target HTTP listener endpoint (Agent Engine URL or load balancer gateway).
*   **Location**: Orchestrated continuously in background deployments maintaining telemetry visual benchmarking benchmarks securely correctly.
