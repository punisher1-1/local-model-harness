#!/usr/bin/env python3
"""Read a backend-wide metrics snapshot through the authenticated harness."""
import argparse
import os
import sys
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", action="store_true", help="Show all vLLM Prometheus families")
    args = parser.parse_args()
    token = os.getenv("HARNESS_TOKEN") or os.getenv("HARNESS_API_KEY")
    if not token:
        parser.error("Set HARNESS_TOKEN or HARNESS_API_KEY")
    try:
        with httpx.Client(timeout=12, trust_env=False, follow_redirects=False) as client:
            response = client.get("http://127.0.0.1:8200/v1/backend/metrics",
                headers={"Authorization": "Bearer " + token})
            response.raise_for_status()
        if args.raw:
            print(response.text, end="")
        else:
            print("Backend-wide snapshot; KV-cache usage is a fraction (0.25 = 25%).")
            names = {"vllm:prompt_tokens_total", "vllm:generation_tokens_total",
                     "vllm:kv_cache_usage_perc", "vllm:num_requests_running", "vllm:num_requests_waiting"}
            for line in response.text.splitlines():
                if line.split("{")[0].split(" ")[0] in names:
                    print(line)
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "unavailable"
        print("Metrics request failed: " + str(status), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
