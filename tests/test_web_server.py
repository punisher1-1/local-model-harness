"""Web tools server: SSRF guards, page extraction, Brave mapping and limits, all with mocked HTTP."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import socket
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sandbox"))
import web_server as web  # noqa: E402

PUBLIC = "93.184.216.34"


def resolver(table):
    def resolve(host, port, proto=None):
        if host not in table:
            raise socket.gaierror("unknown")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]
    return resolve


@pytest.mark.parametrize("url,code", [
    ("ftp://example.com/x", "unsupported_url"),
    ("http://user:pw@example.com/", "unsupported_url"),
    ("http://example.com:8080/", "unsupported_port"),
    ("http://localhost/", "private_address"),
    ("http://lab.internal/", "private_address"),
    ("http://metadata/", "private_address"),
    ("http://v6local/", "private_address"),
    ("http://mixed.example/", "private_address"),
    ("http://nowhere.example/", "dns_failed"),
])
def test_urls_that_could_reach_the_lab_are_refused(url, code):
    resolve = resolver({"localhost": ["127.0.0.1"], "lab.internal": ["10.0.0.63"], "metadata": ["169.254.169.254"],
                        "v6local": ["::1"], "mixed.example": [PUBLIC, "192.168.1.10"]})
    with pytest.raises(web.Refused, match=code):
        web.check_url(url, resolve)


def test_public_urls_pass():
    assert web.check_url("https://example.com/page", resolver({"example.com": [PUBLIC]})) == "example.com"


def test_html_becomes_readable_text():
    html = ("<html><head><title> Proxmox  docs </title><style>p{}</style><script>evil()</script></head>"
            "<body><nav>menu</nav><h1>Install</h1><p>First&nbsp;step.</p><p>Second   step.</p><footer>cookie</footer></body></html>")
    title, text = web.html_to_text(html)
    assert title == "Proxmox docs"
    assert text == "Install\n\nFirst step.\n\nSecond step."


def run(coro):
    return asyncio.run(coro)


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_brave_results_are_mapped_and_cleaned(monkeypatch):
    monkeypatch.setattr(web, "BRAVE_KEY", "key-under-test")

    def handler(request):
        assert request.headers["X-Subscription-Token"] == "key-under-test"
        assert request.url.params["count"] == "2" and request.url.params["extra_snippets"] == "true"
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Proxmox <strong>VE</strong>", "url": "https://pve.proxmox.com/", "description": "Open <b>source</b>",
             "extra_snippets": ["a", "b", "c", "d"], "age": "2 days ago"},
            {"title": "bad", "url": "javascript:alert(1)"}]}})

    async def go():
        async with mock_client(handler) as client:
            return await web.brave_search("proxmox", 2, client)
    result = run(go())
    assert result["results"] == [{"title": "Proxmox VE", "url": "https://pve.proxmox.com/", "snippet": "Open source",
                                  "extra_snippets": ["a", "b", "c"], "age": "2 days ago"}]


def test_brave_rate_limit_is_reported():
    async def go():
        async with mock_client(lambda r: httpx.Response(429)) as client:
            return await web.brave_search("q", 3, client)
    assert run(go()) == {"error": "search_rate_limited"}


def test_reading_follows_safe_redirects_and_refuses_private_ones():
    resolve = resolver({"example.com": [PUBLIC], "docs.example.com": [PUBLIC], "evil.example": [PUBLIC], "lab": ["10.0.0.5"]})

    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(301, headers={"location": "https://docs.example.com/guide"})
        if request.url.host == "evil.example":
            return httpx.Response(302, headers={"location": "http://lab/admin"})
        if request.url.host == "lab":
            raise AssertionError("private host must never be fetched")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              text="<title>Guide</title><p>Hello from docs.</p>")

    async def go(url):
        async with mock_client(handler) as client:
            return await web.read_page(url, client, resolve)
    page = run(go("http://example.com/"))
    assert page == {"source": "web", "url": "https://docs.example.com/guide", "title": "Guide", "text": "Hello from docs.", "truncated": False}
    with pytest.raises(web.Refused, match="private_address"):
        run(go("https://evil.example/"))


def test_large_and_binary_pages_are_bounded():
    resolve = resolver({"big.example": [PUBLIC], "img.example": [PUBLIC]})

    def handler(request):
        if request.url.host == "img.example":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * (web.MAX_PAGE_BYTES + 5000))

    async def go(url):
        async with mock_client(handler) as client:
            return await web.read_page(url, client, resolve)
    big = run(go("https://big.example/"))
    assert big["truncated"] and len(big["text"]) == web.MAX_TEXT_CHARS
    assert run(go("https://img.example/"))["error"] == "unsupported_content_type"


def test_daily_search_limit_resets_each_day(monkeypatch):
    monkeypatch.setattr(web, "DAILY_SEARCH_LIMIT", 2)
    monkeypatch.setitem(web._usage, "day", None)
    today = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert [web.take_search_slot(today) for _ in range(3)] == [True, True, False]
    assert web.take_search_slot(today + timedelta(days=1)) is True


def test_tools_validate_arguments_and_report_refusals(monkeypatch):
    monkeypatch.setitem(web._usage, "day", None)
    mcp = web.build_server(["testserver"], client_factory=lambda: mock_client(lambda r: httpx.Response(500)))

    async def call(name, args):
        content, _ = await mcp.call_tool(name, args)
        return json.loads(content[0].text)

    async def go():
        assert (await call("web_search", {"query": " "}))["error"] == "invalid_arguments"
        assert (await call("web_search", {"query": "x", "count": 50}))["error"] == "invalid_arguments"
        assert (await call("web_search", {"query": "x"}))["error"] == "search_failed"
        assert (await call("web_read", {"url": "file:///etc/passwd"}))["error"] == "unsupported_url"
    run(go())
