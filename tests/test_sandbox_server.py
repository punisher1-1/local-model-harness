"""Sandbox server behavior with a fake docker binary that runs code with local Python.

Container isolation itself (network, filesystem, memory, processes) is verified on the
sandbox host with the escape tests in sandbox/README.md; these tests cover the server.
"""
import asyncio
import json
import os
import stat
import sys

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sandbox"))
import server  # noqa: E402

FAKE = """#!{python}
import os, sys
args = sys.argv[1:]
if args and args[0] == "run":
    image = os.environ["SANDBOX_IMAGE_UNDER_TEST"]
    command = args[args.index(image) + 1:]
    os.execv(sys.executable, [sys.executable] + command[1:])
"""


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    path = tmp_path / "docker"
    path.write_text(FAKE.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SANDBOX_IMAGE_UNDER_TEST", server.IMAGE)
    monkeypatch.setattr(server, "DOCKER", str(path))
    monkeypatch.setattr(server, "TIMEOUT_SECONDS", 2)


def run(code):
    return asyncio.run(server.run_python(code))


def test_container_flags_are_fixed_and_locked_down():
    cmd = server.docker_command("sbx-test")
    joined = " ".join(cmd)
    for flag in ["--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--user 10001:10001", "--memory 512m", "--memory-swap 512m", "--pids-limit 64", "--cpus 1", "--rm"]:
        assert flag in joined
    assert cmd[-4:] == [server.IMAGE, "python", "-I", "-"]


def test_output_errors_and_exit_codes(fake_docker):
    ok = run("import math\nprint(math.factorial(20))")
    assert ok["stdout"].strip() == "2432902008176640000" and ok["exit_code"] == 0 and not ok["timed_out"]
    bad = run("1/0")
    assert bad["exit_code"] == 1 and "ZeroDivisionError" in bad["stderr"]


def test_timeouts_stop_the_run(fake_docker):
    result = run("while True: pass")
    assert result["timed_out"] and result["duration_ms"] < 6000


def test_output_floods_are_capped_and_stopped(fake_docker):
    result = run("while True: print('x' * 1000)")
    assert result["output_limit"] and result["truncated"] and len(result["stdout"]) <= server.OUTPUT_CAP


def test_tool_validates_code_and_reports_busy(fake_docker):
    mcp = server.build_server(["testserver"])

    async def call(code):
        content, _ = await mcp.call_tool("python_run", {"code": code})
        return json.loads(content[0].text)

    async def scenario():
        assert (await call("print(6*7)"))["stdout"].strip() == "42"
        assert (await call("   "))["error"] == "invalid_code"
        assert (await call("x" * 20001))["error"] == "invalid_code"
        for _ in range(server.MAX_CONCURRENT):
            await server._slots.acquire()
        try:
            assert (await call("print(1)"))["error"] == "sandbox_busy"
        finally:
            for _ in range(server.MAX_CONCURRENT):
                server._slots.release()
    asyncio.run(scenario())


def test_every_request_needs_the_bearer_token():
    async def inner(scope, receive, send):
        if scope["type"] == "lifespan":  # lifespan events pass through the guard untouched
            while (message := await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    app = server.require_token(inner, "t" * 32)
    with TestClient(app) as client:
        assert client.post("/mcp").status_code == 401
        assert client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post("/mcp", headers={"Authorization": "Bearer " + "t" * 32}).text == "ok"
