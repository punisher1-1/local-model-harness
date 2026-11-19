"""Unit checks plus opt-in real PostgreSQL tests against a disposable cluster only."""
import json
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
import pytest
import yaml

from memory import MemoryConfig, SaveMemory, permissions, decode_cursor
from identity import Principal
from test_app import setup, ask, HEADERS
from test_identity import identity_lab, signing_key


def test_disabled_memory_preserves_chat(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        assert client.get("/v1/memories").status_code == 401
        assert client.get("/v1/memories", headers=HEADERS).status_code == 503
        assert client.get("/v1/identity", headers=HEADERS).json()["memory_permissions"] == []
        assert ask(client).status_code == 200


@pytest.mark.parametrize("extra", [{"owner_id": "other"}, {"namespace": "other"}, {"expires_at": "2099-01-01"},
    {"content": " "}, {"content": "é" * 4097}, {"content": "bad\x00value"}, {"category": "system"}])
def test_strict_memory_body(extra):
    with pytest.raises(ValueError):
        SaveMemory.model_validate_json(json.dumps({"content": "test", "idempotency_key": str(uuid4()), **extra}))


def test_config_requires_separate_role_and_tls(tmp_path):
    base = {"namespace": "test", "host": "10.0.0.67", "password_file": "secret", "sslrootcert": "ca"}
    for extra in ({"user": "ragapp"}, {"database": "myragdatabase"}, {"sslmode": "disable"}, {"host": "x password=evil"}):
        with pytest.raises(ValueError):
            MemoryConfig.model_validate({**base, **extra})
    config = MemoryConfig.model_validate(base)
    principal = Principal("service_key", "lab-service", frozenset(), frozenset(), frozenset())
    assert not permissions(config, principal)
    config.allow_shared_service_identity = True
    assert "memory.delete" in permissions(config, principal)


@pytest.mark.parametrize("cursor", ["?", "e30=", "W10=", "x" * 257])
def test_invalid_cursor(cursor):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        decode_cursor(cursor)


@pytest.fixture
def memory_lab(tmp_path, monkeypatch):
    socket = os.getenv("HARNESS_TEST_MEMORY_SOCKET")
    if not socket:
        pytest.skip("Set HARNESS_TEST_MEMORY_SOCKET to a disposable PostgreSQL socket directory")
    assert socket.startswith("/private/tmp/"), "Tests must not target the lab database"
    namespace = "test_" + uuid4().hex
    config = {"namespace": namespace, "host": "unused.test", "password_file": "unused",
        "sslrootcert": "unused", "allow_shared_service_identity": True}
    path = tmp_path / "memory.yaml"
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("HARNESS_MEMORY_CONFIG", str(path))
    # Production has no plaintext option. Only this test substitutes a local socket pool.
    def test_pool(_):
        return AsyncConnectionPool(open=False, min_size=0, max_size=1, timeout=1, max_waiting=8,
            kwargs={"host": socket, "dbname": "local_ai_memory", "user": "harness_memory_app",
                    "autocommit": True, "row_factory": dict_row})
    monkeypatch.setattr("memory.make_pool", test_pool)
    yield namespace, path, socket
    with psycopg.connect(host=socket, dbname="local_ai_memory", autocommit=True) as admin:
        admin.execute("DELETE FROM harness_memory.memories WHERE namespace = %s", (namespace,))


def save(client, text="Synthetic memory: prefer concise explanations", headers=HEADERS, key=None, **extra):
    return client.post("/v1/memories", headers=headers, json={"content": text, "idempotency_key": str(key or uuid4()), **extra})


def test_persistence_search_replay_conflict_delete(tmp_path, memory_lab, caplog):
    client, calls = setup(tmp_path)
    key = uuid4()
    with client, caplog.at_level("INFO", logger="uvicorn.error"):
        assert client.get("/v1/memories/health", headers=HEADERS).json()["automatic_recall"] is False
        first = save(client, key=key)
        assert first.status_code == 201, first.text
        row = first.json()
        assert row["expires_at"] is None
        assert "owner_id" not in row and "namespace" not in row
        replay = save(client, key=key)
        assert replay.status_code == 200 and replay.json() == row
        assert save(client, "Different content", key=key).status_code == 409
        found = client.post("/v1/memories/search", headers=HEADERS, json={"query": "concise explanations"})
        assert [r["memory_id"] for r in found.json()["data"]] == [row["memory_id"]]
        assert client.post("/v1/memories/search", headers=HEADERS, json={"query": "nothingmatching"}).json()["data"] == []
        assert ask(client).status_code == 200
        assert "Synthetic memory" not in calls[-1].content.decode()  # no automatic recall
    # A new app and connection pool must retrieve the same persistent row.
    client2, _ = setup(tmp_path)
    with client2:
        assert client2.get("/v1/memories", headers=HEADERS).json()["data"] == [row]
        assert client2.delete("/v1/memories/" + row["memory_id"], headers=HEADERS).status_code == 204
        assert client2.delete("/v1/memories/" + row["memory_id"], headers=HEADERS).status_code == 404
        assert client2.get("/v1/memories", headers=HEADERS).json()["data"] == []
    assert "Synthetic memory" not in caplog.text
    assert '"event": "memory_operation"' in caplog.text


def test_boundaries_pagination_and_injection(tmp_path, memory_lab):
    client, _ = setup(tmp_path)
    with client:
        for text in ("é" * 4096, "'); DROP TABLE harness_memory.memories; --", "third"):
            assert save(client, text).status_code == 201
        first = client.get("/v1/memories?limit=2", headers=HEADERS).json()
        assert len(first["data"]) == 2 and first["next_cursor"]
        second = client.get("/v1/memories", headers=HEADERS, params={"limit": 2, "cursor": first["next_cursor"]}).json()
        assert len(second["data"]) == 1 and second["next_cursor"] is None
        assert len({r["memory_id"] for r in first["data"] + second["data"]}) == 3
        for params in ({"owner_id": "other"}, {"limit": 0}, {"limit": 101}, {"cursor": "bad"}):
            assert client.get("/v1/memories", headers=HEADERS, params=params).status_code == 400
        assert save(client, owner_id="forged").status_code == 400
        assert save(client, "é" * 4097).status_code == 400
        assert client.post("/v1/memories", headers=HEADERS, content="x" * 16385).status_code == 413
        assert client.delete("/v1/memories/nope", headers=HEADERS).status_code == 400


def test_jwt_permissions_and_pool_scope(tmp_path, memory_lab, identity_lab):
    path, config, mint = identity_lab
    config["role_grants"]["reader"]["memory_permissions"] = ["memory.read", "memory.write", "memory.delete"]
    config["role_grants"]["chat"]["memory_permissions"] = ["memory.read"]
    path.write_text(yaml.safe_dump(config))
    alice = {"Authorization": "Bearer " + mint()}
    bob = {"Authorization": "Bearer " + mint({"sub": "synthetic-user-b"})}
    read_only = {"Authorization": "Bearer " + mint({"roles": ["chat"]})}
    denied = {"Authorization": "Bearer " + mint({"roles": ["searcher"]})}
    client, _ = setup(tmp_path)
    with client:
        key = uuid4()
        row = save(client, headers=alice, key=key).json()
        assert client.get("/v1/memories", headers=bob).json()["data"] == []
        assert client.post("/v1/memories/search", headers=bob, json={"query": "concise"}).json()["data"] == []
        assert client.delete("/v1/memories/" + row["memory_id"], headers=bob).status_code == 404
        assert save(client, "Bob's independent memory", headers=bob, key=key).status_code == 201
        assert len(client.get("/v1/memories", headers=alice).json()["data"]) == 1
        assert client.get("/v1/memories", headers=read_only).status_code == 200
        assert save(client, headers=read_only).status_code == 403
        assert client.delete("/v1/memories/" + row["memory_id"], headers=read_only).status_code == 403
        assert client.get("/v1/memories", headers=denied).status_code == 403
        assert client.get("/v1/identity", headers=alice).json()["memory_permissions"] == ["memory.delete", "memory.read", "memory.write"]


def test_shared_identity_requires_explicit_opt_in(tmp_path, memory_lab):
    _, path, _ = memory_lab
    config = yaml.safe_load(path.read_text())
    config["allow_shared_service_identity"] = False
    path.write_text(yaml.safe_dump(config))
    client, _ = setup(tmp_path)
    with client:
        assert save(client).status_code == 403
        assert client.get("/v1/memories", headers=HEADERS).status_code == 403
        assert ask(client).status_code == 200


def test_database_outage_does_not_break_chat(tmp_path, memory_lab, monkeypatch):
    from contextlib import asynccontextmanager
    from psycopg_pool import PoolTimeout
    @asynccontextmanager
    async def unavailable(*args, **kwargs):
        raise PoolTimeout("private connection details must not escape")
        yield
    client, _ = setup(tmp_path)
    with client:
        monkeypatch.setattr(client.app.state.memory.pool, "connection", unavailable)
        r = save(client)
        assert r.status_code == 503 and "private connection details" not in r.text
        assert ask(client).status_code == 200


def test_pool_context_clears_after_commit_and_rollback(tmp_path, memory_lab):
    _, _, socket = memory_lab
    client, _ = setup(tmp_path)
    with client:
        row = save(client).json()
        assert save(client, "Conflict", key=row["idempotency_key"]).status_code == 409
        # Use the same single-connection pool through the TestClient's event loop.
        async def check():
            async with client.app.state.memory.pool.connection() as conn:
                state = await (await conn.execute("SELECT nullif(current_setting('harness.owner_id', true), '') AS owner")).fetchone()
                assert state["owner"] is None
                assert await (await conn.execute("SELECT memory_id FROM harness_memory.memories")).fetchall() == []
        client.portal.call(check)


def test_concurrent_duplicate_saves(tmp_path, memory_lab):
    import asyncio
    client, _ = setup(tmp_path)
    with client:
        async def exercise():
            store = client.app.state.memory
            await store.pool.resize(0, 4)
            principal = client.app.state.identity.authenticate(HEADERS["Authorization"])
            body = SaveMemory(content="Concurrent synthetic save", idempotency_key=uuid4())
            results = await asyncio.gather(*(store.save(principal, body) for _ in range(8)))
            assert sum(created for _, created in results) == 1
            assert len({row["memory_id"] for row, _ in results}) == 1
        client.portal.call(exercise)


def test_database_policy_change_fails_closed(tmp_path, memory_lab):
    _, _, socket = memory_lab
    client, _ = setup(tmp_path)
    with client, psycopg.connect(host=socket, dbname="local_ai_memory", autocommit=True) as admin:
        try:
            admin.execute("ALTER TABLE harness_memory.memories DISABLE ROW LEVEL SECURITY")
            assert client.get("/v1/memories/health", headers=HEADERS).status_code == 503
            assert ask(client).status_code == 200
        finally:
            admin.execute("ALTER TABLE harness_memory.memories ENABLE ROW LEVEL SECURITY")
        assert client.get("/v1/memories/health", headers=HEADERS).status_code == 200
