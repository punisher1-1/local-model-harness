"""OpenID Connect sign-in for the chat UI (ADR-004).

The harness is the OIDC client. It runs the authorization code flow with PKCE (S256),
state and nonce, exchanges the code server-side, verifies the ID token, and issues its
usual HttpOnly session cookie, so tokens never reach the browser and the harness holds
no passwords. Endpoints and signing keys come from the configured issuer's discovery
document and must be HTTPS on the issuer's own host. An unknown key ID triggers a
rate-limited JWKS refresh, so the provider can rotate keys without a harness restart.
Discovery happens at sign-in, never at startup: a provider outage breaks new sign-ins
only, not the harness.

Logs record outcomes and actor hashes only, never codes, tokens or claims.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from sessions import COOKIE as SESSION_COOKIE

log = logging.getLogger("uvicorn.error")

STATE_COOKIE = "harness_oidc"
LOGIN_SECONDS = 600
MAX_PENDING = 64
CACHE_SECONDS = 3600
KEY_REFRESH_SECONDS = 60
MAX_DOCUMENT_BYTES = 262144
LEEWAY_SECONDS = 60
# The algorithm comes from the trusted key, never from the token header alone.
KEY_ALGORITHMS = {("RSA", None): "RS256", ("EC", "P-256"): "ES256", ("OKP", "Ed25519"): "EdDSA"}
PRIVATE_PARTS = {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}


class SignInError(Exception):
    """A sign-in failure with a short code the UI can explain."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class OIDCClient:
    def __init__(self, config, transport=None):
        self.config = config
        self.secret = os.getenv(config.client_secret_env, "")
        self.transport = transport
        self.meta, self.meta_at = None, 0.0
        self.keys, self.keys_at = {}, 0.0
        self.lock = asyncio.Lock()
        issuer = urlsplit(config.issuer)
        self.host = issuer.hostname

    def http(self):
        return httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False, transport=self.transport)

    async def fetch_json(self, request):
        try:
            async with self.http() as client:
                async with client.stream(**request) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_DOCUMENT_BYTES:
                            raise SignInError("provider_unavailable")
                    status = response.status_code
        except httpx.HTTPError:
            raise SignInError("provider_unavailable") from None
        try:
            data = json.loads(raw)
        except ValueError:
            raise SignInError("provider_unavailable") from None
        if not isinstance(data, dict):
            raise SignInError("provider_unavailable")
        return status, data

    def trusted_endpoint(self, url):
        parts = urlsplit(url) if isinstance(url, str) else None
        return bool(parts) and parts.scheme == "https" and parts.hostname == self.host and not (parts.username or parts.fragment)

    async def metadata(self):
        if self.meta and time.monotonic() - self.meta_at < CACHE_SECONDS:
            return self.meta
        status, data = await self.fetch_json({"method": "GET", "url": self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"})
        if status != 200:
            raise SignInError("provider_unavailable")
        if data.get("issuer") != self.config.issuer:
            raise SignInError("provider_misconfigured")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not self.trusted_endpoint(data.get(key)):
                raise SignInError("provider_misconfigured")
        methods = data.get("code_challenge_methods_supported")
        if methods is not None and "S256" not in methods:
            raise SignInError("provider_misconfigured")
        self.meta, self.meta_at = data, time.monotonic()
        return data

    def parse_key(self, entry):
        if not isinstance(entry, dict) or PRIVATE_PARTS & entry.keys():
            return None
        kid = entry.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 128 or entry.get("use", "sig") != "sig":
            return None
        algorithm = KEY_ALGORITHMS.get((entry.get("kty"), entry.get("crv")))
        if algorithm is None or entry.get("alg", algorithm) != algorithm:
            return None
        try:
            key = jwt.PyJWK.from_dict(entry, algorithm=algorithm).key
        except (jwt.PyJWKError, ValueError, TypeError):
            return None
        if algorithm == "RS256" and key.key_size < 2048:
            return None
        return kid, (key, algorithm)

    async def signing_key(self, kid):
        async with self.lock:
            stale = time.monotonic() - self.keys_at >= CACHE_SECONDS
            # Refresh for a new kid (rotation), but at most once a minute so forged
            # tokens cannot turn the harness into a JWKS request amplifier.
            if (kid not in self.keys or stale) and time.monotonic() - self.keys_at >= KEY_REFRESH_SECONDS:
                meta = await self.metadata()
                status, data = await self.fetch_json({"method": "GET", "url": meta["jwks_uri"]})
                entries = data.get("keys") if status == 200 else None
                if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
                    raise SignInError("provider_unavailable")
                self.keys = dict(filter(None, (self.parse_key(e) for e in entries)))
                self.keys_at = time.monotonic()
            if kid not in self.keys:
                raise SignInError("invalid_token")
            return self.keys[kid]

    async def authorization_url(self, state, nonce, verifier):
        meta = await self.metadata()
        query = {"response_type": "code", "client_id": self.config.client_id, "redirect_uri": self.config.redirect_uri,
                 "scope": " ".join(self.config.scopes), "state": state, "nonce": nonce,
                 "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
        sep = "&" if "?" in meta["authorization_endpoint"] else "?"
        return meta["authorization_endpoint"] + sep + urlencode(query)

    async def exchange(self, code, verifier):
        meta = await self.metadata()
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.config.redirect_uri,
                "code_verifier": verifier, "client_id": self.config.client_id}
        request = {"method": "POST", "url": meta["token_endpoint"], "data": form, "headers": {"Accept": "application/json"}}
        if self.secret:
            request["auth"] = (self.config.client_id, self.secret)
        status, data = await self.fetch_json(request)
        if status != 200 or not isinstance(data.get("id_token"), str):
            raise SignInError("exchange_failed")
        return data["id_token"]

    async def verify(self, id_token, nonce):
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise SignInError("invalid_token") from None
        kid = header.get("kid")
        if not isinstance(kid, str) or header.get("crit") or any(k in header for k in ("jku", "jwk", "x5u", "x5c")):
            raise SignInError("invalid_token")
        key, algorithm = await self.signing_key(kid)
        if header.get("alg") != algorithm:
            raise SignInError("invalid_token")
        try:
            claims = jwt.decode(id_token, key, algorithms=[algorithm], audience=self.config.client_id, issuer=self.config.issuer,
                                leeway=LEEWAY_SECONDS, options={"require": ["exp", "iat", "iss", "aud", "sub"], "strict_aud": False})
        except jwt.PyJWTError:
            raise SignInError("invalid_token") from None
        audience = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if len(audience) > 1 and claims.get("azp") != self.config.client_id:
            raise SignInError("invalid_token")
        if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(claims["nonce"].encode(), nonce.encode()):
            raise SignInError("invalid_token")
        if any(claims.get(k) != v for k, v in self.config.required_claims.items()):
            raise SignInError("no_access")
        return claims


class PendingLogins:
    """Logins in progress: state -> (nonce, PKCE verifier). Held in memory for ten minutes."""

    def __init__(self):
        self.items = {}

    def start(self):
        now = time.monotonic()
        self.items = {k: v for k, v in self.items.items() if now - v[2] < LOGIN_SECONDS}
        while len(self.items) >= MAX_PENDING:
            del self.items[min(self.items, key=lambda k: self.items[k][2])]
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        self.items[hashlib.sha256(state.encode()).hexdigest()] = (nonce, verifier, now)
        return state, nonce, verifier

    def finish(self, state):
        if not isinstance(state, str) or not 16 <= len(state) <= 128:
            return None
        entry = self.items.pop(hashlib.sha256(state.encode()).hexdigest(), None)
        if entry is None or time.monotonic() - entry[2] >= LOGIN_SECONDS:
            return None
        return entry[0], entry[1]


def display_user(claims, roles):
    def text(key, limit):
        value = claims.get(key)
        return value[:limit] if isinstance(value, str) else ""
    return {"name": text("name", 120) or text("preferred_username", 120), "email": text("email", 254),
            "groups": [r for r in roles][:20]}


def install_oidc(app, transport=None):
    pending = PendingLogins()

    def identity():
        return app.state.identity

    def client():
        if getattr(app.state, "oidc", None) is None:
            app.state.oidc = OIDCClient(identity().config, transport)
        return app.state.oidc

    def back_to_chat(error=None):
        response = RedirectResponse("/chat/" + (f"?auth_error={error}" if error else ""), status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.delete_cookie(STATE_COOKIE, path="/v1/auth")
        return response

    @app.get("/v1/auth/config")
    async def auth_config():
        config = identity().config
        oidc = config.mode == "oidc"
        return JSONResponse({"oidc": oidc, "provider": (config.provider_name or "your identity provider") if oidc else None,
                             "key_sign_in": not oidc or (config.allow_key_sign_in and config.service_key is not None)},
                            headers={"Cache-Control": "no-store"})

    @app.get("/v1/auth/login")
    async def login(request: Request):
        if identity().config.mode != "oidc":
            raise HTTPException(404, "Sign-in with an identity provider is not configured")
        state, nonce, verifier = pending.start()
        try:
            url = await client().authorization_url(state, nonce, verifier)
        except SignInError as exc:
            log.warning(json.dumps({"event": "oidc_sign_in", "status": exc.code, "stage": "discovery"}))
            return back_to_chat(exc.code)
        response = RedirectResponse(url, status_code=303)
        response.headers["Cache-Control"] = "no-store"
        # Lax, not Strict: the provider's redirect back is a cross-site top-level navigation.
        response.set_cookie(STATE_COOKIE, state, max_age=LOGIN_SECONDS, path="/v1/auth", httponly=True,
                            samesite="lax", secure=request.url.scheme == "https")
        return response

    @app.get("/v1/auth/callback")
    async def callback(request: Request):
        if identity().config.mode != "oidc":
            raise HTTPException(404, "Sign-in with an identity provider is not configured")
        query = request.query_params
        state = query.get("state")
        cookie = request.cookies.get(STATE_COOKIE)
        # The state must match this browser's cookie as well as a login we started.
        if not state or not cookie or not secrets.compare_digest(state.encode(), cookie.encode()):
            return back_to_chat("expired")
        started = pending.finish(state)
        if started is None:
            return back_to_chat("expired")
        if query.get("error"):
            return back_to_chat("cancelled" if query.get("error") == "access_denied" else "failed")
        code = query.get("code")
        if not code or len(code) > 2048:
            return back_to_chat("failed")
        nonce, verifier = started
        try:
            claims = await client().verify(await client().exchange(code, verifier), nonce)
            roles = identity().roles_of(claims)
            principal = identity().principal_from_claims(claims, None)
        except SignInError as exc:
            log.warning(json.dumps({"event": "oidc_sign_in", "status": exc.code}))
            return back_to_chat(exc.code)
        except (ValueError, TypeError):
            log.warning(json.dumps({"event": "oidc_sign_in", "status": "invalid_token"}))
            return back_to_chat("invalid_token")
        if not principal.profiles:
            log.info(json.dumps({"event": "oidc_sign_in", "status": "no_access", "actor_id": principal.actor_id}))
            return back_to_chat("no_access")
        user = display_user(claims, roles)
        record = getattr(app.state, "record_account", None)
        if record:
            await record(principal, claims["iss"], claims["sub"], user)
        store = app.state.sessions
        token = store.create(principal, user)
        log.info(json.dumps({"event": "oidc_sign_in", "status": "ok", "actor_id": principal.actor_id}))
        response = back_to_chat()
        response.set_cookie(SESSION_COOKIE, token, max_age=int(store.max), path="/", httponly=True,
                            samesite="strict", secure=request.url.scheme == "https")
        return response
