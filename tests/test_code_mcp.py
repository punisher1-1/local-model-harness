import asyncio
import json
import os
import socket
import sys
import threading
import time

import pytest
import uvicorn

from code_mcp import CodeStore, OUTPUT_CAP
from test_app import setup, ask
from test_research import completion, tool

TOKEN = "s" * 32


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("HARNESS_CODE_MCP_URL", "http://sandbox/mcp")
    monkeypatch.setenv("HARNESS_CODE_MCP_TOKEN", TOKEN)


def test_endpoint_and_token_come_from_configuration(monkeypatch):
    monkeypatch.setenv("HARNESS_CODE_MCP_TOKEN", TOKEN)
    for url in ["", "ftp://x/mcp", "http://user:pw@x/mcp", "http://x/mcp?next=y"]:
        monkeypatch.setenv("HARNESS_CODE_MCP_URL", url)
        with pytest.raises(ValueError):
            CodeStore()
    monkeypatch.setenv("HARNESS_CODE_MCP_URL", "http://x/mcp")
    monkeypatch.setenv("HARNESS_CODE_MCP_TOKEN", "short")
    with pytest.raises(ValueError):
        CodeStore()


def test_arguments_results_and_failures_are_normalized(env, monkeypatch):
    store = CodeStore()
    replies = []

    async def fake(name, args):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(store, "call", fake)

    async def run():
        assert (await store.execute("os_system", {"code": "x"}))["error"] == "tool_not_allowed"
        assert (await store.execute("python_run", {"code": ""}))["error"] == "invalid_arguments"
        assert (await store.execute("python_run", {"code": "x", "image": "other"}))["error"] == "invalid_arguments"
        replies.append({"stdout": "y" * 50000, "stderr": "", "exit_code": 0, "timed_out": False, "extra": "dropped"})
        big = await store.execute("python_run", {"code": "print('y' * 50000)"})
        assert len(big["stdout"]) == OUTPUT_CAP and big["truncated"] and "extra" not in big
        replies.append({"error": "sandbox_busy", "detail": "upstream text"})
        assert await store.execute("python_run", {"code": "1"}) == {"error": "sandbox_busy"}
        replies.append({"error": "anything else"})
        assert await store.execute("python_run", {"code": "1"}) == {"error": "sandbox_tool_failed"}
        replies.append(OSError("refused"))
        assert await store.execute("python_run", {"code": "1"}) == {"error": "sandbox_unavailable", "reason": "error_oserror"}
    asyncio.run(run())


def test_tool_loop_runs_a_long_script_and_reports_activity(tmp_path, env, monkeypatch):
    script = "total = 0\n" + "total += 1\n" * 400 + "print(total)\n"
    calls, rounds = [], []

    async def fake(self, name, args):
        calls.append(len(args["code"]))
        return {"stdout": "400\n", "stderr": "", "exit_code": 0, "timed_out": False}
    monkeypatch.setattr(CodeStore, "call", fake)

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        body = json.loads(request.content)
        rounds.append(body)
        if len(rounds) == 1:
            assert [t["function"]["name"] for t in body["tools"]] == ["python_run"]
            assert "python_run" in body["messages"][0]["content"]
            return completion({"role": "assistant", "tool_calls": [tool("python_run", {"code": script})]}, "tool_calls")
        result = json.loads(body["messages"][-1]["content"])
        assert result["stdout"] == "400\n" and result["source"] == "python_sandbox"
        return completion({"role": "assistant", "content": "The script printed 400."})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["code"]}, handler=backend)
    with client:
        r = ask(client)
        assert r.status_code == 200 and "MCP activity (Python sandbox): python_run" in r.text
    assert calls == [len(script)] and len(script) > 2048


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_round_trip_through_the_real_sandbox_server(tmp_path, monkeypatch):
    """Harness adapter → MCP over HTTP with the bearer token → sandbox server → fake docker."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sandbox"))
    import server
    from test_sandbox_server import FAKE
    docker = tmp_path / "docker"
    docker.write_text(FAKE.format(python=sys.executable))
    docker.chmod(0o755)
    monkeypatch.setenv("SANDBOX_IMAGE_UNDER_TEST", server.IMAGE)
    monkeypatch.setattr(server, "DOCKER", str(docker))
    port = free_port()
    app = server.require_token(server.build_server([f"127.0.0.1:{port}"]).streamable_http_app(), TOKEN)
    # log_config=None: keep uvicorn from reconfiguring loggers other tests inspect
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if uv.started:
                break
            time.sleep(0.05)
        monkeypatch.setenv("HARNESS_CODE_MCP_URL", f"http://127.0.0.1:{port}/mcp")
        monkeypatch.setenv("HARNESS_CODE_MCP_TOKEN", TOKEN)
        result = asyncio.run(CodeStore().execute("python_run", {"code": "print(sum(range(101)))"}))
        assert result["stdout"].strip() == "5050" and result["exit_code"] == 0
        monkeypatch.setenv("HARNESS_CODE_MCP_TOKEN", "w" * 32)
        # The exact misconfiguration seen in deployment (wrong token) is named, not hidden.
        assert asyncio.run(CodeStore().execute("python_run", {"code": "print(1)"})) == {"error": "sandbox_unavailable", "reason": "unauthorized"}
    finally:
        uv.should_exit = True
        thread.join(timeout=5)


def rules_text():
    from code_mcp import RULES
    return " ".join(RULES.split())


def test_rules_require_python_for_derived_numbers_only():
    text = rules_text()
    assert "Use it for derived numbers your answer depends on" in text
    assert "never mental arithmetic" in text and "Write one script that computes all of them" in text
    assert "Do not run Python for numbers given in the request or a source" in text
    assert "A writing task with no calculation needs no run." in text
    assert "every number, total, percentage" not in text


def test_rules_bound_length_limit_drafting():
    text = rules_text()
    assert "write the draft once, in the answer and never repeatedly in your reasoning" in text
    assert "Count exactly the text the limit applies to" in text and "not the subject line or signature" in text
    assert "with one python_run, adjust the draft once" in text


def test_rules_require_shown_code_to_be_the_code_that_ran():
    text = rules_text()
    assert "Code you show in the answer must be code that ran, exactly as it ran." in text
    assert "put each one in the run, printing its own labeled result; one run can hold several" in text
    assert "Never show a tidied, renamed or partial rewrite" in text and 'labeled "not run"' in text
    assert "Quote output exactly as python_run printed it" in text


def test_rules_cover_quoted_forms_formula_checks_choices_and_ballparks():
    text = rules_text()
    assert "Print each number in the exact form you will quote it" in text
    assert "a value printed as a fraction or in other units does not count" in text
    assert "test it in the same run against a direct count or simulation" in text and "print the number of mismatches" in text
    assert "Label values you choose (allocations, thresholds, assumptions) as chosen" in text
    assert "Do not state typical or ballpark figures as facts" in text
