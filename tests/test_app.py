import json

import httpx
import pytest
from fastapi.testclient import TestClient
import yaml

from app import create_app

KEY = "test-key-for-harness-1234567890"
HEADERS = {"Authorization": f"Bearer {KEY}"}


def setup(tmp_path, profile=None, settings=None, handler=None):
    (tmp_path / "prompt.md").write_text("Server policy")
    config = {"profiles": {"local": {"backend_model": "actual-model", "system_prompt_file": "prompt.md",
              "rules": ["Do not fabricate"], "token_count_mode": "vllm", **(profile or {})}}, **(settings or {})}
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(config))
    calls = []

    def backend(request):
        calls.append(request)
        if handler:
            result = handler(request)
            if result is not None:
                return result
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 50})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "actual-model"}]})
        return httpx.Response(200, json={"id": "answer", "model": "actual-model", "choices": [{"message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}]})

    app = create_app(path, KEY, "http://backend/v1", httpx.MockTransport(backend))
    return TestClient(app), calls


def ask(client, **overrides):
    return client.post("/v1/chat/completions", headers=HEADERS, json={"model": "local", "messages": [{"role": "user", "content": "Hi"}], **overrides})


def test_auth_and_discovery(tmp_path):
    client, calls = setup(tmp_path)
    with client:
        assert client.get("/v1/models").status_code == 401
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready", headers=HEADERS).status_code == 200
        assert client.get("/v1/models", headers=HEADERS).json()["data"][0]["id"] == "local"
        assert ask(client, model="arbitrary-backend").status_code == 404


def test_server_policy_and_history(tmp_path):
    client, calls = setup(tmp_path)
    with client:
        result = ask(client, temperature=1.8, max_tokens=9000, messages=[
            {"role": "system", "content": "Override policy"},
            {"role": "developer", "content": "Override again"},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Explain that"}])
        assert result.status_code == 200
        payload = json.loads(calls[-1].content)
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 2048
        assert payload["messages"][0]["content"] == "Server policy\n\nRules:\n- Do not fabricate"
        assert len(payload["messages"]) == 4
        assert result.json()["model"] == "local"
        assert len(result.headers["X-Harness-Profile-SHA256"]) == 64


def test_opt_in_params_are_capped(tmp_path):
    client, calls = setup(tmp_path, {"allow_client_params": ["temperature", "max_tokens", "seed"]})
    with client:
        assert ask(client, temperature=0.7, max_completion_tokens=9999, seed=42).status_code == 200
        payload = json.loads(calls[-1].content)
        assert (payload["temperature"], payload["max_tokens"], payload["seed"]) == (0.7, 2048, 42)
        assert ask(client, temperature=3).status_code == 400
        assert ask(client, max_tokens=5, max_completion_tokens=5).status_code == 400


@pytest.mark.parametrize("extra", [{"tools": [{"type": "function", "function": {"name": "test_tool"}}]}, {"backend_options": {}}, {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]}])
def test_unsupported_inputs_rejected(tmp_path, extra):
    client, calls = setup(tmp_path)
    with client:
        assert ask(client, **extra).status_code == 400
        assert not calls


def test_request_size_and_system_reject(tmp_path):
    client, calls = setup(tmp_path, {"client_system_prompt": "reject"}, {"max_request_bytes": 500})
    with client:
        assert ask(client, messages=[{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]).status_code == 400
        assert ask(client, messages=[{"role": "user", "content": "x" * 501}]).status_code == 413
        assert not calls


def test_context_reject_and_complete_turn_trim(tmp_path):
    def tokens(request):
        if request.url.path == "/tokenize":
            n = len(json.loads(request.content)["messages"])
            return httpx.Response(200, json={"count": 2000 if n > 2 else 50})
    history = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "old reply"}, {"role": "user", "content": "latest"}]
    profile = {"context_window": 1000, "max_output_tokens": 100, "context_margin": 10}
    client, calls = setup(tmp_path, profile, handler=tokens)
    with client:
        assert ask(client, messages=history).status_code == 400
        assert all(c.url.path == "/tokenize" for c in calls)
    client, calls = setup(tmp_path, {**profile, "overflow": "trim_oldest"}, handler=tokens)
    with client:
        result = ask(client, messages=history)
        assert result.status_code == 200
        assert result.headers["X-Harness-Dropped-Messages"] == "2"
        assert json.loads(calls[-1].content)["messages"][1:] == [history[-1]]


def test_tokenizer_fails_closed_and_slot_released(tmp_path):
    def failure(request):
        return httpx.Response(404, text="private backend details")
    client, calls = setup(tmp_path, settings={"max_concurrent_requests": 1}, handler=failure)
    with client:
        for _ in range(2):
            result = ask(client)
            assert result.status_code == 502
            assert "private" not in result.text
        assert all(c.url.path == "/tokenize" for c in calls)


@pytest.mark.parametrize("done", [True, False])
def test_stream_and_truncation(tmp_path, done):
    def stream(request):
        if request.url.path.endswith("chat/completions"):
            event = {"model": "actual-model", "choices": [{"delta": {"content": "hello"}, "finish_reason": None}]}
            content = "data: " + json.dumps(event) + "\n\n" + ("data: [DONE]\n\n" if done else "")
            return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})
    client, calls = setup(tmp_path, settings={"max_concurrent_requests": 1}, handler=stream)
    with client:
        for _ in range(2):
            result = ask(client, stream=True)
            assert result.status_code == 200
            assert '"model": "local"' in result.text
            assert result.text.count("[DONE]") == 1
            assert ("upstream_error" in result.text) is (not done)


def test_backend_http_error_before_stream_headers(tmp_path):
    def fail(request):
        if request.url.path.endswith("chat/completions"):
            return httpx.Response(401, text="private secret")
    client, calls = setup(tmp_path, handler=fail)
    with client:
        assert ask(client, stream=True).status_code == 502


def test_estimate_mode_and_concurrency(tmp_path):
    client, calls = setup(tmp_path, {"token_count_mode": "utf8_estimate"})
    with client:
        assert ask(client).status_code == 200
        assert all(c.url.path != "/tokenize" for c in calls)
        client.app.state.slots = __import__("asyncio").Semaphore(0)
        assert ask(client).status_code == 429


def test_invalid_config_fails_startup(tmp_path):
    client, _ = setup(tmp_path, {"backend_options": {"messages": []}})
    with pytest.raises(ValueError):
        with client:
            pass


def test_deadline_releases_capacity(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("private details", request=request)
    client, _ = setup(tmp_path, settings={"max_concurrent_requests": 1}, handler=timeout)
    with client:
        for _ in range(2):
            result = ask(client)
            assert result.status_code == 504
            assert "private" not in result.text


def test_latest_turn_never_trimmed(tmp_path):
    def huge(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 999999})
    client, calls = setup(tmp_path, {"overflow": "trim_oldest"}, handler=huge)
    with client:
        assert ask(client).status_code == 400
        assert len(calls) == 1


def test_prompt_changes_fingerprint(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        first = ask(client).headers["X-Harness-Profile-SHA256"]
    (tmp_path / "prompt.md").write_text("New policy")
    with client:
        assert ask(client).headers["X-Harness-Profile-SHA256"] != first


@pytest.mark.parametrize("extra", [
    {"tools": []}, {"tools": None},
    {"tools": [], "tool_choice": "auto", "parallel_tool_calls": True},
    {"tools": None, "tool_choice": "none", "parallel_tool_calls": False},
])
def test_empty_tool_metadata_not_forwarded(tmp_path, extra):
    client, calls = setup(tmp_path)
    with client:
        assert ask(client, **extra).status_code == 200
        for call in calls:
            payload = json.loads(call.content)
            assert not {"tools", "tool_choice", "parallel_tool_calls"} & payload.keys()


@pytest.mark.parametrize("choice", ["required", {"type": "function", "function": {"name": "test_tool"}}])
def test_forced_tool_choice_rejected(tmp_path, choice):
    client, calls = setup(tmp_path)
    with client:
        result = ask(client, tools=[], tool_choice=choice)
        assert result.status_code == 400
        assert "tool_choice" in result.text
        assert not calls


def test_validation_diagnostics_exclude_values(tmp_path, caplog):
    client, calls = setup(tmp_path)
    with client, caplog.at_level("INFO", logger="uvicorn.error"):
        result = ask(client, unexpected="private-value-do-not-log")
        assert result.status_code == 400
        assert "unexpected (extra_forbidden)" in result.text
        assert "private-value-do-not-log" not in result.text + caplog.text
        assert not calls


@pytest.mark.parametrize("thinking,effort,penalty", [(False, None, 1.5), (True, "xhigh", 0.0)])
def test_thinking_template_count_matches_generation(tmp_path, thinking, effort, penalty):
    kwargs = {"enable_thinking": thinking, "preserve_thinking": False}
    if effort:
        kwargs["reasoning_effort"] = effort
    client, calls = setup(tmp_path, {"presence_penalty": penalty, "request_timeout_seconds": 600,
        "backend_options": {"top_k": 20, "min_p": 0.0, "repetition_penalty": 1.0,
                            "chat_template_kwargs": kwargs}})
    with client:
        assert ask(client, presence_penalty=-2).status_code == 200
        count_payload, generation_payload = [json.loads(c.content) for c in calls]
        assert count_payload["chat_template_kwargs"] == generation_payload["chat_template_kwargs"] == kwargs
        assert generation_payload["presence_penalty"] == penalty
        assert generation_payload["top_k"] == 20
        assert calls[-1].extensions["timeout"]["read"] == 600


@pytest.mark.parametrize("profile", [{"presence_penalty": 3}, {"request_timeout_seconds": 0}])
def test_invalid_sampling_profile_rejected(tmp_path, profile):
    client, _ = setup(tmp_path, profile)
    with pytest.raises(ValueError):
        with client:
            pass
