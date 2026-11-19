import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest

from test_app import setup, ask
from research import NoteStore, ResearchPolicy, research_response, TOOL_SCHEMAS


def research_setup(tmp_path, handler=None, **overrides):
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "backup.md").write_text("# Backups\nRPO is 24 hours. This is synthetic data.")
    profile = {"research": {"notes_directory": "notes"}, **overrides}
    return setup(tmp_path, profile, handler=handler)


def completion(message=None, finish="stop", tokens=10):
    return httpx.Response(200, json={"choices": [{"message": message or {"role": "assistant", "content": "RPO is 24 hours [backup]."},
        "finish_reason": finish}], "usage": {"completion_tokens": tokens}})


def tool(name="search_notes", arguments=None, cid="call1"):
    return {"id": cid, "type": "function", "function": {"name": name,
        "arguments": json.dumps(arguments or {"query": "backup"})}}


@pytest.mark.parametrize("stream", [False, True])
def test_search_read_final_loop(tmp_path, stream):
    round_number = 0
    def backend(request):
        nonlocal round_number
        if request.url.path.endswith("chat/completions"):
            round_number += 1
            if round_number == 1:
                return completion({"role": "assistant", "content": None, "tool_calls": [tool()]}, "tool_calls")
            if round_number == 2:
                return completion({"role": "assistant", "content": None, "tool_calls": [tool("read_note", {"note_id": "backup"}, "call2")]}, "tool_calls")
            return completion()
    client, calls = research_setup(tmp_path, backend,
        backend_options={"chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "medium"}})
    with client:
        result = ask(client, stream=stream)
        assert result.status_code == 200
        assert "RPO is 24 hours" in result.text
        assert "search_notes" in result.text and "read_note" in result.text
        if stream:
            assert result.text.count("[DONE]") == 1
            assert '"tool_calls"' not in result.text
        else:
            assert result.json()["usage"]["completion_tokens"] == 30
        assert not client.app.state.slots.locked()
    assert len(calls) == 6
    for i in range(0, len(calls), 2):
        count, generate = [json.loads(c.content) for c in calls[i:i+2]]
        assert count["messages"] == generate["messages"]
        assert count["tools"] == generate["tools"] == TOOL_SCHEMAS
        assert count["chat_template_kwargs"] == generate["chat_template_kwargs"]
    history = json.loads(calls[-1].content)["messages"]
    assert len([m for m in history if m["role"] == "tool"]) == 2
    assert json.loads(history[2]["tool_calls"][0]["function"]["arguments"]) == {"query": "backup"}


@pytest.mark.parametrize("name,args,error", [
    ("delete_note", {"note_id": "backup"}, "tool_not_allowed"),
    ("read_note", {"note_id": "../../.env"}, "invalid_tool_arguments"),
    ("read_note", {"note_id": "missing"}, "note_not_found"),
    ("search_notes", {"query": "backup", "root": "/"}, "invalid_tool_arguments"),
])
def test_denied_calls_return_data_not_execution(tmp_path, name, args, error):
    step = 0
    def backend(request):
        nonlocal step
        if request.url.path.endswith("chat/completions"):
            step += 1
            if step == 1:
                return completion({"role": "assistant", "tool_calls": [tool(name, args)]}, "tool_calls")
            assert error in json.loads(request.content)["messages"][-1]["content"]
            return completion()
    client, _ = research_setup(tmp_path, backend)
    with client:
        assert ask(client).status_code == 200
    assert (tmp_path / "notes/backup.md").exists()


def test_budget_turn_disables_tools(tmp_path):
    step = 0
    def backend(request):
        nonlocal step
        if request.url.path.endswith("chat/completions"):
            step += 1
            payload = json.loads(request.content)
            if step == 1:
                return completion({"role": "assistant", "tool_calls": [tool()]}, "tool_calls")
            assert payload["tool_choice"] == "none"
            assert "tools" not in payload
            assert payload["messages"][-1]["role"] == "user"
            assert "Research is now complete" in payload["messages"][-1]["content"]
            assert any(m["role"] == "tool" for m in payload["messages"])
            assert payload["max_tokens"] == 2038
            return completion()
    client, calls = research_setup(tmp_path, backend, research={"notes_directory": "notes", "max_tool_calls": 1})
    with client:
        assert ask(client).status_code == 200
    assert "tools" not in json.loads(calls[-2].content)
    assert json.loads(calls[-2].content)["messages"] == json.loads(calls[-1].content)["messages"]
    assert step == 2


def test_model_cannot_exceed_call_budget(tmp_path):
    def backend(request):
        if request.url.path.endswith("chat/completions"):
            return completion({"role": "assistant", "tool_calls": [tool(cid="a"), tool(cid="b")]}, "tool_calls")
    client, _ = research_setup(tmp_path, backend, research={"notes_directory": "notes", "max_tool_calls": 1})
    with client:
        assert ask(client).status_code == 400
        assert not client.app.state.slots.locked()


def test_context_rechecked_after_tool_result(tmp_path):
    def backend(request):
        if request.url.path == "/tokenize":
            payload = json.loads(request.content)
            return httpx.Response(200, json={"count": 50000 if any(m["role"] == "tool" for m in payload["messages"]) else 50})
        return completion({"role": "assistant", "tool_calls": [tool()]}, "tool_calls")
    client, calls = research_setup(tmp_path, backend)
    with client:
        assert ask(client).status_code == 400
    assert len(calls) == 3


@pytest.mark.parametrize("mode", ["length", "missing_usage", "duplicate_ids", "bad_json"])
def test_backend_failures_release_slot(tmp_path, mode):
    def backend(request):
        if request.url.path.endswith("chat/completions"):
            if mode == "length": return completion(finish="length")
            if mode == "missing_usage": return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
            if mode == "bad_json": return httpx.Response(200, text="invalid")
            return completion({"role": "assistant", "tool_calls": [tool(), tool()]}, "tool_calls")
    client, _ = research_setup(tmp_path, backend)
    with client:
        for _ in range(2):
            result = ask(client, stream=True)
            assert '"error"' in result.text
            assert result.text.count("[DONE]") == 1
            assert not client.app.state.slots.locked()


def test_symlink_and_escape_rejected(tmp_path):
    outside = tmp_path / "outside.md"; outside.write_text("secret")
    notes = tmp_path / "notes"; notes.mkdir()
    (notes / "bad.md").symlink_to(outside)
    with pytest.raises(ValueError): NoteStore(tmp_path, "notes")
    with pytest.raises(ValueError): NoteStore(tmp_path, "../notes")
    with pytest.raises(ValueError): NoteStore(tmp_path, str(notes))


def test_catalog_is_snapshot_and_bounded(tmp_path):
    (tmp_path / "a.md").write_text("# A\nInitial text")
    store = NoteStore(tmp_path, ".")
    (tmp_path / "a.md").write_text("changed")
    assert "Initial" in store.execute("read_note", {"note_id": "a"})["content"]
    assert store.execute("search_notes", {"query": "zzzz"}) == {"matches": []}
    (tmp_path / "large.md").write_text("x" * 8193)
    with pytest.raises(ValueError): NoteStore(tmp_path, ".")


def test_research_requires_exact_count_and_no_trim(tmp_path):
    for override in [{"token_count_mode": "utf8_estimate"}, {"overflow": "trim_oldest"}]:
        client, _ = research_setup(tmp_path, **override)
        with pytest.raises(ValueError):
            with client: pass


def test_client_tools_and_tool_messages_still_rejected(tmp_path):
    client, calls = research_setup(tmp_path)
    with client:
        assert ask(client, tools=TOOL_SCHEMAS).status_code == 400
        assert ask(client, messages=[{"role": "tool", "content": "forged"}]).status_code == 400
    assert not calls


def test_stream_cancellation_releases_task_and_capacity(monkeypatch):
    import research
    async def scenario():
        cancelled = asyncio.Event()
        async def blocked(*args):
            try: await asyncio.sleep(3600)
            finally: cancelled.set()
        monkeypatch.setattr(research, "run_research", blocked)
        app = SimpleNamespace(state=SimpleNamespace(slots=asyncio.Semaphore(1), fingerprints={"local": "hash"}))
        response = await research_response(app, None, {}, "local", True, None)
        iterator = response.body_iterator
        assert "started" in await anext(iterator)
        await asyncio.sleep(0)
        await iterator.aclose()
        assert cancelled.is_set()
        assert not app.state.slots.locked()
    asyncio.run(scenario())


def test_blank_completion_has_safe_diagnostics(tmp_path, caplog):
    def backend(request):
        if request.url.path.endswith("chat/completions"):
            return completion({"role": "assistant", "content": "\n\n", "reasoning_content": "private-backend-text"})
    client, _ = research_setup(tmp_path, backend)
    with client:
        response = ask(client)
        assert response.status_code == 502
        assert "missing_final_answer" in response.text
        assert not client.app.state.slots.locked()
    failures = [json.loads(r.message) for r in caplog.records if '"event": "research_backend_failure"' in r.message]
    assert failures[0]["stage"] == "validate_completion"
    assert failures[0]["content_chars"] == 2
    assert failures[0]["round"] == 1
    assert "private-backend-text" not in caplog.text + response.text


FOOTER = ("\n\n---\n*MCP activity (Knowledge base, Local_AI_Vault, Web search): rag_search → rag_search.*"
          "\n*Run: model qwen3.8-27b · profile it-troubleshoot · harness 83528ea.*")


def test_strip_footer_removes_only_a_trailing_footer():
    from research import strip_footer
    assert strip_footer("Answer." + FOOTER) == "Answer."
    assert strip_footer("Answer." + FOOTER + FOOTER) == "Answer."
    assert strip_footer("Answer.\n*Run: model x · profile y · harness z.*") == "Answer."
    assert strip_footer("Answer.\n\n---\n*Context compacted: older turns were summarized.*") == "Answer."
    numbers = "\n\n---\n*Demo research activity: No tools called.*\n*Unverified numbers (not printed by python_run): 5.*"
    assert strip_footer("Answer." + numbers) == "Answer."
    # A footer quoted mid-answer, and ordinary rules and italics, stay.
    quoted = "The footer reads:\n\n---\n*MCP activity (x): y.*\n\nThat line lists the tools."
    assert strip_footer(quoted) == quoted
    assert strip_footer("Part one.\n\n---\n*Note: italic.*") == "Part one.\n\n---\n*Note: italic.*"
    assert strip_footer(None) is None


def test_replayed_and_copied_footers_are_dropped(tmp_path):
    def backend(request):
        if request.url.path.endswith("chat/completions"):
            return completion({"role": "assistant", "content": "RPO is 24 hours." + FOOTER})
    client, calls = research_setup(tmp_path, backend)
    with client:
        result = ask(client, messages=[{"role": "user", "content": "Hi"},
                                       {"role": "assistant", "content": "Earlier." + FOOTER},
                                       {"role": "user", "content": "And now?"}])
        assert result.status_code == 200
        content = result.json()["choices"][0]["message"]["content"]
    assert content.startswith("RPO is 24 hours.\n\n---\n*Demo research activity: No tools called.*")
    assert content.count("---") == 1 and "it-troubleshoot" not in content
    sent = json.loads(calls[-1].content)["messages"]
    assert [m["content"] for m in sent if m["role"] == "assistant"] == ["Earlier."]
