"""One bounded call to a trusted Streamable HTTP MCP server, shared by the adapters."""
import asyncio
import json
import logging
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

log = logging.getLogger("uvicorn.error")


def trusted_url(url):
    """Endpoints come from deployment configuration only, never from a model or request."""
    parts = urlsplit(url or "")
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and not (
        parts.username or parts.password or parts.query or parts.fragment)


async def call_tool(url, name, args, timeout, prefix, headers=None, max_bytes=65536):
    """Return the tool's JSON object, or {"error": "<prefix>_..."} without upstream detail."""
    async with asyncio.timeout(timeout):
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False, headers=headers or {}) as client:
            async with streamable_http_client(url, http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, args)
                    if result.isError:
                        return {"error": prefix + "_tool_failed"}
                    text = "".join(c.text for c in result.content if c.type == "text")
                    if len(text.encode()) > max_bytes:
                        return {"error": prefix + "_result_too_large"}
                    return json.loads(text)


def failure_reason(exc):
    """A short, fixed code for why a call failed, without upstream bodies or secrets."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return {401: "unauthorized", 403: "forbidden", 404: "not_found", 421: "host_not_allowed"}.get(status, f"http_{status}")
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection_failed"
    if isinstance(exc, ValueError):
        return "invalid_response"
    return "error_" + type(exc).__name__.lower()[:40]


def unavailable(prefix, tool, exc):
    """Log why a server could not be reached and tell the model the same short reason."""
    reason = failure_reason(exc)
    log.warning(json.dumps({"event": "mcp_call_failed", "server": prefix, "tool": tool, "reason": reason}))
    return {"error": prefix + "_unavailable", "reason": reason}
