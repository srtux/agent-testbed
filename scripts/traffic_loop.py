"""
Continuous traffic generator for the Agent Testbed.

Sends randomized travel requests to the RootRouter at a configurable interval,
generating a steady stream of distributed traces across all agents and MCP servers.

Usage:
    # Against local services (default):
    uv run traffic-loop

    # Against a deployed endpoint:
    ROOT_ROUTER_URL=https://my-router.a.run.app/chat uv run traffic-loop

    # Custom interval and burst size:
    uv run traffic-loop --interval 30 --burst 3

    # Run for a fixed duration (seconds):
    uv run traffic-loop --duration 300
"""

import argparse
import json
import logging
import os
import random
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("traffic_loop")

# Diverse prompt pool covering different agent paths and tool invocations
PROMPTS = [
    # Full waterfall: RootRouter -> Flight -> Hotel -> Car -> Weather -> Booking
    "I need to travel to SFO for a tech conference next Tuesday through Friday. Book everything including hotel, car, and check the weather.",
    "My flight to Tokyo was canceled. Read my customer profile, check the weather in Tokyo, find a new flight, book a hotel, and secure a rental car. Summarize everything.",
    "I need an emergency re-booking for London due to weather. Check my profile, find a flight and hotel, make sure I have a rental car, and confirm.",
    "My trip to Paris is in jeopardy because of a missed connection. Grab my preferences, verify Paris weather, book a new flight and adjust my hotel and car rental.",
    "Plan a complete business trip to JFK area for next week. I need flights, a luxury hotel, and a rental car. Check the weather forecast too.",
    "Book a round trip to LAX departing Monday returning Thursday. Include hotel and car rental. Check my loyalty tier for discounts.",
    # Flight-focused (exercises FlightSpecialist + SeatSelector sub-agent)
    "Find me a flight to SFO departing next Wednesday. I prefer window seats.",
    "What flights are available to JFK next Friday? I need business class.",
    # Hotel-focused (exercises HotelSpecialist -> Inventory MCP -> CarRental)
    "I need a hotel in San Francisco for 3 nights starting next Tuesday.",
    # Weather-focused (exercises WeatherSpecialist -> Inventory MCP)
    "What's the weather like in Tokyo next week? I want packing suggestions.",
    # Profile-focused (exercises Profile MCP)
    "Check my travel profile and suggest a trip based on my preferences.",
    # Cancellation/modification (exercises IntentClassifier sub-agent)
    "I need to cancel my upcoming trip to London.",
    "Can I modify my hotel booking in Paris to extend by 2 nights?",
]


def _resolve_endpoint(url: str) -> str:
    """Ensure the URL has the /chat path."""
    if url and not url.startswith("projects/") and not url.endswith("/chat"):
        return url.rstrip("/") + "/chat"
    return url


def send_request(endpoint: str, request_num: int, timeout: float = 120.0) -> dict:
    """Send a single traffic request and return result metadata."""
    import requests

    prompt = random.choice(PROMPTS)
    user_id = f"traffic_{random.randint(1000, 9999)}"
    start = time.monotonic()

    result = {
        "request_num": request_num,
        "user_id": user_id,
        "prompt_preview": prompt[:80] + "...",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        if endpoint.startswith("projects/"):
            import vertexai
            from vertexai import agent_engines

            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
            vertexai.init(project=project_id, location=location)

            ae = agent_engines.AgentEngine(endpoint)
            # stream_query is recommended for Reasoning Engines
            response = ae.stream_query(user_id=user_id, message=prompt)

            final_response = ""
            for event in response:
                is_dict = isinstance(event, dict)
                content = (
                    event.get("content") if is_dict else getattr(event, "content", None)
                )
                if content:
                    parts = (
                        content.get("parts", [])
                        if is_dict
                        else getattr(content, "parts", [])
                    )
                    for part in parts:
                        text = (
                            part.get("text") if is_dict else getattr(part, "text", None)
                        )
                        if text:
                            final_response += text
                        if is_dict and "function_call" in part:
                            final_response += (
                                f"Tool call: {part['function_call']['name']}\n"
                            )

            elapsed = time.monotonic() - start
            result["status_code"] = 200
            result["elapsed_seconds"] = round(elapsed, 2)
            result["status"] = "success"
            result["summary_length"] = len(final_response)
            logger.info(
                f"[#{request_num}] OK in {elapsed:.1f}s | user={user_id} | summary={len(final_response)} chars"
            )
        else:
            resp = requests.post(
                endpoint,
                json={"user_id": user_id, "prompt": prompt},
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            result["status_code"] = resp.status_code
            result["elapsed_seconds"] = round(elapsed, 2)

            if resp.status_code == 200:
                data = resp.json()
                summary = data.get("orchestration_summary", "")
                result["status"] = "success"
                result["summary_length"] = len(summary)
                logger.info(
                    f"[#{request_num}] OK in {elapsed:.1f}s | user={user_id} | summary={len(summary)} chars"
                )
            else:
                result["status"] = "http_error"
                result["error"] = resp.text[:200]
                logger.warning(
                    f"[#{request_num}] HTTP {resp.status_code} in {elapsed:.1f}s | {resp.text[:100]}"
                )

    except Exception as e:
        elapsed = time.monotonic() - start
        result["status"] = "exception"
        result["error"] = str(e)[:200]
        result["elapsed_seconds"] = round(elapsed, 2)
        logger.error(f"[#{request_num}] FAILED in {elapsed:.1f}s | {e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Continuous traffic generator for Agent Testbed"
    )
    parser.add_argument(
        "--interval", type=int, default=60, help="Seconds between bursts (default: 60)"
    )
    parser.add_argument(
        "--burst", type=int, default=1, help="Requests per burst (default: 1)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Run for N seconds then stop (0 = indefinite)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--output", type=str, default="", help="Path to write JSON results log"
    )
    args = parser.parse_args()

    endpoint = os.environ.get("ROOT_ROUTER_URL", "http://localhost:8080/chat")
    endpoint = _resolve_endpoint(endpoint)

    logger.info(f"Starting continuous traffic to: {endpoint}")
    logger.info(
        f"Interval: {args.interval}s | Burst size: {args.burst} | Duration: {'indefinite' if args.duration == 0 else f'{args.duration}s'}"
    )

    # Graceful shutdown
    stop_event = threading.Event()

    def handle_signal(sig, frame):
        logger.info("Received shutdown signal, finishing current burst...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    results = []
    request_counter = 0
    start_time = time.monotonic()

    while not stop_event.is_set():
        # Check duration limit
        if args.duration > 0 and (time.monotonic() - start_time) >= args.duration:
            logger.info(f"Duration limit ({args.duration}s) reached. Stopping.")
            break

        # Send burst
        burst_results = []
        if args.burst > 1:
            with ThreadPoolExecutor(max_workers=min(args.burst, 5)) as pool:
                futures = []
                for _ in range(args.burst):
                    request_counter += 1
                    futures.append(
                        pool.submit(
                            send_request, endpoint, request_counter, args.timeout
                        )
                    )
                for future in as_completed(futures):
                    burst_results.append(future.result())
        else:
            request_counter += 1
            burst_results.append(send_request(endpoint, request_counter, args.timeout))

        results.extend(burst_results)

        # Summary for this burst
        ok = sum(1 for r in burst_results if r["status"] == "success")
        fail = len(burst_results) - ok
        logger.info(
            f"Burst complete: {ok} ok, {fail} failed | Total requests: {request_counter}"
        )

        # Write results if output path specified
        if args.output:
            try:
                with open(args.output, "w") as f:
                    json.dump(
                        {"total_requests": request_counter, "results": results},
                        f,
                        indent=2,
                    )
            except Exception as e:
                logger.warning(f"Failed to write results: {e}")

        # Wait for next interval (interruptible)
        if not stop_event.wait(timeout=args.interval):
            continue  # timeout expired, loop again
        else:
            break  # stop_event was set

    # Final summary
    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    elapsed_total = time.monotonic() - start_time
    logger.info(
        f"Traffic loop complete: {success}/{total} succeeded in {elapsed_total:.0f}s"
    )

    if args.output and results:
        with open(args.output, "w") as f:
            json.dump(
                {"total_requests": total, "success": success, "results": results},
                f,
                indent=2,
            )
        logger.info(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
