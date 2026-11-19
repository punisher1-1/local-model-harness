"""Pieces shared by the Hermes MCP servers (Python sandbox and web tools)."""
import hmac


def require_token(app, token):
    """Pure ASGI wrapper: every HTTP request needs Authorization: Bearer <token>."""
    expected = ("Bearer " + token).encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await app(scope, receive, send)
    return guarded
