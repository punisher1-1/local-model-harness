import json
import pytest
import yaml
import psycopg
from uuid import uuid4
from memory import MemoryConfig
from test_app import setup, ask, HEADERS
from test_memory import memory_lab, save
from test_identity import identity_lab, signing_key

@pytest.fixture
def scopes(memory_lab):
    namespace, path, socket = memory_lab
    config = yaml.safe_load(path.read_text())
    config["scope_namespaces"] = {s: namespace + "_" + s for s in ("home", "work")}
    path.write_text(yaml.safe_dump(config))
    yield config
    with psycopg.connect(host=socket, dbname="local_ai_memory", autocommit=True) as conn:
        conn.execute("DELETE FROM harness_memory.memories WHERE namespace = ANY(%s)", (list(config["scope_namespaces"].values()),))

def headers(scope):
    return {**HEADERS, "X-Harness-Memory-Scope": scope}

@pytest.mark.parametrize("scope", ["home", "work"])
def test_scopes_isolate_all_operations_and_recall(tmp_path, scopes, scope):
    client, calls = setup(tmp_path, profile={"memory_recall":{"enabled":True,"scope":scope}})
    ids = {}
    with client:
        key = uuid4()
        for target in ("legacy", "home", "work"):
            r = save(client, "Telescope " + target + " ONLY", category="preference", headers=headers(target), key=key)
            assert r.status_code == 201
            ids[target] = r.json()["memory_id"]
        async def raw_rls_read(target):
            principal=client.app.state.identity.authenticate(HEADERS["Authorization"])
            store=client.app.state.memory.for_scope(principal,target)
            async with store.transaction(principal,"test_rls") as conn:
                return await (await conn.execute("SELECT memory_id FROM harness_memory.memories")).fetchall()
        for target in ids:
            # No WHERE clause: the database itself must restrict the scope.
            assert [str(r["memory_id"]) for r in client.portal.call(raw_rls_read,target)] == [ids[target]]
            assert [r["memory_id"] for r in client.get("/v1/memories",headers=headers(target)).json()["data"]] == [ids[target]]
            result=client.post("/v1/memories/search",headers=headers(target),json={"query":"Telescope"})
            assert [r["memory_id"] for r in result.json()["data"]] == [ids[target]]
        r=client.post("/v1/chat/completions",headers=headers("work" if scope=="home" else "home"),json={"model":"local","messages":[{"role":"user","content":"Tell me about the other lab telescope"}]})
        assert r.status_code==200
        payload=json.loads(calls[-1].content)
        assert "Telescope " + scope + " ONLY" in json.dumps(payload)
        for other in set(ids)-{scope}:
            assert "Telescope " + other + " ONLY" not in json.dumps(payload)
            assert client.delete("/v1/memories/"+ids[other],headers=headers(scope)).status_code==404
        assert client.get("/v1/memories",headers=headers("unknown")).status_code==403
        # Base configuration is unchanged after alternating pool checkouts.
        assert client.app.state.memory.config.namespace==scopes["namespace"]
        assert client.get("/v1/memories/health",headers=headers(scope)).json()["recall_profiles"]==["local"]
        assert client.get("/v1/memories/health",headers=headers("legacy")).json()["recall_profiles"]==[]


def test_jwt_cannot_select_ungranted_scope(tmp_path, scopes, identity_lab):
    path, config, mint=identity_lab
    config["role_grants"]["reader"]["memory_permissions"]=["memory.read","memory.write","memory.delete"]
    config["role_grants"]["reader"]["memory_scopes"]=["home"]
    path.write_text(yaml.safe_dump(config))
    auth={"Authorization":"Bearer "+mint()}
    client,_=setup(tmp_path, profile={"memory_recall":{"enabled":True,"scope":"work"}})
    with client:
        assert client.get("/v1/identity",headers=auth).json()["memory_scopes"]==["home"]
        for scope in ("work","legacy","unknown"):
            h={**auth,"X-Harness-Memory-Scope":scope}
            assert client.get("/v1/memories",headers=h).status_code==403
            assert save(client,headers=h).status_code==403
            assert client.post("/v1/memories/search",headers=h,json={"query":"x"}).status_code==403
            assert client.delete("/v1/memories/"+str(uuid4()),headers=h).status_code==403
        assert client.get("/v1/memories",headers={**auth,"X-Harness-Memory-Scope":"home"}).status_code==200
        assert client.post("/v1/chat/completions",headers=auth,json={"model":"local","messages":[{"role":"user","content":"hello"}]}).status_code==403

@pytest.mark.parametrize("mapping", [{"home":"base"},{"home":"same","work":"same"},{"legacy":"new"},{"home":"bad value"}])
def test_namespace_aliases_rejected(mapping):
    with pytest.raises(ValueError):
        MemoryConfig(namespace="base",host="db",password_file="secret",sslrootcert="ca",scope_namespaces=mapping)
