import asyncio
import json
import threading
import time

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
import pytest
import uvicorn

from rag_tool import RagStore, TEXT_CAP
from research import describe_result
from test_app import setup, ask
from test_code_mcp import free_port
from test_research import completion, tool

TOKEN = "r" * 32


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("HARNESS_RAG_URL", "http://rag:8100")
    monkeypatch.setenv("HARNESS_RAG_TOKEN", TOKEN)


def test_configuration_is_required(monkeypatch):
    monkeypatch.setenv("HARNESS_RAG_TOKEN", TOKEN)
    monkeypatch.setenv("HARNESS_RAG_URL", "http://user:pw@rag:8100")
    with pytest.raises(ValueError):
        RagStore()
    monkeypatch.setenv("HARNESS_RAG_URL", "http://rag:8100")
    monkeypatch.setenv("HARNESS_RAG_TOKEN", "short")
    with pytest.raises(ValueError):
        RagStore()


def test_arguments_results_and_errors_are_bounded(env, monkeypatch):
    store = RagStore()
    replies, sent = [], []

    async def fake(args):
        sent.append(args)
        return replies.pop(0)
    monkeypatch.setattr(store, "call", fake)

    async def run():
        assert (await store.execute("rag_chat", {"query": "x"}))["error"] == "tool_not_allowed"
        assert (await store.execute("rag_search", {"query": "x", "top_k": 50}))["error"] == "invalid_arguments"
        assert (await store.execute("rag_search", {"query": "x", "collection": "../etc"}))["error"] == "invalid_arguments"
        replies.append({"results": [], "weak": True, "collections": ["it help"]})
        await store.execute("rag_search", {"query": "x", "collection": "it help"})
        assert sent[-1] == {"query": "x", "collection": "it help"}
        replies.append({"results": [{"title": "IT301 Week 4", "locator": "§2 Files, p. 9", "text": "y" * 9000, "secret": 1}] * 12,
                        "weak": False, "collections": ["it301"]})
        found = await store.execute("rag_search", {"query": "sequential file"})
        assert sent[-1] == {"query": "sequential file"}
        assert len(found["results"]) == 10 and len(found["results"][0]["text"]) == TEXT_CAP and found["results"][0]["truncated"]
        assert "secret" not in found["results"][0] and found["collections"] == ["it301"]
        replies.append({"results": [], "weak": True, "collections": []})
        empty = await store.execute("rag_search", {"query": "powerpoint length"})
        assert empty["weak"] and "Weak match" in empty["next_step"]
        assert describe_result({"results": [1], "weak": True}) == "  ✓ 1 results (weak match)"
        replies.append({"error": "unknown_collection", "collections": ["it301", "nist"]})
        assert await store.execute("rag_search", {"query": "x", "collection": "atf"}) == {"error": "unknown_collection", "collections": ["it301", "nist"]}
        replies.append({"error": "Traceback (most recent call last): password"})
        assert await store.execute("rag_search", {"query": "x"}) == {"error": "rag_search_failed"}
    asyncio.run(run())


def test_loop_cites_the_knowledge_base(tmp_path, env, monkeypatch):
    rounds = []

    async def fake(self, args):
        return {"results": [{"title": "IT301 Week 4", "locator": "§2 Files, p. 9",
                             "text": "A sequential file is read in order from start to end."}], "weak": False, "collections": ["it301"]}
    monkeypatch.setattr(RagStore, "call", fake)

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        body = json.loads(request.content)
        rounds.append(body)
        if len(rounds) == 1:
            assert {t["function"]["name"] for t in body["tools"]} == {"rag_search"}
            assert "curated knowledge base" in body["messages"][0]["content"]
            return completion({"role": "assistant", "tool_calls": [tool("rag_search", {"query": "sequential file definition"})]}, "tool_calls")
        assert "IT301 Week 4" in body["messages"][-1]["content"]
        return completion({"role": "assistant", "content": "Read in order (IT301 Week 4 — §2 Files, p. 9)."})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["rag"]}, handler=backend)
    with client:
        r = ask(client)
    assert r.status_code == 200 and "MCP activity (Knowledge base): rag_search" in r.text
    assert "→ rag_search(sequential file definition)" in r.json()["choices"][0]["message"]["reasoning_content"]


def test_round_trip_over_http_with_the_token(monkeypatch):
    """The adapter speaks the gateway's /v1/search contract: bearer token, JSON body, JSON errors."""
    gateway = FastAPI()
    seen = []

    @gateway.post("/v1/search")
    def search(body: dict, authorization: str = Header(default="")):
        if authorization != "Bearer " + TOKEN:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        seen.append(body)
        if body.get("collection") == "atf":
            return JSONResponse({"error": "unknown_collection", "collections": ["it301"]}, status_code=400)
        return {"results": [{"rank": 1, "title": "IT301 Week 4", "locator": "p. 9", "text": "ok"}], "weak": False, "collections": ["it301"]}

    port = free_port()
    uv = uvicorn.Server(uvicorn.Config(gateway, host="127.0.0.1", port=port, log_config=None))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if uv.started:
                break
            time.sleep(0.05)
        monkeypatch.setenv("HARNESS_RAG_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("HARNESS_RAG_TOKEN", TOKEN)
        assert asyncio.run(RagStore().execute("rag_search", {"query": "files"}))["results"][0]["title"] == "IT301 Week 4"
        assert asyncio.run(RagStore().execute("rag_search", {"query": "x", "collection": "atf"}))["error"] == "unknown_collection"
        monkeypatch.setenv("HARNESS_RAG_TOKEN", "w" * 32)
        assert asyncio.run(RagStore().execute("rag_search", {"query": "x"})) == {"error": "rag_unavailable", "reason": "unauthorized"}
        assert seen == [{"query": "files"}, {"query": "x", "collection": "atf"}]
    finally:
        uv.should_exit = True
        thread.join(timeout=5)


def test_rules_treat_the_knowledge_base_as_a_source_to_apply_with_honest_attribution():
    from rag_tool import RULES
    text = " ".join(RULES.split())
    assert "trusted source to reason from, not a script to recite" in text
    assert "Apply what it says to the conversation" in text
    assert "must come from a returned passage" in text and "quotations must match its wording" in text
    assert "Quote only when the exact wording matters" in text
    assert "Cite the passages your answer relies on" in text
    assert "Quote definitions as the passage states them" not in text


def test_rules_require_a_search_before_crediting_a_named_document():
    from rag_tool import RULES
    text = " ".join(RULES.split())
    assert "Search before you attribute." in text
    assert "search the knowledge base for it" in text
    assert "present the point as your own knowledge, not as the document's" in text
    # The search rule comes before the attribution rule it supports.
    assert text.index("Search before you attribute.") < text.index("Keep attribution honest.")
