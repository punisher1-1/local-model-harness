import time

import pytest

import sessions
from identity import Principal
from test_app import setup, HEADERS

CHAT = {"X-Harness-Client": "chat"}


def start(client):
    return client.post("/v1/session", headers={**HEADERS, **CHAT})


def test_session_cookie_is_httponly_strict_and_replaces_the_key(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        r = start(client)
        assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        assert "secure" not in cookie  # plain-HTTP lab access; HTTPS requests get Secure
        assert r.json()["actor_id"] == "lab-service" and r.json()["idle_timeout_seconds"] == 720 * 60
        assert client.get("/v1/profiles", headers=CHAT).json()["data"][0]["id"] == "local"
        assert client.get("/v1/session", headers=CHAT).status_code == 200


def test_cookie_requires_client_header_and_bearer_to_start(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        assert client.post("/v1/session", headers=HEADERS).status_code == 400
        assert client.post("/v1/session", headers={**CHAT, "Authorization": "Bearer wrong-key-value-123456789"}).status_code == 401
        assert start(client).status_code == 201
        # A cross-origin page cannot add the header, so the cookie alone is refused.
        assert client.get("/v1/profiles").status_code == 401
        # A session cannot mint another session without the real credential.
        assert client.post("/v1/session", headers=CHAT).status_code == 401


def test_bearer_credentials_still_work_and_take_precedence(tmp_path):
    client, _ = setup(tmp_path)
    with client:
        start(client)
        assert client.get("/v1/profiles", headers=HEADERS).status_code == 200
        assert client.get("/v1/profiles", headers={**CHAT, "Authorization": "Bearer wrong-key-value-123456789"}).status_code == 401


def test_logout_and_idle_expiry_end_the_session(tmp_path, monkeypatch):
    client, _ = setup(tmp_path)
    with client:
        start(client)
        assert client.delete("/v1/session", headers=CHAT).status_code == 204
        assert client.get("/v1/profiles", headers=CHAT).status_code == 401
        start(client)
        now = time.time()
        monkeypatch.setattr(sessions.time, "time", lambda: now + 720 * 60 + 1)
        r = client.get("/v1/session", headers=CHAT)
        assert r.status_code == 401 and "expired" in r.json()["error"]["message"]


def test_activity_slides_the_idle_window_but_not_the_maximum(monkeypatch):
    store = sessions.SessionStore(600, 3600)
    principal = Principal("service_key", "lab-service", frozenset(), frozenset(), frozenset())
    clock = [1000.0]
    monkeypatch.setattr(sessions.time, "time", lambda: clock[0])
    token = store.create(principal)
    for _ in range(5):
        clock[0] += 500
        assert store.lookup(token) is not None
    clock[0] += 1200  # past the absolute limit even though recently active
    assert store.lookup(token) is None


def test_token_expiry_caps_the_session():
    store = sessions.SessionStore(600, 3600)
    principal = Principal("jwt_subject", "abc", frozenset(), frozenset(), frozenset(), expires_at=int(time.time()) + 120)
    session = store.lookup(store.create(principal))
    assert store.describe(session)["expires_at"] == principal.expires_at


def test_store_is_bounded_and_rejects_bad_settings():
    store = sessions.SessionStore(60, 60)
    principal = Principal("service_key", "lab-service", frozenset(), frozenset(), frozenset())
    tokens = [store.create(principal) for _ in range(sessions.MAX_SESSIONS + 5)]
    assert len(store.items) == sessions.MAX_SESSIONS and store.lookup(tokens[0]) is None
    with pytest.raises(RuntimeError):
        sessions.SessionStore(3600, 60)


def test_session_settings_come_from_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_SESSION_IDLE_MINUTES", "30")
    monkeypatch.setenv("HARNESS_SESSION_MAX_HOURS", "24")
    store = sessions.SessionStore.from_env()
    assert (store.idle, store.max) == (1800, 86400)
    monkeypatch.setenv("HARNESS_SESSION_IDLE_MINUTES", "soon")
    with pytest.raises(RuntimeError):
        sessions.SessionStore.from_env()
