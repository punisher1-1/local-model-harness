"""Team knowledge base: SQLite FTS5 articles edited in the UI and searched by kb_search."""
import asyncio
import json
import uuid

from fastapi.testclient import TestClient

import kb_store
from kb_store import KbStore, TEXT_CAP, database, ensure_schema, reindex, sections
from test_app import ask, setup
from test_oidc import KEY, UI, grants, lab, sign_in  # noqa: F401  (fixture)
from test_research import completion, tool

RUNBOOK = """# Domain rename fails with RPC server unavailable

## Symptoms
Renaming the computer fails with "The RPC server is unavailable".

## Fix
1. Check the machine can reach a domain controller.
2. Run the rename again from an elevated prompt.
"""


def kb_grants(editor=True):
    g = grants()
    g["harness-admin"].update(tools=["kb_search", "kb_read"], collections=["team_kb"], kb_editor=editor)
    g["harness-family"].update(tools=["kb_search", "kb_read"], collections=["team_kb"])
    return g


def sign_in_as(client, provider, sub, name, group):
    provider.claims = {"sub": sub, "name": name, "email": sub + "@example.test", "groups": [group]}
    sign_in(client, provider)


def put(client, aid, revision=0, **fields):
    body = {"title": "Domain rename RPC error", "body": RUNBOOK, "tags": ["AD", "rename"], "status": "published", "revision": revision}
    return client.put(f"/v1/kb/{aid}", headers=UI, json={**body, **fields})


def insert(path, aid, body, status="published", title="Article"):
    with database(path) as db:
        db.execute("INSERT INTO kb_articles VALUES (?,?,?,?,?,1,'x','t','x','t')", (aid, title, '["tag"]', body, status))
        reindex(db, aid)


def test_sections_split_at_headings_and_cap_long_ones():
    parts = sections(RUNBOOK)
    assert [h for h, _ in parts] == ["Domain rename fails with RPC server unavailable", "Symptoms", "Fix"]
    long = sections("## Big\n" + ("word " * 200 + "\n\n") * 10)
    assert len(long) > 1 and all(len(t) <= TEXT_CAP and h == "Big" for h, t in long)


def test_search_finds_published_sections_and_never_drafts(tmp_path, monkeypatch):
    path = str(tmp_path / "kb.sqlite3")
    monkeypatch.setenv("HARNESS_CHAT_DB", path)
    ensure_schema(path)
    published, draft = str(uuid.uuid4()), str(uuid.uuid4())
    insert(path, published, RUNBOOK, title="Domain rename RPC error")
    insert(path, draft, "# Secret draft\nRPC server unavailable workaround nobody approved.", status="draft")
    store = KbStore()
    result = asyncio.run(store.execute("kb_search", {"query": "RPC server is unavailable during rename"}))
    assert not result["weak"] and result["results"]
    assert {r["id"] for r in result["results"]} == {published}
    assert result["results"][0]["title"] == "Domain rename RPC error"
    # FTS syntax in the model's query cannot break the search.
    odd = asyncio.run(store.execute("kb_search", {"query": 'rename" OR NEAR( *'}))
    assert "error" not in odd
    weak = asyncio.run(store.execute("kb_search", {"query": "printer toner cartridge"}))
    assert weak["weak"] is True and weak["results"] == []
    read = asyncio.run(store.execute("kb_read", {"id": published}))
    assert "elevated prompt" in read["text"]
    assert asyncio.run(store.execute("kb_read", {"id": draft})) == {"error": "article_not_found"}
    assert "error" in asyncio.run(store.execute("kb_search", {"query": "x", "collection": "it"}))
    assert asyncio.run(store.execute("vault_search", {"query": "x"})) == {"error": "tool_not_allowed"}


def test_editor_writes_publishes_and_reader_sees_only_published(lab):  # noqa: F811
    ed, provider = lab(role_grants=kb_grants())
    helper = TestClient(ed.app, base_url="http://harness.test")
    with ed, helper:
        sign_in_as(ed, provider, "user-editor", "Editor", "harness-admin")
        sign_in_as(helper, provider, "user-helper", "Helper", "harness-family")
        assert ed.get("/v1/identity", headers=UI).json()["kb_editor"] is True

        live, draft = str(uuid.uuid4()), str(uuid.uuid4())
        saved = put(ed, live).json()
        assert saved["revision"] == 1 and saved["updated_by"] == "Editor" and saved["tags"] == ["ad", "rename"]
        assert put(ed, draft, title="Half done", status="draft").status_code == 200

        listing = ed.get("/v1/kb", headers=UI).json()
        assert listing["editor"] and {r["id"] for r in listing["data"]} == {live, draft}
        assert {r["id"] for r in helper.get("/v1/kb", headers=UI).json()["data"]} == {live}
        assert helper.get(f"/v1/kb/{draft}", headers=UI).status_code == 404
        assert helper.get(f"/v1/kb/{live}", headers=UI).json()["body"].startswith("# Domain rename")

        found = helper.get("/v1/kb/search", headers=UI, params={"q": "RPC unavailable rename"}).json()
        assert [r["id"] for r in found["results"]][:1] == [live]

        # Readers cannot write; the service key is not a person and cannot either.
        assert put(helper, str(uuid.uuid4())).status_code == 403
        assert ed.put(f"/v1/kb/{uuid.uuid4()}", headers={"Authorization": "Bearer " + KEY},
                        json={"title": "t", "body": "b", "revision": 0}).status_code == 403

        # A stale revision is refused; unpublishing drops it from search.
        assert put(ed, live, revision=0).status_code == 409
        assert put(ed, live, revision=1, status="draft").json()["revision"] == 2
        assert helper.get("/v1/kb/search", headers=UI, params={"q": "RPC unavailable rename"}).json()["results"] == []

        assert ed.delete(f"/v1/kb/{live}", headers=UI, params={"revision": 1}).status_code == 409
        assert ed.delete(f"/v1/kb/{live}", headers=UI, params={"revision": 2}).status_code == 204
        assert ed.get(f"/v1/kb/{live}", headers=UI).status_code == 404
        with database(kb_store.os.environ["HARNESS_CHAT_DB"]) as db:
            assert db.execute("SELECT count(*) FROM kb_revisions WHERE article_id=?", (live,)).fetchone()[0] == 2


def test_no_access_without_the_kb_tool_grant(lab):  # noqa: F811
    client, provider = lab()
    with client:
        sign_in(client, provider)
        assert client.get("/v1/kb", headers=UI).status_code == 403
        assert client.get("/v1/identity", headers=UI).json()["kb_editor"] is False


def test_editor_flag_alone_does_not_grant_editing_without_read_access(lab):  # noqa: F811
    g = grants()
    g["harness-admin"]["kb_editor"] = True
    client, provider = lab(role_grants=g)
    with client:
        sign_in(client, provider)
        assert put(client, str(uuid.uuid4())).status_code == 403


DOCK = """## Symptoms
A Mac on the dock shows only one of two external monitors.

## Fix
Install DisplayLink Manager and allow it under Screen Recording.

## References
- Vendor product page and FAQ
"""


def test_a_conversational_question_finds_the_article_it_is_about(tmp_path):
    """A technician's whole question, filler words and all, must not rank another article's
    "References" section first, or be called weak, just because one rare word matched."""
    path = str(tmp_path / "kb.sqlite3")
    ensure_schema(path)
    rename, dock = str(uuid.uuid4()), str(uuid.uuid4())
    insert(path, rename, RUNBOOK, title="Intune rename fails: The RPC server is unavailable")
    insert(path, dock, DOCK, title="Mac second monitor blank on dock")
    question = ("What is a RPC server in reference to Active Directory or Azure? We have a computer that "
                "failed the renaming process and that was the error.")
    with database(path) as db:
        rows, weak = kb_store.search(db, question)
        assert rows[0]["article_id"] == rename and not weak
        rows, weak = kb_store.search(db, "second monitor not working on the dock")
        assert rows[0]["article_id"] == dock and not weak
        rows, weak = kb_store.search(db, "printer offline paper jam")
        assert weak and rows == []


def test_a_chat_with_the_knowledge_base_on_searches_and_cites_it(tmp_path, monkeypatch):
    """End to end through the research loop: the store must give the loop what every
    tool store gives it (a catalog fingerprint), not just answer execute()."""
    path = str(tmp_path / "chat.sqlite3")
    monkeypatch.setenv("HARNESS_CHAT_DB", path)
    ensure_schema(path)
    article = str(uuid.uuid4())
    insert(path, article, RUNBOOK, title="Domain rename RPC error")
    rounds = []

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        body = json.loads(request.content)
        rounds.append(body)
        if len(rounds) == 1:
            assert {t["function"]["name"] for t in body["tools"]} == {"kb_search", "kb_read"}
            assert "team knowledge base" in body["messages"][0]["content"]
            return completion({"role": "assistant", "tool_calls": [tool("kb_search", {"query": "RPC server is unavailable rename"})]}, "tool_calls")
        assert "Domain rename RPC error" in body["messages"][-1]["content"]
        return completion({"role": "assistant", "content": "Retry the rename (Domain rename RPC error — Fix)."})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["kb"]}, handler=backend)
    with client:
        r = ask(client)
    assert r.status_code == 200, r.text
    assert "MCP activity (Team knowledge base): kb_search" in r.text
    assert len(rounds) == 2


def test_an_unexpected_error_ends_the_stream_with_a_message(tmp_path, monkeypatch):
    """A bug in the tool loop must reach the chat as an error event with a request ID,
    not as a dropped connection (the browser's "network error")."""
    import research

    async def broken(*args, **kwargs):
        raise RuntimeError("bug")
    monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "chat.sqlite3"))
    monkeypatch.setattr(research, "run_research", broken)
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["kb"]})
    with client:
        r = ask(client, stream=True)
    assert r.status_code == 200
    assert "The harness hit an internal error. Request ID: " in r.text and r.text.rstrip().endswith("data: [DONE]")
