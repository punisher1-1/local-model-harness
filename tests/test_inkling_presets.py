"""Every tracked profile is ready for Inkling 2 Mini, and Qwen's settings are unchanged."""
import asyncio
from pathlib import Path

import pytest
import yaml

from app import Settings
from backend import resolve_profile

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = Settings.model_validate(yaml.safe_load((ROOT / "profiles.yaml").read_text()))
QWEN_PROFILES = [n for n, p in SETTINGS.profiles.items() if "qwen3.8-27b" in p.backend_presets]
# The levels Inkling's chat template accepts; any other name makes the template raise.
INKLING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}


def resolve(profile, model):
    return asyncio.run(resolve_profile(None, profile, {model: {"id": model, "max_model_len": 131072}}))


@pytest.mark.parametrize("name", QWEN_PROFILES)
def test_every_qwen_profile_has_an_inkling_preset(name):
    assert "inkling-2-mini" in SETTINGS.profiles[name].backend_presets


@pytest.mark.parametrize("name", QWEN_PROFILES)
def test_inkling_gets_only_settings_it_understands(name):
    base = SETTINGS.profiles[name]
    ink = resolve(base, "inkling-2-mini")
    qwen = resolve(base, "qwen3.8-27b")
    assert ink.backend_model == "inkling-2-mini"
    assert ink.temperature == 1.0 and ink.top_p is None and ink.presence_penalty is None
    assert set(ink.backend_options) <= {"chat_template_kwargs", "thinking_token_budget"}
    assert ink.backend_options["chat_template_kwargs"] == {"reasoning_effort": qwen.backend_options["chat_template_kwargs"]["reasoning_effort"]}
    assert ink.backend_options["chat_template_kwargs"]["reasoning_effort"] in INKLING_EFFORTS
    # Same thinking cap and context window as the profile's Qwen preset.
    assert ink.backend_options.get("thinking_token_budget") == qwen.backend_options.get("thinking_token_budget")
    assert ink.thinking_budget_ratio == qwen.thinking_budget_ratio
    assert ink.context_window == qwen.context_window


@pytest.mark.parametrize("name", QWEN_PROFILES)
def test_qwen_resolution_still_uses_its_own_preset(name):
    qwen = resolve(SETTINGS.profiles[name], "qwen3.8-27b")
    assert qwen.backend_options["top_k"] == 20
    assert qwen.backend_options["chat_template_kwargs"]["enable_thinking"] is True
