"""Authenticated server metrics and numeric-only per-generation usage logs."""
import asyncio
import json
import logging
import httpx
from fastapi import HTTPException
from fastapi.responses import Response

log = logging.getLogger("uvicorn.error")


def record_usage(usage, rid, public_model, backend_model):
    if not isinstance(usage, dict):
        return
    counts = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
              if type(usage.get(k)) is int and usage[k] >= 0}
    if counts:
        log.info(json.dumps({"event": "generation_usage", "request_id": rid,
            "profile": public_model, "backend_model": backend_model, **counts}))


async def backend_metrics(app, principal):
    principal.ensure_current()
    if not principal.backend_metrics:
        raise HTTPException(403, "Backend metrics access denied")
    try:
        async with asyncio.timeout(10):
            async with app.state.client.stream("GET", app.state.url[:-3] + "/metrics", timeout=10) as upstream:
                upstream.raise_for_status()
                raw = bytearray()
                async for chunk in upstream.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise ValueError("Oversized metrics")
            # Expose vLLM engine statistics only, not process/python metrics.
            lines = [line for line in raw.decode("utf-8").splitlines()
                if line.startswith(("vllm:", "# HELP vllm:", "# TYPE vllm:"))]
            if not lines:
                raise ValueError("No vLLM metrics")
            principal.ensure_current()
            return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4",
                headers={"Cache-Control": "no-store", "X-Harness-Metrics-Scope": "backend-wide"})
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise HTTPException(503, "vLLM metrics unavailable") from None


def attach_accounting(result, state):
    """Keep upstream usage intact; identify extra summary work separately."""
    usage = result.get("usage")
    if not isinstance(usage, dict) or not state.get("summary_calls"):
        return
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int:
        return
    summary_prompt = state.get("summary_prompt_tokens", 0)
    summary_completion = state.get("summary_completion_tokens", 0)
    result["harness_usage"] = {"generation_prompt_tokens": prompt,
        "generation_completion_tokens": completion, "summary_prompt_tokens": summary_prompt,
        "summary_completion_tokens": summary_completion,
        "total_tokens_including_compaction": prompt + completion + summary_prompt + summary_completion}
