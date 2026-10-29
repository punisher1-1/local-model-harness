import re
import json

import httpx

import pytest

from research import describe_call, describe_result
from test_app import setup, ask
from test_research import completion, tool
from vault_mcp import VaultStore


def test_call_previews_show_targets_not_bodies():
    assert describe_call("vault_search", {"query": "Proxmox"}) == "→ vault_search(Proxmox)"
    script = "import math\n\nx = 1\nprint(math.pi)\n"
    assert describe_call("python_run", {"code": script}) == "→ python_run(import math … (3 lines))"
    secret_body = "draft text " * 100
    line = describe_call("vault_create_note", {"path": "Drafts/a.md", "content": secret_body})
    assert line == "→ vault_create_note(Drafts/a.md (1,100 chars))" and "draft text" not in line
    assert len(describe_call("vault_search", {"query": "q" * 500})) < 180
    assert describe_call("python_run", None) == "→ python_run()"


@pytest.mark.parametrize("result,expected", [
    ({"error": "vault_unavailable"}, "  ✗ vault_unavailable"),
    ({"exit_code": 0, "stdout": "1"}, "  ✓ exit 0"),
    ({"exit_code": None, "timed_out": True}, "  ✗ exit None (timed out)"),
    ({"results": [1, 2, 3]}, "  ✓ 3 results"),
    ({"notes": []}, "  ✓ 0 notes"),
    ({"status": "created", "path": "Drafts/a.md"}, "  ✓ created Drafts/a.md"),
    ({"content": "x" * 2000, "truncated": True}, "  ✓ read 2,000 chars (truncated)"),
])
def test_result_summaries(result, expected):
    assert describe_result(result) == expected


def vault_backend(rounds):
    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        rounds.append(json.loads(request.content))
        if len(rounds) == 1:
            return completion({"role": "assistant", "reasoning_content": "I should search the vault first.",
                               "tool_calls": [tool("vault_search", {"query": "evidence"})]}, "tool_calls")
        if len(rounds) == 2:
            return completion({"role": "assistant", "reasoning_content": "Read the hit.",
                               "tool_calls": [tool("vault_read_note", {"path": "Lab/note.md"}, "call2")]}, "tool_calls")
        return completion({"role": "assistant", "reasoning_content": "Now answer with the citation.", "content": "Answer [Lab/note.md]."})
    return backend


@pytest.fixture
def vault(monkeypatch):
    monkeypatch.setenv("HARNESS_VAULT_MCP_URL", "http://vault/mcp")

    async def fake(self, name, args):
        return {"results": [{"path": "Lab/note.md", "snippet": "s"}]} if name == "vault_search" else {"content": "PRIVATE NOTE BODY"}
    monkeypatch.setattr(VaultStore, "call", fake)


def test_stream_sends_each_step_as_reasoning_before_the_answer(tmp_path, vault):
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]}, handler=vault_backend([]))
    with client:
        r = ask(client, stream=True)
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: {")]
    reasoning = [e["choices"][0]["delta"]["reasoning_content"].strip() for e in events
                 if e.get("choices") and "reasoning_content" in e["choices"][0]["delta"]]
    assert reasoning == ["I should search the vault first.", "→ vault_search(evidence)", "✓ 1 results",
                         "Read the hit.", "→ vault_read_note(Lab/note.md)", "✓ read 17 chars",
                         "Now answer with the citation."]
    first_content = next(i for i, e in enumerate(events) if e.get("choices") and e["choices"][0]["delta"].get("content"))
    last_reasoning = max(i for i, e in enumerate(events) if e.get("choices") and "reasoning_content" in e["choices"][0]["delta"])
    assert last_reasoning < first_content and "PRIVATE NOTE BODY" not in r.text


def test_non_stream_answer_carries_the_combined_trace(tmp_path, vault):
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]}, handler=vault_backend([]))
    with client:
        message = ask(client).json()["choices"][0]["message"]
    assert message["content"].startswith("Answer [Lab/note.md].")
    assert message["reasoning_content"].split("\n\n")[:2] == ["I should search the vault first.", "→ vault_search(evidence)"]


def sse(*deltas, finish="stop", tokens=10):
    chunks = [{"choices": [{"index": 0, "delta": d, "finish_reason": None}]} for d in deltas]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
    chunks.append({"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": tokens, "total_tokens": 30 + tokens}})
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n")


def streaming_vault_backend(rounds, preamble=""):
    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        body = json.loads(request.content)
        rounds.append(body)
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        if len(rounds) == 1:
            args = json.dumps({"query": "evidence"})
            return sse({"reasoning_content": "Search "}, {"reasoning_content": "first."},
                       *([{"content": preamble}] if preamble else []),
                       {"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "vault_search", "arguments": ""}}]},
                       {"tool_calls": [{"index": 0, "function": {"arguments": args[:9]}}]},
                       {"tool_calls": [{"index": 0, "function": {"arguments": args[9:]}}]}, finish="tool_calls")
        return sse({"reasoning": "Answer now."}, {"content": "Answer [Lab/note.md]. "}, {"content": "x" * 200}, {"content": "tail"})
    return backend


def stream_events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]


def deltas(events, key):
    return [e["choices"][0]["delta"][key] for e in events if e.get("choices") and key in e["choices"][0]["delta"]]


def test_reasoning_and_answer_stream_token_by_token(tmp_path, vault):
    rounds = []
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]}, handler=streaming_vault_backend(rounds))
    with client:
        r = ask(client, stream=True)
    events = stream_events(r.text)
    assert deltas(events, "reasoning_content")[:4] == ["Search ", "first.", "\n\n", "→ vault_search(evidence)\n\n"]
    content = deltas(events, "content")
    # The opening is held until it is clearly an answer, then tokens pass straight through.
    assert content[:2] == ["Answer [Lab/note.md]. " + "x" * 200, "tail"]
    assert re.fullmatch(r"\n\n---\n\*Vault MCP activity: vault_search\.\*\n\*Run: model \S+ · profile local · harness \S+\.\*", content[2])
    assert json.loads(rounds[1]["messages"][-1]["content"])["results"][0]["path"] == "Lab/note.md"
    assert deltas(events, "role") == ["assistant"] and "PRIVATE NOTE BODY" not in r.text


def test_short_preamble_before_a_tool_call_is_not_shown_as_answer(tmp_path, vault):
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]},
                      handler=streaming_vault_backend([], preamble="Let me check."))
    with client:
        r = ask(client, stream=True)
    assert "".join(deltas(stream_events(r.text), "content")).startswith("Answer [Lab/note.md].")


def test_stream_without_usage_is_refused(tmp_path, vault):
    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text='data: {"choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n')
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]}, handler=backend)
    with client:
        r = ask(client, stream=True)
    assert "invalid_completion_usage" in r.text and r.text.count("[DONE]") == 1
    assert not client.app.state.slots.locked()


def test_streamed_tool_call_ending_with_stop_is_treated_as_a_tool_round(tmp_path, vault):
    rounds = []

    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        rounds.append(json.loads(request.content))
        if len(rounds) == 1:
            return sse({"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                        "function": {"name": "vault_search", "arguments": json.dumps({"query": "evidence"})}}]},
                       finish="stop")
        return sse({"content": "Answer [Lab/note.md]."})
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]}, handler=backend)
    with client:
        r = ask(client, stream=True)
    assert "malformed_tool_completion" not in r.text and len(rounds) == 2
    assert "".join(deltas(stream_events(r.text), "content")).startswith("Answer [Lab/note.md].")


def test_streamed_tool_call_cut_off_by_length_still_fails(tmp_path, vault):
    def backend(request):
        if request.url.path != "/v1/chat/completions":
            return None
        return sse({"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                    "function": {"name": "vault_search", "arguments": "{\"query\": \"ev"}}]}, finish="length")
    client, _ = setup(tmp_path, {"client_tools": True, "mcp_servers": ["vault"]}, handler=backend)
    with client:
        r = ask(client, stream=True)
    assert "output limit" in r.text and r.text.count("[DONE]") == 1
