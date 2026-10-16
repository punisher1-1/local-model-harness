"""Per-request model discovery and server-owned model recipes."""
import asyncio
import json
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class BackendPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    context_window: int | None = Field(default=None, gt=0)
    # Reasoning cap as a fraction of each call's output allowance (vLLM thinking_token_budget).
    thinking_budget_ratio: float | None = Field(default=None, gt=0, lt=1)
    backend_options: dict = Field(default_factory=dict)


def preset_values(preset):
    # null sampling means inherit backend defaults; null window means keep base ceiling.
    return {k: v for k, v in preset.model_dump(exclude_unset=True).items()
            if k != "context_window" or v is not None}


async def catalog(app):
    try:
        async with asyncio.timeout(10):
            async with app.state.client.stream("GET", app.state.url + "/models", timeout=10) as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        raise ValueError("Oversized model catalog")
            data = json.loads(raw)["data"]
            if not isinstance(data, list) or not data or len(data) > 128:
                raise ValueError("Invalid catalog")
            models = {}
            for item in data:
                name = item["id"]
                if not isinstance(name, str) or not 1 <= len(name) <= 256 or name in models:
                    raise ValueError("Invalid model ID")
                models[name] = item
            return models
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Backend model catalog unavailable; load a model and retry") from None


async def resolve_profile(app, profile, models=None):
    # Fixed profiles remain compatible with backends lacking discovery metadata.
    if profile.backend_model != "auto":
        preset = profile.backend_presets.get(profile.backend_model)
        if not preset:
            return profile
        config = {**profile.model_dump(), **preset_values(preset)}
        try:
            return type(profile).model_validate(config)
        except ValueError:
            raise HTTPException(503, "Invalid pinned model preset budget") from None
    models = await catalog(app) if models is None else models
    if len(models) != 1:
        raise HTTPException(503, "Automatic model selection requires exactly one advertised model; pin backend_model when multiple models or aliases are served")
    name, metadata = next(iter(models.items()))
    capacity = metadata.get("max_model_len")
    if type(capacity) is not int or capacity <= 0:
        raise HTTPException(503, "Automatic model selection requires max_model_len from vLLM; use a pinned profile with a verified context window otherwise")
    config = profile.model_dump()
    preset = profile.backend_presets.get(name)
    if preset:
        config.update(preset_values(preset))
    config["backend_model"] = name
    config["context_window"] = min(config["context_window"], capacity)
    try:
        return type(profile).model_validate(config)
    except ValueError:
        raise HTTPException(503, "Loaded model context is too small for this profile's output and summary budgets") from None


def thinking_budget(profile, max_tokens, configured=None):
    """Reasoning cap for one generation call, always leaving room for the visible answer.

    A ratio scales with the call's real output allowance (a client-lowered max_tokens,
    or one round of a tool loop); otherwise a fixed budget is clamped below it.
    """
    if profile.thinking_budget_ratio is not None:
        return min(max(1, int(max_tokens * profile.thinking_budget_ratio)), max_tokens - 1)
    if configured is not None:
        return min(configured, max_tokens - 1)
    return None


def runtime_headers(profile):
    return {"X-Harness-Backend-Model": profile.backend_model,
            "X-Harness-Context-Window": str(profile.context_window)}
