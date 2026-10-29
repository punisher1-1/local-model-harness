"""OIDC sign-in (ADR-004) against a fake provider that signs real ES256 and RS256 tokens."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient

import oidc
from app import create_app

ISSUER = "https://id.example.test"
CLIENT = "harness-client"
REDIRECT = "http://harness.test/v1/auth/callback"
KEY = "test-key-for-harness-1234567890"
UI = {"X-Harness-Client": "chat"}
ALL_TOOLS = ["vault_search", "vault_read_note"]


class Provider:
    """Discovery, JWKS and token endpoints. The test controls every claim and key."""

    def __init__(self):
        self.keys = {"k1": ec.generate_private_key(ec.SECP256R1())}
        self.published = ["k1"]
        self.sign_with = "k1"
        self.claims = {}
        self.nonce = None
        self.challenge = None
        self.token_requests = []
        self.jwks_requests = 0
        self.discovery = {}
        self.token_status = 200

    def jwk(self, kid):
        key = self.keys[kid]
        if isinstance(key, rsa.RSAPrivateKey):
            entry = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        else:
            entry = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
        return {**entry, "kid": kid, "use": "sig"}

    def id_token(self):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT, "sub": "user-alice", "iat": now, "exp": now + 3600, "nonce": self.nonce,
                  "name": "Alice", "email": "alice@example.test", "groups": ["harness-admin"], **self.claims}
        claims = {k: v for k, v in claims.items() if v is not None}
        key = self.keys[self.sign_with]
        alg = "RS256" if isinstance(key, rsa.RSAPrivateKey) else "ES256"
        return jwt.encode(claims, key, algorithm=alg, headers={"kid": self.sign_with})

    def handler(self, request):
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                                             "token_endpoint": ISSUER + "/api/oidc/token", "jwks_uri": ISSUER + "/.well-known/jwks.json",
                                             "code_challenge_methods_supported": ["S256"], **self.discovery})
        if path == "/.well-known/jwks.json":
            self.jwks_requests += 1
            return httpx.Response(200, json={"keys": [self.jwk(k) for k in self.published]})
        if path == "/api/oidc/token":
            form = parse_qs(request.content.decode())
            self.token_requests.append((form, request.headers.get("authorization")))
            verifier = form["code_verifier"][0]
            expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if expected != self.challenge or form["code"] != ["good-code"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(self.token_status, json={"id_token": self.id_token(), "access_token": "unused"})
        return httpx.Response(404)


def grants():
    return {"harness-admin": {"profiles": ["local", "family"], "tools": ALL_TOOLS, "collections": ["local_ai_vault"]},
            "harness-family": {"profiles": ["family"], "memory_scopes": []}}


@pytest.fixture
def lab(tmp_path, monkeypatch):
    def build(**overrides):
        (tmp_path / "prompt.md").write_text("Server policy")
        profile = {"backend_model": "actual-model", "system_prompt_file": "prompt.md", "token_count_mode": "vllm"}
        (tmp_path / "profiles.yaml").write_text(yaml.safe_dump({"profiles": {"local": profile, "family": profile}}))
        identity = {"mode": "oidc", "issuer": ISSUER, "client_id": CLIENT, "redirect_uri": REDIRECT, "provider_name": "Pocket ID",
                    "roles_claim": "groups", "role_grants": grants(),
                    "service_key": {"profiles": ["local"], "tools": [], "collections": []}, **overrides}
        identity = {k: v for k, v in identity.items() if v is not None}
        (tmp_path / "identity.yaml").write_text(yaml.safe_dump(identity))
        monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "chat.sqlite3"))
        provider = Provider()
        provider.backend_calls = []

        def backend(request):
            if request.url.path != "/tokenize":
                provider.backend_calls.append(json.loads(request.content))
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"count": 5})
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}]})
        app = create_app(tmp_path / "profiles.yaml", KEY, "http://backend/v1", httpx.MockTransport(backend),
                         identity_path=tmp_path / "identity.yaml", oidc_transport=httpx.MockTransport(provider.handler))
        return TestClient(app, base_url="http://harness.test"), provider
    return build


def sign_in(client, provider, code="good-code", state=None):
    """Follow the browser through /v1/auth/login and back to the callback."""
    start = client.get("/v1/auth/login", follow_redirects=False)
    assert start.status_code == 303, start.text
    location = urlsplit(start.headers["location"])
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert location.netloc == "id.example.test" and location.path == "/authorize"
    provider.nonce, provider.challenge = query["nonce"], query["code_challenge"]
    return query, client.get("/v1/auth/callback", params={"code": code, "state": state or query["state"]}, follow_redirects=False)


def test_full_sign_in_creates_a_session_with_group_grants(lab):
    client, provider = lab()
    with client:
        assert client.get("/v1/auth/config").json() == {"oidc": True, "provider": "Pocket ID", "key_sign_in": True}
        query, done = sign_in(client, provider)
        assert query["code_challenge_method"] == "S256" and query["scope"] == "openid profile email groups"
        assert query["redirect_uri"] == REDIRECT and query["client_id"] == CLIENT and query["response_type"] == "code"
        assert done.status_code == 303 and done.headers["location"] == "/chat/"
        assert "harness_session" in done.cookies and "HttpOnly" in done.headers["set-cookie"]
        session = client.get("/v1/session", headers=UI).json()
        assert session["kind"] == "jwt_subject" and session["user"] == {"name": "Alice", "email": "alice@example.test", "groups": ["harness-admin"]}
        assert sorted(p["id"] for p in client.get("/v1/profiles", headers=UI).json()["data"]) == ["family", "local"]
        form, auth = provider.token_requests[0]
        assert form["grant_type"] == ["authorization_code"] and form["redirect_uri"] == [REDIRECT] and auth is None


def test_family_group_gets_only_its_profile_and_a_separate_owner(lab):
    client, provider = lab()
    provider.claims = {"sub": "user-wife", "name": "Beth", "groups": ["harness-family"]}
    with client:
        sign_in(client, provider)
        assert [p["id"] for p in client.get("/v1/profiles", headers=UI).json()["data"]] == ["family"]
        assert client.post("/v1/chat/completions", headers=UI, json={"model": "local", "messages": [{"role": "user", "content": "hi"}]}).status_code == 403
        cid = "11111111-1111-4111-8111-111111111111"
        body = {"profile": "family", "title": "Mine", "revision": 0, "messages": []}
        assert client.put("/v1/conversations/" + cid, headers=UI, json=body).status_code == 200
        # The service key is a different owner and cannot see her chat.
        assert client.get("/v1/conversations", headers={"Authorization": "Bearer " + KEY}).json()["data"] == []


def test_confidential_client_sends_its_secret(lab, monkeypatch):
    monkeypatch.setenv("HARNESS_OIDC_CLIENT_SECRET", "s3cret")
    client, provider = lab()
    with client:
        sign_in(client, provider)
        assert provider.token_requests[0][1] == "Basic " + base64.b64encode(f"{CLIENT}:s3cret".encode()).decode()


@pytest.mark.parametrize("claims,error", [
    ({"aud": "someone-else"}, "invalid_token"),
    ({"iss": "https://evil.example.test"}, "invalid_token"),
    ({"exp": int(time.time()) - 600}, "invalid_token"),
    ({"nonce": "replayed"}, "invalid_token"),
    ({"groups": ["unknown-group"]}, "no_access"),
    ({"groups": []}, "no_access"),
    ({"groups": "harness-admin"}, "invalid_token"),
])
def test_bad_tokens_and_ungranted_users_are_refused(lab, claims, error):
    client, provider = lab()
    provider.claims = claims
    with client:
        _, done = sign_in(client, provider)
        assert done.headers["location"] == f"/chat/?auth_error={error}" and "harness_session" not in done.cookies
        assert client.get("/v1/session", headers=UI).status_code == 401


def test_state_must_match_the_browser_and_is_single_use(lab):
    client, provider = lab()
    with client:
        query, done = sign_in(client, provider, state="x" * 32)
        assert done.headers["location"] == "/chat/?auth_error=expired"
        # A second browser without the state cookie cannot finish someone else's login.
        other = TestClient(client.app, base_url="http://harness.test")
        assert other.get("/v1/auth/callback", params={"code": "good-code", "state": query["state"]}, follow_redirects=False).headers["location"] == "/chat/?auth_error=expired"
        query, done = sign_in(client, provider)
        assert done.headers["location"] == "/chat/"
        client.cookies.set("harness_oidc", query["state"], path="/v1/auth")
        again = client.get("/v1/auth/callback", params={"code": "good-code", "state": query["state"]}, follow_redirects=False)
        assert again.headers["location"] == "/chat/?auth_error=expired"


def test_cancel_wrong_code_and_provider_failures(lab):
    client, provider = lab()
    with client:
        start = client.get("/v1/auth/login", follow_redirects=False)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        assert client.get("/v1/auth/callback", params={"error": "access_denied", "state": state}, follow_redirects=False).headers["location"] == "/chat/?auth_error=cancelled"
        _, done = sign_in(client, provider, code="stolen-code")
        assert done.headers["location"] == "/chat/?auth_error=exchange_failed"


@pytest.mark.parametrize("discovery,error", [
    ({"issuer": "https://other.example.test"}, "provider_misconfigured"),
    ({"token_endpoint": "https://attacker.example/token"}, "provider_misconfigured"),
    ({"jwks_uri": "http://id.example.test/jwks"}, "provider_misconfigured"),
    ({"code_challenge_methods_supported": ["plain"]}, "provider_misconfigured"),
])
def test_discovery_must_stay_on_the_issuer(lab, discovery, error):
    client, provider = lab()
    provider.discovery = discovery
    with client:
        assert client.get("/v1/auth/login", follow_redirects=False).headers["location"] == f"/chat/?auth_error={error}"


def test_provider_down_does_not_stop_the_harness(tmp_path, lab):
    client, provider = lab()
    def down(request):
        raise httpx.ConnectError("refused", request=request)
    with client:
        client.app.state.oidc = oidc.OIDCClient(client.app.state.identity.config, httpx.MockTransport(down))
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/auth/login", follow_redirects=False).headers["location"] == "/chat/?auth_error=provider_unavailable"


def test_key_rotation_refreshes_jwks_once_and_rejects_unknown_keys(lab, monkeypatch):
    client, provider = lab()
    with client:
        sign_in(client, provider)
        assert provider.jwks_requests == 1
        provider.keys["k2"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        provider.published, provider.sign_with = ["k1", "k2"], "k2"
        monkeypatch.setattr(oidc, "KEY_REFRESH_SECONDS", 0)
        _, done = sign_in(client, provider)
        assert done.headers["location"] == "/chat/" and provider.jwks_requests == 2
        # A key the provider never published is refused, and refreshes are rate limited.
        monkeypatch.setattr(oidc, "KEY_REFRESH_SECONDS", 3600)
        provider.keys["rogue"] = ec.generate_private_key(ec.SECP256R1())
        provider.sign_with = "rogue"
        _, done = sign_in(client, provider)
        assert done.headers["location"] == "/chat/?auth_error=invalid_token" and provider.jwks_requests == 2


def test_algorithm_must_match_the_published_key(lab):
    client, provider = lab()
    original = provider.id_token

    def hs256_token():
        token = original()
        claims = jwt.decode(token, options={"verify_signature": False})
        return jwt.encode(claims, "guessable-secret-that-is-at-least-32-bytes", algorithm="HS256", headers={"kid": "k1"})
    provider.id_token = hs256_token
    with client:
        _, done = sign_in(client, provider)
        assert done.headers["location"] == "/chat/?auth_error=invalid_token"


def test_service_key_is_scoped_and_can_be_disabled(lab):
    client, provider = lab()
    with client:
        key = {"Authorization": "Bearer " + KEY}
        assert [m["id"] for m in client.get("/v1/models", headers=key).json()["data"]] == ["local"]
        assert client.post("/v1/session", headers={**UI, **key}).status_code == 201
    client, provider = lab(service_key=None)
    with client:
        assert client.get("/v1/models", headers={"Authorization": "Bearer " + KEY}).status_code == 401
        assert client.get("/v1/auth/config").json()["key_sign_in"] is False
    client, provider = lab(allow_key_sign_in=False)
    with client:
        assert client.get("/v1/models", headers={"Authorization": "Bearer " + KEY}).status_code == 200
        assert client.post("/v1/session", headers={**UI, "Authorization": "Bearer " + KEY}).status_code == 403


def test_signed_in_accounts_are_recorded(lab, tmp_path):
    import sqlite3
    client, provider = lab()
    with client:
        sign_in(client, provider)
        provider.claims = {"name": "Alice G"}
        sign_in(client, provider)
    rows = sqlite3.connect(tmp_path / "chat.sqlite3").execute("SELECT issuer,subject,name,email,groups FROM accounts").fetchall()
    assert rows == [(ISSUER, "user-alice", "Alice G", "alice@example.test", '["harness-admin"]')]


@pytest.mark.parametrize("change", [
    {"redirect_uri": "http://harness.test/callback"},
    {"issuer": "http://id.example.test"},
    {"client_id": None},
    {"scopes": ["profile"]},
    {"audience": "api://x"},
    {"role_grants": {"harness-admin": {"profiles": ["missing"]}}},
])
def test_invalid_oidc_configuration_fails_startup(lab, change):
    client, _ = lab(**change)
    with pytest.raises(Exception):
        with client:
            pass


def test_claim_script_moves_shared_data_to_a_signed_in_account(lab, tmp_path, capsys):
    import sqlite3
    import sys as _sys
    _sys.path.insert(0, "scripts")
    import claim_shared_data
    client, provider = lab()
    key = {"Authorization": "Bearer " + KEY}
    cid = "22222222-2222-4222-8222-222222222222"
    with client:
        assert client.put("/v1/conversations/" + cid, headers=key, json={"profile": "local", "title": "Old", "revision": 0, "messages": []}).status_code == 200
        assert client.put("/v1/skills/33333333-3333-4333-8333-333333333333", headers=key, json={"name": "Mine", "content": "Do it."}).status_code == 200
        sign_in(client, provider)
        assert client.get("/v1/conversations", headers=UI).json()["data"] == []
        db = str(tmp_path / "chat.sqlite3")
        assert claim_shared_data.main(["--db", db]) == 0
        listing = capsys.readouterr().out
        assert "1 conversations, 0 projects, 1 user skills" in listing and "Alice <alice@example.test>" in listing
        assert claim_shared_data.main(["--db", db, "--to", "ALICE@example.test"]) == 0
        assert "Dry run only" in capsys.readouterr().out
        assert client.get("/v1/conversations", headers=UI).json()["data"] == []
        assert claim_shared_data.main(["--db", db, "--to", "alice@example.test", "--apply"]) == 0
        assert [c["id"] for c in client.get("/v1/conversations", headers=UI).json()["data"]] == [cid]
        assert [s["name"] for s in client.get("/v1/skills", headers=UI).json()["data"]] == ["Mine"]
        assert client.get("/v1/conversations", headers=key).json()["data"] == []
    with pytest.raises(SystemExit):
        claim_shared_data.main(["--db", db, "--to", "nobody@example.test"])


def test_example_config_is_valid():
    from identity import IdentityConfig
    config = IdentityConfig.model_validate(yaml.safe_load(open("examples/identity.oidc.example.yaml")))
    assert config.mode == "oidc" and config.roles_claim == "groups"
    assert config.role_grants["harness_family"].memory_scopes == ["family-personal", "family-writing"]
    assert all("-" not in name for name in config.role_grants)  # Pocket ID Names use underscores



def test_client_tool_profiles_need_client_tools_in_the_grant(tmp_path, monkeypatch, caplog):
    """Beth's case: her profiles set client_tools, so her group's grant must allow it."""
    def build(family_grant):
        (tmp_path / "prompt.md").write_text("Server policy")
        tools_profile = {"backend_model": "actual-model", "system_prompt_file": "prompt.md", "token_count_mode": "vllm", "client_tools": True}
        (tmp_path / "profiles.yaml").write_text(yaml.safe_dump({"profiles": {"family": tools_profile}}))
        (tmp_path / "identity.yaml").write_text(yaml.safe_dump({"mode": "oidc", "issuer": ISSUER, "client_id": CLIENT, "redirect_uri": REDIRECT,
                                                                 "roles_claim": "groups", "role_grants": {"harness_family": family_grant}}))
        monkeypatch.setenv("HARNESS_CHAT_DB", str(tmp_path / "chat.sqlite3"))
        provider = Provider()
        provider.claims = {"sub": "user-wife", "groups": ["harness_family"]}

        def backend(request):
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"count": 5})
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}],
                                             "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}})
        app = create_app(tmp_path / "profiles.yaml", KEY, "http://backend/v1", httpx.MockTransport(backend),
                         identity_path=tmp_path / "identity.yaml", oidc_transport=httpx.MockTransport(provider.handler))
        return TestClient(app, base_url="http://harness.test"), provider

    ask = {"model": "family", "messages": [{"role": "user", "content": "hi"}]}
    client, provider = build({"profiles": ["family"]})
    with caplog.at_level("WARNING", logger="uvicorn.error"), client:
        assert "harness_family can see family but cannot use them" in caplog.text
        sign_in(client, provider)
        refused = client.post("/v1/chat/completions", headers=UI, json=ask)
        assert refused.status_code == 403 and "Ask your harness admin" in refused.text
    caplog.clear()
    client, provider = build({"profiles": ["family"], "client_tools": True})
    with caplog.at_level("WARNING", logger="uvicorn.error"), client:
        assert "cannot use them" not in caplog.text
        sign_in(client, provider)
        assert client.post("/v1/chat/completions", headers=UI, json=ask).status_code == 200


def test_example_family_grant_allows_client_tools():
    from identity import IdentityConfig
    config = IdentityConfig.model_validate(yaml.safe_load(open("examples/identity.oidc.example.yaml")))
    assert config.role_grants["harness_family"].client_tools is True



def test_startup_warns_when_a_group_cannot_reach_its_profiles_memory():
    """Beth's class profiles: each recalls from its own scope, which her grant must list."""
    from types import SimpleNamespace
    from app import unusable_grants
    from identity import IdentityConfig
    def profile(scope):
        return SimpleNamespace(client_tools=True, memory_recall=SimpleNamespace(enabled=scope is not None, scope=scope))
    profiles = {"personal": profile("beth-personal"), "hr": profile("beth-hr-course"), "plain": profile(None)}
    def config(grant):
        return IdentityConfig.model_validate({"mode": "oidc", "issuer": ISSUER, "client_id": CLIENT, "redirect_uri": REDIRECT,
                                              "role_grants": {"family": grant}, "service_key": {"profiles": ["hr"], "client_tools": True}})
    warnings = list(unusable_grants(config({"profiles": ["personal", "hr", "plain"], "client_tools": True,
                                            "memory_scopes": ["beth-personal"], "memory_permissions": ["memory.read"]}), profiles))
    assert warnings == ["family can see profiles that use memory scopes beth-hr-course but cannot reach them: add them to its memory_scopes"]
    warnings = list(unusable_grants(config({"profiles": ["hr"], "client_tools": True, "memory_scopes": ["beth-hr-course"]}), profiles))
    assert warnings == ["family can see hr, which use memory, but has no memory_permissions"]
    assert list(unusable_grants(config({"profiles": ["personal", "hr"], "client_tools": True,
                                        "memory_scopes": ["beth-personal", "beth-hr-course"], "memory_permissions": ["memory.read"]}), profiles)) == []
