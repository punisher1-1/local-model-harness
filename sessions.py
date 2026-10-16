"""Browser sessions for the built-in chat UI.

The UI exchanges a harness credential once for an opaque HttpOnly cookie, so a
page reload does not discard the sign-in and the key never stays in page memory.
Sessions live in process memory: a restart or redeploy signs everyone out, and
a rotated API key cannot outlive the process. Cookie-authenticated requests must
also send X-Harness-Client, which cross-origin pages cannot add without a CORS
preflight that the harness never grants.
"""
from dataclasses import dataclass
import hashlib
import os
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

COOKIE = "harness_session"
CLIENT_HEADER = "x-harness-client"
CLIENT_VALUE = "chat"
MAX_SESSIONS = 256


@dataclass
class Session:
    principal: object
    last_seen: float
    expires_at: float


class SessionStore:
    def __init__(self, idle_seconds, max_seconds):
        if not 60 <= idle_seconds <= max_seconds:
            raise RuntimeError("Session idle timeout must be at least one minute and no longer than the maximum lifetime")
        self.idle = idle_seconds
        self.max = max_seconds
        self.items = {}

    @classmethod
    def from_env(cls):
        try:
            idle = float(os.getenv("HARNESS_SESSION_IDLE_MINUTES", "720")) * 60
            lifetime = float(os.getenv("HARNESS_SESSION_MAX_HOURS", "168")) * 3600
        except ValueError:
            raise RuntimeError("HARNESS_SESSION_IDLE_MINUTES and HARNESS_SESSION_MAX_HOURS must be numbers") from None
        return cls(idle, lifetime)

    @staticmethod
    def key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def live(self, session, now):
        return now < session.expires_at and now - session.last_seen < self.idle

    def create(self, principal):
        now = time.time()
        self.items = {k: s for k, s in self.items.items() if self.live(s, now)}
        while len(self.items) >= MAX_SESSIONS:
            del self.items[min(self.items, key=lambda k: self.items[k].last_seen)]
        expires = now + self.max
        if principal.expires_at is not None:
            expires = min(expires, principal.expires_at)
        token = secrets.token_urlsafe(32)
        self.items[self.key(token)] = Session(principal, now, expires)
        return token

    def lookup(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            return None
        key = self.key(token)
        session = self.items.get(key)
        now = time.time()
        if session is None or not self.live(session, now):
            self.items.pop(key, None)
            return None
        session.last_seen = now
        return session

    def delete(self, token):
        if isinstance(token, str):
            self.items.pop(self.key(token), None)

    def describe(self, session):
        p = session.principal
        return {"kind": p.kind, "actor_id": p.actor_id, "expires_at": int(session.expires_at),
                "idle_expires_at": int(min(session.expires_at, session.last_seen + self.idle)),
                "idle_timeout_seconds": int(self.idle)}

    def authenticate(self, request):
        if request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
            raise HTTPException(401, "Session requests must come from the harness chat client")
        session = self.lookup(request.cookies.get(COOKIE))
        if session is None:
            raise HTTPException(401, "Session expired; sign in again")
        session.principal.ensure_current()
        request.state.session = session
        return session.principal


def install_sessions(app):
    def response(data, status=200):
        return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})

    @app.post("/v1/session")
    async def start(request: Request):
        if request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
            raise HTTPException(400, "Sessions are only issued to the harness chat client")
        # Only a bearer credential can open a session; an existing cookie cannot extend itself.
        principal = app.state.identity.authenticate(request.headers.get("authorization", ""))
        principal.ensure_current()
        store = app.state.sessions
        token = store.create(principal)
        result = response(store.describe(store.lookup(token)), 201)
        result.set_cookie(COOKIE, token, max_age=int(store.max), path="/", httponly=True,
                          samesite="strict", secure=request.url.scheme == "https")
        return result

    @app.get("/v1/session")
    async def current(request: Request):
        app.state.sessions.authenticate(request)
        return response(app.state.sessions.describe(request.state.session))

    @app.delete("/v1/session")
    async def end(request: Request):
        app.state.sessions.delete(request.cookies.get(COOKIE))
        result = Response(status_code=204, headers={"Cache-Control": "no-store"})
        result.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return result
