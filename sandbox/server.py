"""Python sandbox MCP server for the local model harness (ADR-003).

Runs on the dedicated Hermes VM. Exposes one tool, python_run. Each call starts a
fresh Docker container with no network, a read-only root filesystem, a non-root
user and CPU/memory/process/time limits, then removes it. The harness on the harness host
is the only client: the host firewall limits the port and every request must
carry the shared bearer token.

Logs hold request metadata only (code length, exit code, duration), never code
or output.
"""
import asyncio
import json
import logging
import os
import time
import uuid

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from common import require_token

log = logging.getLogger("harness-sandbox")

IMAGE = os.getenv("SANDBOX_IMAGE", "harness-sandbox:py312")
DOCKER = os.getenv("SANDBOX_DOCKER", "docker")
TIMEOUT_SECONDS = float(os.getenv("SANDBOX_TIMEOUT_SECONDS", "30"))
MAX_CONCURRENT = int(os.getenv("SANDBOX_MAX_CONCURRENT", "2"))
MAX_CODE_CHARS = 20000
OUTPUT_CAP = 16000          # bytes kept per stream and returned
OUTPUT_KILL = 4_000_000     # bytes seen per stream before the run is stopped
LABEL = "harness-sandbox=1"

_slots = asyncio.Semaphore(MAX_CONCURRENT)


def docker_command(name):
    """The fixed, locked-down container invocation. Nothing in it comes from the request."""
    return [DOCKER, "run", "--rm", "-i", "--name", name, "--label", LABEL,
            "--network", "none", "--read-only",
            "--tmpfs", "/work:size=64m,noexec,nosuid,uid=10001,gid=10001",
            "--tmpfs", "/tmp:size=16m,noexec,nosuid,uid=10001,gid=10001",
            "--workdir", "/work", "--user", "10001:10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
            "--pids-limit", "64", "--ulimit", "nofile=256:256",
            "-e", "HOME=/work", "-e", "MPLBACKEND=Agg", "-e", "PYTHONDONTWRITEBYTECODE=1",
            IMAGE, "python", "-I", "-"]


class Capture:
    """Keep the first OUTPUT_CAP bytes of a stream and count the rest."""
    def __init__(self):
        self.data = bytearray()
        self.total = 0

    async def drain(self, stream, on_flood):
        while chunk := await stream.read(65536):
            self.total += len(chunk)
            if len(self.data) < OUTPUT_CAP:
                self.data.extend(chunk[:OUTPUT_CAP - len(self.data)])
            if self.total > OUTPUT_KILL:
                on_flood()
                return

    def text(self):
        return self.data.decode("utf-8", errors="replace")


async def _cleanup(name):
    for args in (("kill", name), ("rm", "-f", name)):
        proc = await asyncio.create_subprocess_exec(DOCKER, *args, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()


async def run_python(code):
    name = "sbx-" + uuid.uuid4().hex[:16]
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(*docker_command(name), stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = Capture(), Capture()
    flooded = False

    def flood():
        nonlocal flooded
        flooded = True
        proc.kill()

    timed_out = False
    try:
        try:
            proc.stdin.write(code.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the container exited before reading all input; its stderr explains why
        try:
            await asyncio.wait_for(asyncio.gather(out.drain(proc.stdout, flood), err.drain(proc.stderr, flood), proc.wait()),
                                   TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            timed_out = True
    finally:
        if proc.returncode is None or timed_out or flooded:
            await _cleanup(name)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    exit_code = proc.returncode
    stderr = err.text()
    if exit_code == 125 and not stderr.strip():
        stderr = "sandbox container failed to start"
    elif exit_code == 137 and not timed_out and not flooded:
        stderr += "\nKilled: the run most likely exceeded the 512 MB memory limit."
    return {"stdout": out.text(), "stderr": stderr, "exit_code": exit_code, "timed_out": timed_out,
            "output_limit": flooded, "truncated": out.total > OUTPUT_CAP or err.total > OUTPUT_CAP,
            "duration_ms": round((time.monotonic() - started) * 1000)}


def build_server(allowed_hosts):
    mcp = FastMCP("harness-sandbox", stateless_http=True, json_response=True,
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                               allowed_hosts=allowed_hosts))

    @mcp.tool()
    async def python_run(code: str) -> str:
        """Run a Python 3.12 script in a fresh sandbox with numpy, pandas, sympy and matplotlib.
        No network; nothing persists between runs. Print the results you need."""
        rid = uuid.uuid4().hex[:12]
        if not code.strip() or len(code) > MAX_CODE_CHARS:
            return json.dumps({"error": "invalid_code", "detail": f"Provide 1 to {MAX_CODE_CHARS} characters of Python."})
        if _slots.locked():
            log.info(json.dumps({"event": "run", "id": rid, "status": "busy"}))
            return json.dumps({"error": "sandbox_busy", "detail": "Another run is in progress; retry shortly."})
        async with _slots:
            result = await run_python(code)
        log.info(json.dumps({"event": "run", "id": rid, "code_chars": len(code), "exit_code": result["exit_code"],
                             "timed_out": result["timed_out"], "output_limit": result["output_limit"],
                             "duration_ms": result["duration_ms"]}))
        return json.dumps(result)

    return mcp


async def sweep():
    """Remove containers a crashed run may have left behind."""
    proc = await asyncio.create_subprocess_exec(DOCKER, "ps", "-aq", "--filter", "label=" + LABEL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    ids = (await proc.communicate())[0].decode().split()
    if ids:
        rm = await asyncio.create_subprocess_exec(DOCKER, "rm", "-f", *ids, stdout=asyncio.subprocess.DEVNULL,
                                                  stderr=asyncio.subprocess.DEVNULL)
        await rm.wait()
    return len(ids)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    token = os.getenv("SANDBOX_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("Set SANDBOX_TOKEN to a random secret of at least 24 characters")
    host = os.getenv("SANDBOX_BIND", "0.0.0.0")
    port = int(os.getenv("SANDBOX_PORT", "8202"))
    allowed = [h.strip() for h in os.getenv("SANDBOX_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*").split(",") if h.strip()]
    log.info(json.dumps({"event": "start", "image": IMAGE, "swept": asyncio.run(sweep()), "port": port}))
    app = require_token(build_server(allowed).streamable_http_app(), token)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
