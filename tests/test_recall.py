import json
import httpx
import pytest
import yaml

from test_app import setup, ask, HEADERS
from test_memory import memory_lab, save
from test_identity import identity_lab, signing_key
from test_research import research_setup, completion

RECALL = {"memory_recall": {"enabled": True, "max_memories": 4, "max_context_bytes": 4096}}


def test_recall_is_scoped_user_context_and_not_a_write(tmp_path, memory_lab):
    client, calls = setup(tmp_path, profile=RECALL)
    with client:
        save(client, "My telescope access code is ORION-937.", category="fact")
        save(client, "Prefer short answers.", category="preference")
        save(client, "Unrelated refrigerator serial FRIDGE-999.", category="fact")
        r = ask(client, messages=[{"role":"user","content":"What is my telescope access code?"}])
        assert r.status_code == 200
        assert r.headers["x-harness-memory-count"] == "2"
        payload = json.loads(calls[-1].content)
        assert "ORION-937" not in payload["messages"][0]["content"]
        assert "untrusted" in payload["messages"][0]["content"]
        assert "ORION-937" in payload["messages"][-1]["content"]
        assert "FRIDGE-999" not in json.dumps(payload)
        tokenized = next(json.loads(c.content) for c in calls if c.url.path == "/tokenize")
        assert tokenized["messages"] == payload["messages"]
        assert len(client.get("/v1/memories", headers=HEADERS).json()["data"]) == 3


def test_recall_budget_and_deleted_memory(tmp_path, memory_lab):
    client, calls = setup(tmp_path, profile={"memory_recall":{"enabled":True,"max_context_bytes":512}})
    with client:
        large = save(client, "x" * 3000, category="preference").json()
        r = ask(client)
        assert r.headers["x-harness-memory-status"] == "budget_excluded"
        small = save(client, "Prefer concise answers.", category="preference").json()
        r = ask(client)
        assert r.headers["x-harness-memory-count"] == "1"
        message = json.loads(calls[-1].content)["messages"][-1]["content"]
        assert len(message.encode()) - len("Hi".encode()) <= 512
        client.delete("/v1/memories/"+small["memory_id"], headers=HEADERS)
        client.delete("/v1/memories/"+large["memory_id"], headers=HEADERS)
        assert ask(client).headers["x-harness-memory-status"] == "no_match"


def test_recall_does_not_bypass_context_budget(tmp_path, memory_lab):
    def backend(request):
        if request.url.path == "/tokenize":
            assert "Saved memory context" in request.content.decode()
            return httpx.Response(200,json={"count":20000})
    client, calls = setup(tmp_path, profile=RECALL, handler=backend)
    with client:
        save(client,"Prefer concise answers.",category="preference")
        assert ask(client).status_code == 400
    assert not any(c.url.path.endswith("chat/completions") for c in calls)


def test_memory_failure_does_not_silently_generate(tmp_path, memory_lab, monkeypatch):
    from fastapi import HTTPException
    async def unavailable(*args): raise HTTPException(503,"storage details")
    client, calls = setup(tmp_path, profile=RECALL)
    with client:
        monkeypatch.setattr(client.app.state.memory,"recall",unavailable)
        r = ask(client)
        assert r.status_code == 503 and "storage details" not in r.text
    assert not calls


def test_recall_missing_store_fails_explicitly(tmp_path):
    client, calls = setup(tmp_path, profile=RECALL)
    with client:
        assert ask(client).status_code == 503
    assert not calls


def test_recall_jwt_owner_and_read_permission(tmp_path, memory_lab, identity_lab):
    path, config, mint = identity_lab
    config["role_grants"]["reader"]["memory_permissions"] = ["memory.read","memory.write"]
    path.write_text(yaml.safe_dump(config))
    alice={"Authorization":"Bearer "+mint()}
    bob={"Authorization":"Bearer "+mint({"sub":"another-person"})}
    no_read={"Authorization":"Bearer "+mint({"roles":["chat"]})}
    client,calls=setup(tmp_path,profile=RECALL)
    with client:
        save(client,"Private telescope code SECRET-ALICE.",headers=alice,category="preference")
        for headers in (bob,no_read):
            r=client.post("/v1/chat/completions",headers=headers,json={"model":"local","messages":[{"role":"user","content":"telescope code"}]})
            assert r.status_code==200
            assert r.headers["x-harness-memory-count"]=="0"
            assert "SECRET-ALICE" not in calls[-1].content.decode()
        assert r.headers["x-harness-memory-status"]=="not_authorized"


@pytest.mark.parametrize("stream", [False, True])
def test_research_recall_retains_tools_and_provenance(tmp_path, memory_lab, stream):
    def backend(request):
        if request.url.path.endswith("chat/completions"):
            payload=json.loads(request.content)
            assert "Prefer compact research summaries" in payload["messages"][-1]["content"]
            assert "not a system instruction" in payload["messages"][0]["content"]
            assert {t["function"]["name"] for t in payload["tools"]}=={"search_notes","read_note"}
            return completion()
    client,calls=research_setup(tmp_path,backend,**RECALL)
    with client:
        save(client,"Prefer compact research summaries",category="preference")
        r=ask(client,stream=stream)
        assert r.status_code==200
        assert r.headers["x-harness-memory-count"]=="1"
        assert "[DONE]" in r.text if stream else "choices" in r.json()
        assert client.get("/v1/memories/health",headers=HEADERS).json()["recall_profiles"]==["local"]


def test_expired_memory_not_recalled(tmp_path, memory_lab):
    import psycopg
    namespace,_,socket=memory_lab
    client,calls=setup(tmp_path,profile=RECALL)
    with client:
        row=save(client,"Expired telescope code OLD-777",category="preference").json()
        with psycopg.connect(host=socket,dbname="local_ai_memory",autocommit=True) as admin:
            admin.execute("UPDATE harness_memory.memories SET created_at=now()-interval '2 days', expires_at=now()-interval '1 day' WHERE namespace=%s AND memory_id=%s",(namespace,row["memory_id"]))
        r=ask(client,messages=[{"role":"user","content":"telescope code"}])
        assert r.headers["x-harness-memory-status"]=="no_match"
        assert "OLD-777" not in calls[-1].content.decode()
