import json

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
    ({"exit_code": None, "timed_out": True}, "  ✓ exit None (timed out)"),
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
