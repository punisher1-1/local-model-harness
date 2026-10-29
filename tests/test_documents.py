"""Per-chat document attachments: conversion through a mocked Docling Serve, and digests."""
import json

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import documents
from app import create_app
from test_app import HEADERS, KEY

DOCLING = "http://docling.test:5001"


def make(tmp_path, monkeypatch, docling=None, chat=None, converter=True):
    (tmp_path / "prompt.md").write_text("Server policy")
    profile = {"backend_model": "actual-model", "system_prompt_file": "prompt.md", "token_count_mode": "vllm",
               "context_window": 32768, "max_output_tokens": 4096}
    (tmp_path / "profiles.yaml").write_text(yaml.safe_dump({"profiles": {"local": profile}}))
    if converter:
        monkeypatch.setenv("HARNESS_DOCLING_URL", DOCLING)
        monkeypatch.setenv("HARNESS_DOCLING_API_KEY", "docling-key")
    else:
        monkeypatch.delenv("HARNESS_DOCLING_URL", raising=False)
    calls = []

    def backend(request):
        calls.append(json.loads(request.content) if request.content else None)
        if request.url.path == "/tokenize":
            text = request.content.decode()
            return httpx.Response(200, json={"count": 20000 if "LONG" in text else 120})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "actual-model"}]})
        return chat(request) if chat else httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "summary"}, "finish_reason": "stop"}]})

    app = create_app(tmp_path / "profiles.yaml", KEY, "http://backend/v1", httpx.MockTransport(backend),
                     docling_transport=httpx.MockTransport(docling) if docling else None)
    return TestClient(app), calls


def events(response):
    return [json.loads(l) for l in response.text.splitlines() if l.strip()]


def upload(client, name, data, profile="local"):
    return client.post(f"/v1/documents/convert?profile={profile}", headers={**HEADERS, "X-Document-Name": name}, content=data)


def test_config_lists_types_the_harness_can_read(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch, converter=False)
    with client:
        assert client.get("/v1/documents/config", headers=HEADERS).json() == {
            "converter": False, "types": [".markdown", ".md", ".txt"], "max_bytes": documents.MAX_UPLOAD_BYTES}
    client, _ = make(tmp_path, monkeypatch)
    with client:
        assert ".pdf" in client.get("/v1/documents/config", headers=HEADERS).json()["types"]


def test_text_files_are_read_directly_and_counted(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch, converter=False)
    with client:
        result = events(upload(client, "../notes/plan.md", b"# Plan\n\nShip it."))
    assert result[0] == {"status": "reading"}
    assert result[-1] == {"done": True, "name": "plan.md", "text": "# Plan\n\nShip it.", "chars": 16, "tokens": 120,
                          "budget": (32768 - 4096 - 256) // 2, "fits": True, "partial": False}


def test_pdf_goes_to_docling_as_markdown_with_the_api_key(tmp_path, monkeypatch):
    seen = []

    def docling(request):
        seen.append(request)
        return httpx.Response(200, json={"status": "success", "document": {"md_content": "## Report\n\nQ3 grew 4%."}})
    client, _ = make(tmp_path, monkeypatch, docling)
    with client:
        result = events(upload(client, "report.pdf", b"%PDF-1.7 fake"))
    assert result[-1]["text"] == "## Report\n\nQ3 grew 4%." and result[-1]["fits"] is True
    request = seen[0]
    body = request.content.decode(errors="replace")
    assert str(request.url) == DOCLING + "/v1/convert/file" and request.headers["x-api-key"] == "docling-key"
    assert 'name="to_formats"' in body and "\r\n\r\nmd\r\n" in body and 'filename="report.pdf"' in body


def test_encoded_non_ascii_names_are_decoded(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch, converter=False)
    with client:
        assert events(upload(client, "R%C3%A9sum%C3%A9%20notes.txt", b"hi"))[-1]["name"] == "Résumé notes.txt"


def test_long_documents_are_marked_as_not_fitting(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch, converter=False)
    with client:
        assert events(upload(client, "big.txt", b"LONG " * 1000))[-1]["fits"] is False


@pytest.mark.parametrize("name,data,status,detail", [
    ("tool.exe", b"x", 415, "Attach a PDF"),
    ("empty.txt", b"", 400, "The file is empty"),
])
def test_unsupported_and_empty_files_are_refused(tmp_path, monkeypatch, name, data, status, detail):
    client, _ = make(tmp_path, monkeypatch, converter=False)
    with client:
        r = upload(client, name, data)
    assert r.status_code == status and detail in r.text


def test_pdfs_need_a_configured_converter_and_size_limits_hold(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch, converter=False)
    monkeypatch.setattr(documents, "MAX_UPLOAD_BYTES", 10)
    with client:
        assert upload(client, "scan.pdf", b"%PDF").status_code == 503
        assert upload(client, "a.txt", b"x" * 11).status_code == 413
        assert upload(client, "a.txt", b"hello", profile="missing").status_code == 404


@pytest.mark.parametrize("docling,error", [
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), "The document converter is unavailable"),
    (lambda r: httpx.Response(401), "refused the harness's API key"),
    (lambda r: httpx.Response(200, json={"status": "failure", "document": {"md_content": ""}}), "could not read this file"),
])
def test_converter_failures_are_explained(tmp_path, monkeypatch, docling, error):
    client, _ = make(tmp_path, monkeypatch, docling)
    with client:
        assert error in events(upload(client, "a.pdf", b"%PDF"))[-1]["error"]


def test_digest_summarizes_each_part_without_reasoning_and_combines_them(tmp_path, monkeypatch):
    client, calls = make(tmp_path, monkeypatch, converter=False)
    monkeypatch.setattr(documents, "PART_CHARS", 60)
    text = "# Intro\n\n" + "Alpha line one.\n\n" * 3 + "# Methods\n\n" + "Beta line two.\n\n" * 3
    with client:
        result = events(client.post("/v1/documents/digest", headers=HEADERS, json={"profile": "local", "name": "paper.pdf", "text": text}))
    progress = [e for e in result if e.get("status") == "summarizing"]
    assert [e["part"] for e in progress] == list(range(1, len(progress) + 1)) and len(progress) >= 2
    done = result[-1]
    assert done["digest"] is True and done["text"].startswith("Section-by-section digest of paper.pdf")
    assert "## Part 1: Intro" in done["text"] and done["text"].count("summary") == len(progress)
    asks = [c for c in calls if c and "max_tokens" in c and c["messages"][0]["content"].startswith("You summarize one part")]
    assert len(asks) == len(progress) and all(c["max_tokens"] == documents.PART_SUMMARY_TOKENS for c in asks)
    assert "<document_part>" in asks[0]["messages"][1]["content"]


def test_split_parts_keeps_paragraphs_and_breaks_long_blocks(monkeypatch):
    monkeypatch.setattr(documents, "PART_CHARS", 50)
    parts = documents.split_parts("# A\n\n" + "x" * 120 + "\n\nshort tail")
    assert parts[0] == "# A" and "".join(parts[1:4]).startswith("x" * 100) and parts[-1].endswith("short tail")
    assert all(len(p) <= 50 for p in parts)


def test_saved_messages_keep_attachments():
    from conversation_store import Message
    m = Message.model_validate({"id": "u", "role": "user", "content": "Summarize it",
                                "attachments": [{"name": "a.pdf", "text": "Body", "chars": 4, "tokens": 2}]})
    assert m.model_dump()["attachments"] == [{"name": "a.pdf", "text": "Body", "chars": 4, "tokens": 2, "digest": False}]
    with pytest.raises(Exception):
        Message.model_validate({"id": "u", "role": "user", "content": "x", "attachments": [{"name": "a", "text": "b", "chars": 1}] * 6})
