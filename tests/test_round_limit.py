import json

import pytest

from code_mcp import CodeStore
from test_app import setup, ask
from test_research import completion
from test_code_mcp import env  # noqa: F401  (fixture)

PROFILE = {"client_tools": True, "mcp_servers": ["code"], "max_output_tokens": 20000,
           "context_window": 40000, "thinking_budget_ratio": 0.5}


def run(tmp_path, monkeypatch, replies, profile=None, **request):
    async def fake(self, name, args):
        return {"stdout": "ok\n", "stderr": "", "exit_code": 0, "timed_out": False}
    monkeypatch.setattr(CodeStore, "call", fake)
    bodies = []

    def backend(r):
        if r.url.path != "/v1/chat/completions":
            return None
        bodies.append(json.loads(r.content))
        return replies[len(bodies) - 1]
    client, _ = setup(tmp_path, {**PROFILE, **(profile or {})}, handler=backend)
    with client:
        return ask(client, **request), bodies


def test_round_cap_defaults_to_8192(tmp_path, env, monkeypatch):  # noqa: F811
    r, bodies = run(tmp_path, monkeypatch, [completion({"role": "assistant", "content": "Done."})])
    assert r.status_code == 200 and bodies[0]["max_tokens"] == 8192 and "tools" in bodies[0]


@pytest.mark.parametrize("stream", [False, True])
def test_cut_off_tool_round_is_retried_once_without_tools(tmp_path, env, monkeypatch, caplog, stream):  # noqa: F811
    replies = [completion({"role": "assistant", "content": "PARTIAL"}, "length", tokens=12000),
               completion({"role": "assistant", "content": "FINAL ANSWER"}, tokens=900)]
    with caplog.at_level("INFO", logger="uvicorn.error"):
        r, bodies = run(tmp_path, monkeypatch, replies, {"mcp_round_output_tokens": 12000}, stream=stream)
    assert r.status_code == 200 and "FINAL ANSWER" in r.text
    first, retry = bodies
    assert first["max_tokens"] == 12000 and first["thinking_token_budget"] == 6000 and "tools" in first
    # The cut-off text is discarded; the retry has tools off and the rest of the allowance.
    assert "tools" not in retry and retry["tool_choice"] == "none" and retry["max_tokens"] == 8000
    assert retry["thinking_token_budget"] == 2000
    assert "PARTIAL" not in json.dumps(retry["messages"]) and "cut off" in retry["messages"][-1]["content"]
    assert "retrying once without tools" in r.text
    event = next(json.loads(m) for m in caplog.messages if '"research_round_retry"' in m)
    assert event["round_limit"] == 12000 and event["remaining"] == 8000
    if not stream:
        assert r.json()["choices"][0]["message"]["content"].startswith("FINAL ANSWER")


def test_cut_off_retry_still_fails(tmp_path, env, monkeypatch):  # noqa: F811
    replies = [completion({"role": "assistant", "content": "PARTIAL"}, "length", tokens=8192),
               completion({"role": "assistant", "content": "STILL PARTIAL"}, "length", tokens=11808)]
    r, bodies = run(tmp_path, monkeypatch, replies)
    assert r.status_code == 400 and "hit its output limit" in r.text and len(bodies) == 2


def test_round_cap_bounds(tmp_path):
    for value in (512, 70000):
        with pytest.raises(Exception, match="mcp_round_output_tokens"):
            setup(tmp_path, {**PROFILE, "mcp_round_output_tokens": value})[0].__enter__()
