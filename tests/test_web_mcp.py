import asyncio
import json
import os
import sys
import threading
import time

import httpx
import pytest
import uvicorn

from web_mcp import WebStore, TEXT_CAP, CONTEXT_CAP
from test_app import setup, ask
from test_code_mcp import free_port
from test_research import completion, tool

TOKEN = "w" * 32


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("HARNESS_WEB_MCP_URL", "http://web/mcp")
    monkeypatch.setenv("HARNESS_WEB_MCP_TOKEN", TOKEN)


def test_configuration_is_required(monkeypatch):
    monkeypatch.setenv("HARNESS_WEB_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("HARNESS_WEB_MCP_URL", "http://web/mcp?redirect=x")
    with pytest.raises(ValueError):
        WebStore()
    monkeypatch.setenv("HARNESS_WEB_MCP_URL", "http://web/mcp")
    monkeypatch.setenv("HARNESS_WEB_MCP_TOKEN", "")
    with pytest.raises(ValueError):
        WebStore()


def test_results_are_capped_and_errors_normalized(env, monkeypatch):
    store = WebStore()
    replies = []

    async def fake(name, args):
        return replies.pop(0)
    monkeypatch.setattr(store, "call", fake)

    async def run():
        assert (await store.execute("web_fetch_any", {"url": "x"}))["error"] == "tool_not_allowed"
        assert (await store.execute("web_search", {"query": "x", "count": 20}))["error"] == "invalid_arguments"
        assert (await store.execute("web_read", {"url": "file:///etc/passwd"}))["error"] == "unsupported_url"
        replies.append({"results": [{"title": "t" * 900, "url": "https://a.example", "snippet": "s", "extra_snippets": ["1", "2", "3", "4"], "x": 1}] * 12})
        found = await store.execute("web_search", {"query": "proxmox"})
        assert len(found["results"]) == 8 and len(found["results"][0]["title"]) == 200 and "x" not in found["results"][0]
        assert found["results"][0]["extra_snippets"] == ["1", "2", "3"]
        replies.append({"url": "https://a.example/p", "title": "T", "text": "y" * 40000})
        page = await store.execute("web_read", {"url": "https://a.example/p"})
        assert len(page["text"]) == TEXT_CAP and page["truncated"]
        assert (await store.execute("web_context", {"query": "x", "max_tokens": 50000}))["error"] == "invalid_arguments"
        assert (await store.execute("web_context", {"query": "x", "freshness": "today"}))["error"] == "invalid_arguments"
        replies.append({"results": [{"title": "t", "url": "https://a.example", "age": "2025-01-15", "snippets": ["s" * 5000] * 20, "x": 1},
                                    {"title": "none", "url": "https://b.example", "snippets": []}] * 6, "truncated": False})
        ctx = await store.execute("web_context", {"query": "proxmox", "max_tokens": 4096, "freshness": "pm"})
        assert sum(len(x) for r in ctx["results"] for x in r["snippets"]) == CONTEXT_CAP and ctx["truncated"]
        assert len(ctx["results"][0]["snippets"]) == 8 and len(ctx["results"][0]["snippets"][0]) == 4000
        assert "x" not in ctx["results"][0] and all(r["snippets"] for r in ctx["results"])
        replies.append({"error": "private_address"})
        assert await store.execute("web_read", {"url": "http://10.0.0.1/"}) == {"error": "private_address"}
        replies.append({"error": "Traceback: something odd happened!"})
        assert await store.execute("web_search", {"query": "x"}) == {"error": "web_tool_failed"}
    asyncio.run(run())


def test_loop_searches_reads_and_reports_activity(tmp_path, env, monkeypatch):
    rounds = []

    async def fake(self, name, args):
        if name == "web_search":
            return {"results": [{"title": "PVE 9 release notes", "url": "https://pve.example/notes", "snippet": "released"}]}
        return {"url": args["url"], "title": "Release notes", "text": "Proxmox VE 9.0 released in August."}
    monkeypatch.setattr(WebStore, "call", fake)

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        body = json.loads(request.content)
        rounds.append(body)
        if len(rounds) == 1:
            assert {t["function"]["name"] for t in body["tools"]} == {"web_context", "web_search", "web_read"}
            assert "untrusted evidence from the internet" in body["messages"][0]["content"]
            return completion({"role": "assistant", "tool_calls": [tool("web_search", {"query": "proxmox ve 9 release"})]}, "tool_calls")
        if len(rounds) == 2:
            return completion({"role": "assistant", "tool_calls": [tool("web_read", {"url": "https://pve.example/notes"}, "c2")]}, "tool_calls")
        return completion({"role": "assistant", "content": "Proxmox VE 9.0 was released in August [https://pve.example/notes]."})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["web"]}, handler=backend)
    with client:
        r = ask(client)
    assert r.status_code == 200 and "MCP activity (Web search): web_search → web_read" in r.text
    assert "→ web_read(https://pve.example/notes)" in r.json()["choices"][0]["message"]["reasoning_content"]


def test_round_trip_through_the_real_web_server(monkeypatch):
    """Adapter → MCP over HTTP with the token → web server → mocked Brave API."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sandbox"))
    import web_server
    monkeypatch.setattr(web_server, "BRAVE_KEY", "brave-key-under-test")
    monkeypatch.setitem(web_server._usage, "day", None)

    def brave(request):
        assert request.url.host == "api.search.brave.com" and request.headers["X-Subscription-Token"] == "brave-key-under-test"
        if request.url.path == "/res/v1/llm/context":
            return httpx.Response(200, json={"grounding": {"generic": [{"url": "https://example.com/", "title": "Hermes", "snippets": ["Hermes is a VM."]}]}})
        return httpx.Response(200, json={"web": {"results": [{"title": "Hermes", "url": "https://example.com/", "description": "ok"}]}})
    port = free_port()
    mcp = web_server.build_server([f"127.0.0.1:{port}"], client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(brave)))
    app = web_server.require_token(mcp.streamable_http_app(), TOKEN)
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if uv.started:
                break
            time.sleep(0.05)
        monkeypatch.setenv("HARNESS_WEB_MCP_URL", f"http://127.0.0.1:{port}/mcp")
        monkeypatch.setenv("HARNESS_WEB_MCP_TOKEN", TOKEN)
        result = asyncio.run(WebStore().execute("web_search", {"query": "hermes"}))
        assert result["results"][0]["url"] == "https://example.com/"
        assert "brave-key-under-test" not in json.dumps(result)
        context = asyncio.run(WebStore().execute("web_context", {"query": "hermes"}))
        assert context["results"] == [{"title": "Hermes", "url": "https://example.com/", "age": "", "snippets": ["Hermes is a VM."]}]
    finally:
        uv.should_exit = True
        thread.join(timeout=5)


def test_rules_send_troubleshooting_to_product_docs_and_matching_sources():
    from web_mcp import RULES
    text = " ".join(RULES.split())
    assert "search the product's own documentation and the names of the settings or options" in text
    assert text.index("documentation") < text.index("then issues and forums")
    assert "does not describe the user's actual symptom" in text
    assert "read or search for another source rather than answering from a near match" in text
    assert "say the cause is unconfirmed" in text


def test_rules_prefer_context_passages_over_full_pages():
    from web_mcp import RULES
    text = " ".join(RULES.split())
    assert "Prefer web_context" in text and "usually need no web_read" in text
    assert "web_search snippets are not verification" in text


def test_descriptions_steer_questions_to_web_context():
    from web_mcp import SCHEMAS
    described = {t["function"]["name"]: t["function"]["description"] for t in SCHEMAS}
    assert described["web_context"].startswith("Default web tool for answering questions.")
    assert "use web_context instead" in described["web_search"]
    assert [t["function"]["name"] for t in SCHEMAS][0] == "web_context"
