from uuid import uuid4

import pytest

import conversation_store
from test_app import setup, HEADERS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "history.sqlite3"))
    client, _ = setup(tmp_path)
    with client:
        yield client


def project(client, pid=None, **fields):
    pid = pid or str(uuid4())
    body = {"name": "IT301", "profile": "local", "skill": "notes", "mcp_servers": ["rag", "vault"], **fields}
    return pid, client.put("/v1/projects/" + pid, headers=HEADERS, json=body)


def chat(client, cid=None, revision=0, **fields):
    cid = cid or str(uuid4())
    body = {"profile": "local", "title": "Reserves", "revision": revision, "messages": [], **fields}
    return cid, client.put("/v1/conversations/" + cid, headers=HEADERS, json=body)


def listing(client):
    return {row["id"]: row for row in client.get("/v1/conversations", headers=HEADERS).json()["data"]}


def test_projects_store_defaults_and_list_by_name(client):
    pid, r = project(client)
    assert r.status_code == 200 and r.json()["mcp_servers"] == ["rag", "vault"] and r.json()["skill"] == "notes"
    project(client, name="home lab")
    project(client, pid, name="IT301 Project Management", mcp_servers=[])
    rows = client.get("/v1/projects", headers=HEADERS).json()["data"]
    assert [p["name"] for p in rows] == ["home lab", "IT301 Project Management"]
    assert rows[1]["id"] == pid and rows[1]["mcp_servers"] == []


def test_chats_join_projects_and_keep_the_link(client):
    pid, _ = project(client)
    cid, r = chat(client, project_id=pid)
    assert r.status_code == 200
    assert listing(client)[cid]["project_id"] == pid
    assert client.get("/v1/conversations/" + cid, headers=HEADERS).json()["project_id"] == pid
    chat(client, cid, revision=1, project_id=None)
    assert listing(client)[cid]["project_id"] is None


def test_deleting_a_project_keeps_its_chats_ungrouped(client):
    pid, _ = project(client)
    cid, _ = chat(client, project_id=pid)
    assert client.delete("/v1/projects/" + pid, headers=HEADERS).status_code == 204
    assert client.get("/v1/projects", headers=HEADERS).json()["data"] == []
    row = listing(client)[cid]
    assert row["project_id"] is None and row["revision"] == 1
    assert client.delete("/v1/projects/" + pid, headers=HEADERS).status_code == 404
    # A tab still holding the deleted project saves without error and stays ungrouped.
    _, r = chat(client, cid, revision=1, project_id=pid)
    assert r.status_code == 200 and listing(client)[cid]["project_id"] is None


def test_unknown_project_links_are_dropped(client):
    cid, r = chat(client, project_id=str(uuid4()))
    assert r.status_code == 200 and listing(client)[cid]["project_id"] is None
    _, r = chat(client, project_id="not-a-uuid")
    assert r.status_code == 400


@pytest.mark.parametrize("fields,status", [
    ({"name": ""}, 400),
    ({"name": "x" * 81}, 400),
    ({"profile": "nope"}, 403),
    ({"mcp_servers": ["vault", "vault"]}, 400),
    ({"mcp_servers": ["a"] * 9}, 400),
    ({"extra": 1}, 400),
])
def test_projects_are_validated(client, fields, status):
    assert project(client, **fields)[1].status_code == status


def test_project_limit(client, monkeypatch):
    monkeypatch.setattr(conversation_store, "MAX_PROJECTS", 2)
    pid, _ = project(client)
    project(client)
    assert project(client)[1].status_code == 409
    assert project(client, pid, name="renamed")[1].status_code == 200
