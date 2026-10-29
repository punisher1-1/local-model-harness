import json
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest
import yaml

from app import Profile
from test_app import setup, ask, HEADERS
from test_research import completion, tool
from vault_mcp import VaultStore

VAULT_RULE = "search, read, create and append notes in Local_AI_Vault"
TOOLS = {"client_tools": True}


@pytest.fixture
def vault(monkeypatch):
    monkeypatch.setenv("HARNESS_VAULT_MCP_URL", "http://vault/mcp")
    calls = []

    async def fake(self, name, args):
        calls.append(name)
        return {"results": [{"path": "Lab/note.md", "snippet": "evidence"}]} if name == "vault_search" else {"content": "Evidence."}
    monkeypatch.setattr(VaultStore, "call", fake)
    return calls


def recorder(rounds, use_tool=True):
    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        body = json.loads(request.content)
        rounds.append(body)
        if body.get("tools") and use_tool and len(rounds) == 1:
            return completion({"role": "assistant", "tool_calls": [tool("vault_search", {"query": "evidence"})]}, "tool_calls")
        return completion({"role": "assistant", "content": "Answer."})
    return backend


def mcp_ask(client, value):
    return client.post("/v1/chat/completions", headers={**HEADERS, **({} if value is None else {"X-Harness-MCP": value})},
                       json={"model": "local", "messages": [{"role": "user", "content": "Hi"}]})


def test_defaults_apply_without_a_header_and_the_header_narrows(tmp_path, vault):
    rounds = []
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"]}, handler=recorder(rounds))
    with client:
        r = mcp_ask(client, None)
        assert r.status_code == 200 and r.headers["x-harness-mcp"] == "vault" and "Vault MCP activity" in r.text
        assert vault == ["vault_search"] and VAULT_RULE in rounds[0]["messages"][0]["content"]
        rounds.clear(); vault.clear()
        r = mcp_ask(client, "none")
        assert r.status_code == 200 and r.headers["x-harness-mcp"] == "none" and "MCP activity" not in r.text
        assert vault == [] and "tools" not in rounds[0] and VAULT_RULE not in rounds[0]["messages"][0]["content"]


def test_opt_in_profiles_stay_off_until_selected(tmp_path, vault):
    rounds = []
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"], "mcp_default": []}, handler=recorder(rounds))
    with client:
        assert mcp_ask(client, None).headers["x-harness-mcp"] == "none" and vault == []
        rounds.clear()
        assert "Vault MCP activity" in mcp_ask(client, "vault").text and vault == ["vault_search"]


def test_header_cannot_add_servers_the_profile_does_not_allow(tmp_path, vault):
    client, _ = setup(tmp_path, TOOLS)
    with client:
        for value in ["vault", "vault,vault", "unknown", "x" * 300]:
            assert mcp_ask(client, value).status_code == 400
        assert mcp_ask(client, "none").status_code == 200
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"]})
    with client:
        assert "Allowed: vault" in mcp_ask(client, "vault,unknown").text


def test_client_tools_and_tool_choice_none_take_precedence(tmp_path, vault):
    rounds = []
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"]}, handler=recorder(rounds, use_tool=False))
    fn = {"type": "function", "function": {"name": "client_fn", "parameters": {"type": "object", "properties": {}}}}
    with client:
        r = client.post("/v1/chat/completions", headers={**HEADERS, "X-Harness-MCP": "vault"},
                        json={"model": "local", "messages": [{"role": "user", "content": "Hi"}], "tools": [fn]})
        assert r.status_code == 200 and r.headers["x-harness-mcp"] == "none"
        assert [t["function"]["name"] for t in rounds[-1]["tools"]] == ["client_fn"]
        r = ask(client, tool_choice="none")
        assert r.headers["x-harness-mcp"] == "none" and vault == []


def test_catalog_lists_allowed_servers_with_granted_tools_and_skill_descriptions(tmp_path, vault, monkeypatch):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "notes.md").write_text("# Note research\nSearch first. Then read the note.\n## Format\nCite paths.")
    client, _ = setup(tmp_path, {**TOOLS, "mcp_servers": ["vault"], "mcp_default": [], "skills": ["notes"], "default_skill": "notes"})
    with client:
        row = client.get("/v1/profiles", headers=HEADERS).json()["data"][0]
        assert row["skill_info"] == [{"id": "notes", "title": "Note research", "description": "Search first."}]
        server = row["mcp_servers"][0]
        assert server["id"] == "vault" and server["default"] is False and "vault_read_note" in server["tools"]
        assert row["server_tools"] == server["tools"]
        identity = client.app.state.identity
        principal = identity.authenticate(HEADERS["Authorization"])
        monkeypatch.setattr(identity, "authenticate", lambda _: replace(principal, collections=frozenset()))
        assert client.get("/v1/profiles", headers=HEADERS).json()["data"][0]["mcp_servers"] == []


@pytest.mark.parametrize("bad", [
    {**TOOLS, "mcp_servers": ["nope"]},
    {**TOOLS, "mcp_servers": ["vault", "vault"]},
    {**TOOLS, "mcp_servers": ["vault"], "mcp_default": ["other"]},
    {"mcp_servers": ["vault"]},
])
def test_invalid_mcp_configuration_is_rejected(bad):
    with pytest.raises(ValueError):
        Profile.model_validate({"backend_model": "m", "system_prompt_file": "p.md", **bad})


def test_legacy_mcp_vault_flag_means_vault_on_by_default():
    p = Profile.model_validate({"backend_model": "m", "system_prompt_file": "p.md", **TOOLS, "mcp_vault": True})
    assert p.mcp_servers == ["vault"] and p.mcp_default == ["vault"]


def test_conversations_keep_skill_and_tool_choices_and_migrate_old_tables(tmp_path, monkeypatch):
    db = tmp_path / "history.sqlite3"
    with sqlite3.connect(db) as conn:  # table as created before per-chat options existed
        conn.execute("CREATE TABLE conversations (owner TEXT NOT NULL, id TEXT NOT NULL, profile TEXT NOT NULL, title TEXT NOT NULL, revision INTEGER NOT NULL, messages TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(owner,id))")
        conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?,?)", (json.dumps(["service_key", "lab-service"]), str(uuid4()), "local", "Old", 1, "[]", "2026-01-01"))
    monkeypatch.setenv("HARNESS_CHAT_DB", str(db))
    client, _ = setup(tmp_path)
    path = "/v1/conversations/" + str(uuid4())
    with client:
        old = client.get("/v1/conversations", headers=HEADERS).json()["data"][0]
        restored = client.get("/v1/conversations/" + old["id"], headers=HEADERS).json()
        assert restored["skill"] == "" and restored["mcp_servers"] is None
        body = {"profile": "local", "title": "New", "revision": 0, "messages": [], "skill": "notes", "mcp_servers": ["vault"]}
        assert client.put(path, headers=HEADERS, json=body).status_code == 200
        saved = client.get(path, headers=HEADERS).json()
        assert saved["skill"] == "notes" and saved["mcp_servers"] == ["vault"]
        assert client.put(path, headers=HEADERS, json={**body, "revision": 1, "mcp_servers": ["x" * 65]}).status_code == 400


def test_repository_profiles_enable_vault_by_policy():
    profiles = yaml.safe_load(open("profiles.yaml"))["profiles"]
    assert profiles["local-tools"]["mcp_servers"] == ["vault", "code", "web", "rag"]
    assert profiles["local-tools"]["mcp_default"] == ["vault", "code", "rag"]
    for name in ["local-home", "local-work"]:
        assert profiles[name]["mcp_servers"] == ["vault", "code", "web", "rag"] and profiles[name]["mcp_default"] == []
