"""Web search and page reading MCP server for the local model harness.

Runs on the Hermes VM next to the Python sandbox, under its own service user. Three tools:
web_search queries the Brave Search API (the key lives only on this host), web_context asks
Brave's LLM Context API for the query-relevant passages of the top pages, and web_read
fetches one public page as plain text. Hermes' firewall blocks connections into the lab,
and web_read also refuses any URL that resolves to a private, loopback, link-local or
reserved address, including after redirects. The harness on the harness host is the only client.

Logs hold metadata only (tool, status, counts, host), never queries or page text.
"""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import json
import logging
import os
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from common import require_token

log = logging.getLogger("harness-web")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
BRAVE_KEY = os.getenv("BRAVE_API_KEY", "")
DAILY_SEARCH_LIMIT = int(os.getenv("WEB_DAILY_SEARCH_LIMIT", "300"))
MAX_CONCURRENT = int(os.getenv("WEB_MAX_CONCURRENT", "4"))
MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_CHARS = 16000
# web_context: Brave's token budget is approximate, so characters are capped here too.
CONTEXT_URLS = 8
CONTEXT_SNIPPET_CHARS = 4000
CONTEXT_TOTAL_CHARS = 32000
FRESHNESS = ("pd", "pw", "pm", "py")
MAX_REDIRECTS = 5
TIMEOUT = 15
USER_AGENT = "LocalModelHarness/1.0 (personal research assistant)"
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/json", "text/markdown", "application/xml", "text/xml")

_slots = asyncio.Semaphore(MAX_CONCURRENT)
_usage = {"day": None, "count": 0}


class Refused(ValueError):
    """A URL or response the reader will not handle; the message is a fixed code."""


def clean(text, limit):
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def take_search_slot(now=None):
    day = (now or datetime.now(timezone.utc)).date()
    if _usage["day"] != day:
        _usage.update(day=day, count=0)
    if _usage["count"] >= DAILY_SEARCH_LIMIT:
        return False
    _usage["count"] += 1
    return True


async def brave_search(query, count, client):
    response = await client.get(BRAVE_URL, params={"q": query, "count": count, "extra_snippets": "true",
                                                   "safesearch": "moderate", "text_decorations": "false"},
                                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_KEY})
    if response.status_code == 429:
        return {"error": "search_rate_limited"}
    if response.status_code != 200:
        return {"error": "search_failed"}
    results = []
    for item in (response.json().get("web") or {}).get("results", [])[:count]:
        url = item.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"}:
            continue
        results.append({"title": clean(item.get("title"), 200), "url": url[:2048],
                        "snippet": clean(item.get("description"), 600),
                        "extra_snippets": [clean(x, 400) for x in (item.get("extra_snippets") or [])[:3]],
                        "age": clean(item.get("age") or item.get("page_age"), 40)})
    return {"source": "brave", "results": results}


def trim(text, limit):
    # Snippets can be code or JSON-serialized tables, so whitespace and angle brackets are kept.
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


async def brave_context(query, max_tokens, freshness, client):
    params = {"q": query, "count": 20, "maximum_number_of_urls": CONTEXT_URLS,
              "maximum_number_of_tokens": max_tokens,
              # Half the budget per page, so at least two sources can contribute.
              "maximum_number_of_tokens_per_url": max(512, max_tokens // 2),
              "context_threshold_mode": "balanced", "safesearch": "moderate"}
    if freshness:
        params["freshness"] = freshness
    response = await client.get(BRAVE_CONTEXT_URL, params=params,
                                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_KEY})
    if response.status_code == 429:
        return {"error": "search_rate_limited"}
    if response.status_code != 200:
        return {"error": "search_failed"}
    data = response.json()
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    results, budget = [], CONTEXT_TOTAL_CHARS
    for item in ((data.get("grounding") or {}).get("generic") or [])[:CONTEXT_URLS]:
        url = item.get("url") if isinstance(item, dict) else None
        if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"}:
            continue
        snippets = []
        for raw in item["snippets"] if isinstance(item.get("snippets"), list) else []:
            if budget <= 0:
                break
            text = trim(raw if isinstance(raw, str) else json.dumps(raw), min(CONTEXT_SNIPPET_CHARS, budget))
            if text:
                snippets.append(text)
                budget -= len(text)
        if not snippets:
            continue
        age = (sources.get(url) or {}).get("age") if isinstance(sources.get(url), dict) else None
        # Brave's age list is [full date, YYYY-MM-DD, relative, ISO]; the short date is enough.
        results.append({"title": clean(item.get("title"), 200), "url": url[:2048], "snippets": snippets,
                        "age": clean(age[1] if isinstance(age, list) and len(age) > 1 else "", 40)})
    return {"source": "brave_context", "results": results, "truncated": budget <= 0}


def check_url(url, resolve=socket.getaddrinfo):
    """Allow only http(s) on default ports whose every address is public."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise Refused("unsupported_url")
    if parts.port not in (None, 80, 443):
        raise Refused("unsupported_port")
    try:
        infos = resolve(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError:
        raise Refused("dns_failed") from None
    addresses = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    if not addresses or any(not a.is_global or a.is_multicast for a in addresses):
        raise Refused("private_address")
    return parts.hostname


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "footer", "form"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "blockquote", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.skip, self.in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)

    def text(self):
        lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in "".join(self.parts).splitlines())
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html):
    parser = TextExtractor()
    parser.feed(html)
    parser.close()
    return clean(parser.title, 300), parser.text()


async def read_page(url, client, resolve=socket.getaddrinfo):
    for _ in range(MAX_REDIRECTS + 1):
        await asyncio.to_thread(check_url, url, resolve)
        async with client.stream("GET", url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"}) as response:
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue
            if response.status_code != 200:
                return {"error": "http_status", "status": response.status_code}
            kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if kind and kind not in TEXT_TYPES:
                return {"error": "unsupported_content_type", "content_type": kind[:100]}
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_PAGE_BYTES:
                    break
            raw = bytes(body[:MAX_PAGE_BYTES]).decode(response.encoding or "utf-8", errors="replace")
        if kind in ("text/html", "application/xhtml+xml") or (not kind and "<html" in raw[:2000].lower()):
            title, text = html_to_text(raw)
        else:
            title, text = "", raw.strip()
        return {"source": "web", "url": url[:2048], "title": title, "text": text[:MAX_TEXT_CHARS],
                "truncated": len(text) > MAX_TEXT_CHARS or len(body) > MAX_PAGE_BYTES}
    return {"error": "too_many_redirects"}


def build_server(allowed_hosts, client_factory=None):
    client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False))
    mcp = FastMCP("harness-web", stateless_http=True, json_response=True,
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts))

    async def guarded(tool, work):
        started = time.monotonic()
        if _slots.locked():
            result = {"error": "web_busy"}
        else:
            async with _slots:
                try:
                    async with client_factory() as client:
                        result = await asyncio.wait_for(work(client), TIMEOUT * 2)
                except Refused as exc:
                    result = {"error": str(exc)}
                except (httpx.HTTPError, asyncio.TimeoutError, ValueError):
                    result = {"error": "fetch_failed"}
        log.info(json.dumps({"event": tool, "status": result.get("error", "ok"),
                             "results": len(result.get("results", [])) if "results" in result else None,
                             "host": urlsplit(result.get("url", "")).hostname, "duration_ms": round((time.monotonic() - started) * 1000)}))
        return json.dumps(result)

    @mcp.tool()
    async def web_search(query: str, count: int = 5) -> str:
        """Search the web with Brave. Returns titles, URLs, snippets and extra snippets for up to 8 results."""
        if not 1 <= len(query.strip()) <= 400 or not 1 <= count <= 8:
            return json.dumps({"error": "invalid_arguments"})
        if not take_search_slot():
            return json.dumps({"error": "daily_search_limit"})
        return await guarded("web_search", lambda client: brave_search(query.strip(), count, client))

    @mcp.tool()
    async def web_context(query: str, max_tokens: int = 2048, freshness: str = "") -> str:
        """Search the web with Brave and return the query-relevant passages of up to 8 pages."""
        if not 1 <= len(query.strip()) <= 400 or not 1024 <= max_tokens <= 8192 or freshness not in ("", *FRESHNESS):
            return json.dumps({"error": "invalid_arguments"})
        if not take_search_slot():
            return json.dumps({"error": "daily_search_limit"})
        return await guarded("web_context", lambda client: brave_context(query.strip(), max_tokens, freshness, client))

    @mcp.tool()
    async def web_read(url: str) -> str:
        """Fetch one public web page and return its readable text (up to 16,000 characters)."""
        if not 1 <= len(url) <= 2048:
            return json.dumps({"error": "invalid_arguments"})
        return await guarded("web_read", lambda client: read_page(url, client))

    return mcp


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    token = os.getenv("WEB_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("Set WEB_TOKEN to a random secret of at least 24 characters")
    if not BRAVE_KEY:
        raise SystemExit("Set BRAVE_API_KEY")
    port = int(os.getenv("WEB_PORT", "8203"))
    allowed = [h.strip() for h in os.getenv("WEB_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*").split(",") if h.strip()]
    log.info(json.dumps({"event": "start", "port": port, "daily_search_limit": DAILY_SEARCH_LIMIT}))
    uvicorn.run(require_token(build_server(allowed).streamable_http_app(), token),
                host=os.getenv("WEB_BIND", "0.0.0.0"), port=port, log_level="warning")


if __name__ == "__main__":
    main()
