from dataclasses import replace
from uuid import uuid4

import pytest

from test_app import setup, HEADERS

PROFILE = {"backend_model": "actual-model", "system_prompt_file": "prompt.md", "rules": ["Do not fabricate"], "token_count_mode": "vllm"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "history.sqlite3"))
    client, _ = setup(tmp_path, settings={"profiles": {"local": PROFILE, "bench": PROFILE}})
    with client:
        yield client


def chat(client, profile="local"):
    cid = str(uuid4())
    r = client.put("/v1/conversations/" + cid, headers=HEADERS, json={"profile": profile, "title": "t", "revision": 0, "messages": []})
    assert r.status_code == 200
    return cid


def ids(client):
    return {row["id"] for row in client.get("/v1/conversations", headers=HEADERS).json()["data"]}


def as_other(client, monkeypatch, **changes):
    identity = client.app.state.identity
    principal = replace(identity.authenticate(HEADERS["Authorization"]), **changes)
    monkeypatch.setattr(identity, "authenticate", lambda _: principal)


def test_bulk_delete_removes_only_the_listed_chats(client):
    a, b, keep = chat(client), chat(client, "bench"), chat(client)
    r = client.post("/v1/conversations/delete", headers=HEADERS, json={"ids": [a, b, a, str(uuid4())]})
    assert r.status_code == 200 and sorted(r.json()["deleted"]) == sorted([a, b])
    assert ids(client) == {keep}


@pytest.mark.parametrize("body", [{"ids": []}, {"ids": ["nope"]}, {"ids": [str(uuid4())] * 1001}, {"ids": [str(uuid4())], "x": 1}])
def test_bulk_delete_validates(client, body):
    assert client.post("/v1/conversations/delete", headers=HEADERS, json=body).status_code in {400, 413}


def test_bulk_delete_skips_other_owners_and_ungranted_profiles(client, monkeypatch):
    mine, bench = chat(client), chat(client, "bench")
    as_other(client, monkeypatch, actor_id="other")
    assert client.post("/v1/conversations/delete", headers=HEADERS, json={"ids": [mine]}).json()["deleted"] == []
    monkeypatch.undo()
    as_other(client, monkeypatch, profiles=frozenset({"local"}))
    assert client.post("/v1/conversations/delete", headers=HEADERS, json={"ids": [mine, bench]}).json()["deleted"] == [mine]
    monkeypatch.undo()
    assert ids(client) == {bench}


def test_hidden_profiles_are_saved_per_person(client, monkeypatch):
    assert client.get("/v1/preferences", headers=HEADERS).json() == {"hidden_profiles": []}
    r = client.put("/v1/preferences", headers=HEADERS, json={"hidden_profiles": ["bench", "bench"]})
    assert r.status_code == 200 and r.json() == {"hidden_profiles": ["bench"]}
    assert client.get("/v1/preferences", headers=HEADERS).json() == {"hidden_profiles": ["bench"]}
    # Hiding is display only: chats on the profile still save and the catalog still lists it.
    chat(client, "bench")
    assert {p["id"] for p in client.get("/v1/profiles", headers=HEADERS).json()["data"]} == {"local", "bench"}
    as_other(client, monkeypatch, actor_id="other")
    assert client.get("/v1/preferences", headers=HEADERS).json() == {"hidden_profiles": []}
    # A profile no longer granted drops out of the saved list.
    monkeypatch.undo()
    as_other(client, monkeypatch, profiles=frozenset({"local"}))
    assert client.get("/v1/preferences", headers=HEADERS).json() == {"hidden_profiles": []}


@pytest.mark.parametrize("hidden,status", [(["local", "bench"], 409), (["nope"], 400), ([""], 400)])
def test_hiding_needs_known_profiles_and_one_left(client, hidden, status):
    assert client.put("/v1/preferences", headers=HEADERS, json={"hidden_profiles": hidden}).status_code == status


@pytest.mark.parametrize("path,method", [("/v1/conversations/delete", "post"), ("/v1/preferences", "put")])
def test_oversized_bodies_are_refused(client, path, method):
    r = getattr(client, method)(path, headers={**HEADERS, "Content-Type": "application/json"}, content=b" " * 70000)
    assert r.status_code == 413
