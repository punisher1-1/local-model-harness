"""Exercise the shipped configurations, rather than test-only profile fixtures."""
import json
from pathlib import Path
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient
import yaml

from app import create_app, Settings

ROOT = Path(__file__).resolve().parents[1]
KEY = "release-test-key-not-a-real-secret"
HEADERS = {"Authorization": f"Bearer {KEY}"}


def public_source(tmp_path, config_name):
    """Stage only shared prompts, excluding any ignored personal prompt."""
    shutil.copy(ROOT / config_name, tmp_path / config_name)
    (tmp_path / "prompts").mkdir()
    for name in ("assistant.md.example", "research.md"):
        shutil.copy(ROOT / "prompts" / name, tmp_path / "prompts" / name)
    shutil.copytree(ROOT / "demo_notes", tmp_path / "demo_notes")
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    return tmp_path / config_name


def backend(calls):
    def respond(request):
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{
                "id": "local-model", "max_model_len": 131072,
            }]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 50})
        assert request.url.path == "/v1/chat/completions"
        if json.loads(request.content)["stream"]:
            event = {"choices": [{"index": 0, "delta": {"content": "Hello"},
                                  "finish_reason": "stop"}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "Hello"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 1, "total_tokens": 51},
        })
    return respond


@pytest.mark.parametrize("config_name", ["profiles.yaml", "profiles.portable.yaml"])
@pytest.mark.parametrize("stream", [False, True])
def test_public_configs_start_and_chat_without_memory(tmp_path, monkeypatch, config_name, stream):
    for variable in ("HARNESS_IDENTITY_CONFIG", "HARNESS_MEMORY_CONFIG", "GEN_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    path = public_source(tmp_path, config_name)
    calls = []
    with TestClient(create_app(path, KEY, "http://backend/v1",
                              httpx.MockTransport(backend(calls)))) as client:
        assert client.get("/v1/models").status_code == 401
        assert client.get("/health/ready", headers=HEADERS).status_code == 200
        assert client.app.state.memory is None
        models = client.get("/v1/models", headers=HEADERS).json()["data"]
        assert len(models) == (6 if config_name == "profiles.yaml" else 1)
        for model in models:
            result = client.post("/v1/chat/completions", headers=HEADERS, json={
                "model": model["id"], "stream": stream,
                "messages": [{"role": "user", "content": "Hello"}],
            })
            assert result.status_code == 200, result.text
            assert "Hello" in result.text
            assert result.headers["X-Harness-Memory-Status"] == "disabled"
            if stream:
                assert result.text.count("[DONE]") == 1
        assert client.get("/v1/memories", headers=HEADERS).status_code == 503
    if config_name == "profiles.portable.yaml":
        assert all(request.url.path != "/tokenize" for request in calls)


def test_documented_memory_enable_and_disable_config():
    config = yaml.safe_load((ROOT / "profiles.yaml").read_text())
    for profile in config["profiles"].values():
        profile["memory_recall"]["enabled"] = True
        profile["chat_memory"] = not bool(profile.get("research"))
    Settings.model_validate(config)
    for profile in config["profiles"].values():
        profile["chat_memory"] = False
        profile["memory_recall"]["enabled"] = False
    Settings.model_validate(config)
