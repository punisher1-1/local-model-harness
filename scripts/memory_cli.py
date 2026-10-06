#!/usr/bin/env python3
"""Explicit memory management; credentials come from the environment, never arguments."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import UUID, uuid4


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("HARNESS_URL", "http://127.0.0.1:8200"))
    parser.add_argument("--scope", default="legacy", help="Authorized memory scope (default: legacy)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("health")
    save = sub.add_parser("save", help="Read exact memory text from stdin")
    save.add_argument("--category", choices=["note", "preference", "fact"], default="note")
    save.add_argument("--idempotency-key", type=UUID)
    save.add_argument("--source-conversation-id")
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--cursor")
    search = sub.add_parser("search", help="Read keyword query from stdin")
    search.add_argument("--limit", type=int, default=10)
    delete = sub.add_parser("delete")
    delete.add_argument("memory_id", type=UUID)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        parser.error("URL must be http(s), without credentials, query, or fragment")
    key = os.getenv("HARNESS_TOKEN") or os.getenv("HARNESS_API_KEY")
    if not key:
        parser.error("Set HARNESS_TOKEN (verified JWT) or HARNESS_API_KEY in the environment")
    path, method, payload = "/v1/memories", "GET", None
    if args.action == "health":
        path += "/health"
    elif args.action == "save":
        identity = str(args.idempotency_key or uuid4())
        # Print before sending so a timed-out request can be retried without duplication.
        print("Save idempotency key: " + identity, file=sys.stderr)
        text = sys.stdin.read(16385)
        payload = {"content": text, "category": args.category, "idempotency_key": identity}
        if args.source_conversation_id:
            payload["source_conversation_id"] = args.source_conversation_id
        method = "POST"
    elif args.action == "list":
        params = {"limit": args.limit}
        if args.cursor:
            params["cursor"] = args.cursor
        path += "?" + urlencode(params)
    elif args.action == "search":
        path += "/search"
        method, payload = "POST", {"query": sys.stdin.read(1025), "limit": args.limit}
    elif args.action == "delete":
        method, path = "DELETE", path + "/" + str(args.memory_id)
    request = Request(args.url.rstrip("/") + path, method=method,
        headers={"X-Harness-Memory-Scope": args.scope, "Authorization": "Bearer " + key, "Content-Type": "application/json"},
        data=json.dumps(payload).encode() if payload is not None else None)
    try:
        # No proxy environment or redirects: don't forward credentials to another endpoint.
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=12) as response:
            body = response.read()
            print(json.dumps(json.loads(body), indent=2) if body else "Deleted.")
    except HTTPError as exc:
        print("HTTP " + str(exc.code) + ": " + exc.read().decode(), file=sys.stderr)
        return 1
    except (URLError, TimeoutError):
        print("Request failed. For saves, retry the same text and idempotency key; the original may have committed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
