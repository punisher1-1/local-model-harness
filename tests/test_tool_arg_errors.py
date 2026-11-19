import asyncio

from pydantic import ValidationError

from mcp_client import invalid_arguments


def run(coro):
    return asyncio.run(coro)


def test_web_read_extra_field_is_named(monkeypatch):
    monkeypatch.setenv("HARNESS_WEB_MCP_URL", "http://127.0.0.1:8203/mcp")
    monkeypatch.setenv("HARNESS_WEB_MCP_TOKEN", "x" * 32)
    from web_mcp import WebStore
    result = run(WebStore().execute("web_read", {"url": "https://example.com", "max_chars": 4000}))
    assert result == {"error": "invalid_arguments", "next_step": "web_read takes: url. Remove: max_chars."}


def test_missing_and_wrong_fields_are_named(monkeypatch):
    monkeypatch.setenv("HARNESS_WEB_MCP_URL", "http://127.0.0.1:8203/mcp")
    monkeypatch.setenv("HARNESS_WEB_MCP_TOKEN", "x" * 32)
    from web_mcp import WebStore
    result = run(WebStore().execute("web_read", {}))
    assert result["next_step"] == "web_read takes: url. Missing: url."
    result = run(WebStore().execute("web_context", {"query": "dock", "freshness": "yesterday"}))
    assert result["next_step"].startswith("web_context takes: ")
    assert "Fix: freshness (one of " in result["next_step"]


def test_values_are_never_echoed():
    from web_mcp import MODELS
    secret = "do-not-echo-this-value"
    try:
        MODELS["web_read"].model_validate({"url": "", "token": secret})
    except ValidationError as error:
        message = invalid_arguments("web_read", MODELS["web_read"], error)["next_step"]
    assert secret not in message and "token" in message and "url (at least 1 characters)" in message
