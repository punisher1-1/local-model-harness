"""Bounded, harness-owned research loop over a startup snapshot of demo notes."""
import asyncio
from contextlib import suppress
import hashlib
import json
import logging
from pathlib import Path
import re
import time
import uuid

import httpx
from telemetry import record_usage, attach_accounting
from compaction import compact_context, NOTICE
from backend import thinking_budget
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

log = logging.getLogger("uvicorn.error")
# Tools whose arguments carry a note body or a script, not a short query.
LARGE_ARGUMENT_TOOLS = frozenset({"vault_create_note", "vault_append", "python_run"})


class ResearchProtocolError(ValueError):
    """A fixed diagnostic code, never backend or user text."""


class ResearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    notes_directory: str
    max_tool_calls: int = Field(default=3, ge=1, le=8)
    max_round_output_tokens: int = Field(default=2048, ge=128, le=8192)


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=256)


class ReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    note_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_notes",
        "description": "Search the synthetic demo notes by keywords. Returns note IDs, titles and short excerpts; use read_note to inspect full evidence. No web or private vault access.",
        "parameters": SearchArgs.model_json_schema()}},
    {"type": "function", "function": {
        "name": "read_note",
        "description": "Read one synthetic demo note by an ID returned by search_notes. Cannot read paths or files outside the fixed demo catalog.",
        "parameters": ReadArgs.model_json_schema()}},
]


class NoteStore:
    """Read files at startup only; model arguments never become filesystem paths."""
    def __init__(self, config_directory: Path, relative_directory: str):
        relative = Path(relative_directory)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Research notes directory must be inside the config directory")
        current = config_directory
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlinked research directories are not allowed")
        if not current.is_dir():
            raise ValueError("Research notes directory is missing")
        self.notes = {}
        total = 0
        for path in sorted(current.iterdir()):
            if path.suffix != ".md":
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError("Research notes must be regular files")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", path.stem):
                raise ValueError("Invalid research note ID")
            if path.stat().st_size > 8192:
                raise ValueError("Research note exceeds 8192 bytes")
            data = path.read_bytes()
            total += len(data)
            if len(data) > 8192 or total > 262144 or len(self.notes) >= 100:
                raise ValueError("Research catalog exceeds size limit")
            content = data.decode("utf-8")
            title = content.splitlines()[0].lstrip("# ")[:120] if content else path.stem
            self.notes[path.stem] = {"note_id": path.stem, "title": title, "content": content}
        if not self.notes:
            raise ValueError("Research catalog is empty")
        self.sha256 = hashlib.sha256(json.dumps(self.notes, sort_keys=True).encode()).hexdigest()

    def execute(self, name, arguments):
        if name not in {"search_notes", "read_note"}:
            return {"error": "tool_not_allowed"}
        try:
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object")
            if name == "read_note":
                args = ReadArgs.model_validate(arguments)
                return self.notes.get(args.note_id, {"error": "note_not_found"})
            args = SearchArgs.model_validate(arguments)
            words = set(re.findall(r"\w+", args.query.casefold()))
            hits = []
            for note in self.notes.values():
                terms = set(re.findall(r"\w+", (note["title"] + " " + note["content"]).casefold()))
                score = len(words & terms)
                if score:
                    hits.append((score, note))
            hits.sort(key=lambda item: (-item[0], item[1]["note_id"]))
            return {"matches": [{"note_id": n["note_id"], "title": n["title"], "excerpt": n["content"][:400]}
                                for _, n in hits[:5]]}
        except (ValidationError, ValueError, TypeError):
            return {"error": "invalid_tool_arguments"}


def describe_call(name, args):
    """One short line for the reasoning trace: the target of a call, never full bodies or scripts."""
    args = args if isinstance(args, dict) else {}
    if name == "python_run":
        lines = [l for l in str(args.get("code", "")).splitlines() if l.strip()]
        target = (lines[0] if lines else "") + (f" … ({len(lines)} lines)" if len(lines) > 1 else "")
    elif name in {"vault_create_note", "vault_append"}:
        body = args.get("content", args.get("text", ""))
        target = f"{args.get('path', '')} ({len(str(body)):,} chars)"
    else:
        target = next((str(args[k]) for k in ("query", "path_prefix", "path", "url", "note_id") if k in args), "")
    target = target if len(target) <= 160 else target[:157] + "…"
    return f"→ {name}({target})"


def describe_result(result):
    if result.get("error"):
        return f"  ✗ {result['error']}" + (f" ({result['reason']})" if result.get("reason") else "")
    if "exit_code" in result:
        return f"  ✓ exit {result['exit_code']}" + (" (timed out)" if result.get("timed_out") else "")
    for key, noun in (("results", "results"), ("matches", "matches"), ("notes", "notes")):
        if isinstance(result.get(key), list):
            return f"  ✓ {len(result[key])} {noun}"
    if result.get("status"):
        return f"  ✓ {result['status']} {result.get('path', '')}".rstrip()
    if isinstance(result.get("content"), str):
        return f"  ✓ read {len(result['content']):,} chars" + (" (truncated)" if result.get("truncated") else "")
    if isinstance(result.get("text"), str):
        return f"  ✓ read {len(result['text']):,} chars" + (" (truncated)" if result.get("truncated") else "")
    return "  ✓ ok"


async def bounded_json(client, url, payload, timeout):
    async with client.stream("POST", url, json=payload, timeout=timeout) as response:
        response.raise_for_status()
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw) > 2_000_000:
                raise HTTPException(502, "Research backend response exceeds size limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Backend response must be an object")
        return value


async def run_research(app, profile, payload, public_model, rid, principal, servers=(), progress=None):
    """Bounded tool loop. progress, if given, receives each reasoning step as it happens."""
    steps = []

    def step(text):
        if text:
            steps.append(text)
            if progress:
                progress(text)

    is_mcp = bool(servers)
    if is_mcp:
        from mcp_registry import server as mcp_server
        registered = [mcp_server(s) for s in servers]
        # Fresh stores per request: discovery receipts never leak between requests.
        stores = {s.id: s.factory() for s in registered}
        owner = {t: s for s in registered for t in s.tools}
        policy = ResearchPolicy(notes_directory="unused",max_tool_calls=6,max_round_output_tokens=8192)
        schemas = [t for s in registered for t in s.schemas]
        catalog_sha256 = hashlib.sha256("".join(stores[s].sha256 for s in servers).encode()).hexdigest()
        activity_label = "Vault MCP activity: " if servers == ("vault",) else "MCP activity (" + ", ".join(s.label for s in registered) + "): "
    else:
        policy = profile.research
        store = app.state.research_stores[public_model]
        schemas, stores, owner = TOOL_SCHEMAS, {}, {}
        catalog_sha256 = store.sha256
        activity_label = "Demo research activity: "
    vault = stores.get("vault")

    def collection(name):
        return owner[name].collection if name in owner else "demo_notes"

    tool_names = {t["function"]["name"] for t in schemas}
    principal.require_profile(public_model)
    permitted_tools = [t for t in schemas if principal.can_tool(public_model, t["function"]["name"], collection(t["function"]["name"]))]
    started = time.monotonic()
    deadline = profile.request_timeout_seconds or app.state.settings.request_timeout_seconds
    messages = list(payload["messages"])
    # Do not mutate the caller's message objects when adding a final-round instruction.
    messages[0] = dict(messages[0])
    calls_used = 0
    output_used = 0
    prompt_total = 0
    trace = []
    seen_ids = set()
    status = "failed"
    stage = "prepare"
    round_index = -1
    finish_reason = None
    content_chars = None
    try:
        async with asyncio.timeout(deadline):
            messages, compact_state = await compact_context(app, profile, payload, messages, principal, rid, permitted_tools)
            for round_index in range(policy.max_tool_calls + 1):
                principal.require_profile(public_model)
                remaining = payload["max_tokens"] - output_used
                if remaining <= 0:
                    raise HTTPException(400, "Research output budget exhausted before final answer")
                can_call = calls_used < policy.max_tool_calls and bool(permitted_tools)
                force_read = (vault is not None and can_call and vault.seen and not vault.read_paths and not vault.writes
                              and vault.discovery_calls >= 2
                              and principal.can_tool(public_model,"vault_read_note",collection("vault_read_note")))
                round_tools = ([t for t in permitted_tools if t["function"]["name"]=="vault_read_note"]
                               if force_read else permitted_tools)
                if not can_call:
                    messages[0]["content"] += "\nTool budget reached. Give a final answer from the evidence already returned; acknowledge any gaps."
                    # A fresh, harness-authored turn makes finalization explicit to
                    # Qwen and its template; no extra tool or model round is granted.
                    messages.append({"role": "user", "content":
                        "Research is now complete and no further tool calls are available. "
                        "Using only the evidence already returned, write the final answer to my original question now. "
                        "Do not search or request more notes. If the evidence does not establish a requested fact, "
                        "state that it is unverified in the notes found. Return a user-facing answer, not tool-call markup."})
                # Reserve final-answer capacity while tools can still be requested.
                round_limit = min(remaining, policy.max_round_output_tokens) if can_call else remaining
                token_payload = {"model": payload["model"], "messages": messages,
                                 "add_generation_prompt": True}
                if can_call:
                    token_payload["tools"] = round_tools
                if "chat_template_kwargs" in payload:
                    token_payload["chat_template_kwargs"] = payload["chat_template_kwargs"]
                stage = "tokenize"
                finish_reason = None
                content_chars = None
                tokenized = await bounded_json(app.state.client, app.state.url[:-3] + "/tokenize", token_payload, deadline)
                count = tokenized.get("count")
                if type(count) is not int or count < 0:
                    raise ResearchProtocolError("invalid_token_count")
                # All history, tool schemas, tool calls and tool results count each round.
                if count + round_limit + profile.context_margin > profile.context_window:
                    raise HTTPException(400, "Research context budget exceeded; shorten the conversation")
                request_payload = {**payload, "messages": messages, "stream": False,
                    "tool_choice": ({"type":"function","function":{"name":"vault_read_note"}} if force_read else "auto") if can_call else "none",
                    "parallel_tool_calls": False, "max_tokens": round_limit}
                if can_call:
                    request_payload["tools"] = round_tools
                budget = thinking_budget(profile, round_limit, request_payload.get("thinking_token_budget"))
                if budget is not None:
                    request_payload["thinking_token_budget"] = budget
                request_payload.pop("stream_options", None)
                stage = "generate"
                result = await bounded_json(app.state.client, app.state.url + "/chat/completions", request_payload, deadline)
                stage = "validate_completion"
                choices = result.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ResearchProtocolError("invalid_choices")
                choice = choices[0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason")
                content_chars = len(message["content"]) if isinstance(message.get("content"), str) else None
                usage = result.get("usage") or {}
                consumed = usage.get("completion_tokens")
                if type(consumed) is not int or not 0 < consumed <= round_limit:
                    raise ResearchProtocolError("invalid_completion_usage")
                record_usage(usage, rid, public_model, profile.backend_model)
                actual_prompt = usage.get("prompt_tokens")
                prompt_total += actual_prompt if type(actual_prompt) is int and actual_prompt >= 0 else count
                output_used += consumed
                tool_calls = message.get("tool_calls") or []
                if choice.get("finish_reason") == "length":
                    raise HTTPException(400, "Research round hit its output limit before completion; shorten the task or adjust the research budget")
                if force_read and not tool_calls:
                    raise ResearchProtocolError("reserved_read_not_followed")
                if is_mcp and len(tool_calls) > 1:
                    raise ResearchProtocolError("mcp_requires_sequential_calls")
                reasoning = message.get("reasoning_content") or message.get("reasoning")
                step(reasoning.strip() if isinstance(reasoning, str) else "")
                if not tool_calls:
                    content = message.get("content")
                    if choice.get("finish_reason") != "stop" or not isinstance(content, str) or not content.strip():
                        raise ResearchProtocolError("missing_final_answer")
                    activity = " → ".join(trace) if trace else "No tools called"
                    content += "\n\n---\n*" + activity_label + activity + ".*"
                    if compact_state["status"] == "compacted":
                        content += NOTICE
                    status = "completed"
                    answer = {"harness_context": compact_state,"id": "chatcmpl-" + rid, "object": "chat.completion", "created": int(time.time()),
                        "model": public_model, "choices": [{"index": 0,
                            "message": {"role": "assistant", "content": content,
                                        **({"reasoning_content": "\n\n".join(steps)} if steps else {})}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": prompt_total, "completion_tokens": output_used,
                                  "total_tokens": prompt_total + output_used}}
                    attach_accounting(answer, compact_state)
                    return answer
                if choice.get("finish_reason") != "tool_calls" or not isinstance(tool_calls, list):
                    raise ResearchProtocolError("malformed_tool_completion")
                if not can_call or len(tool_calls) > policy.max_tool_calls - calls_used:
                    raise HTTPException(400, "Research tool-call budget exceeded")
                normalized = []
                for call in tool_calls:
                    cid = call.get("id")
                    fn = call.get("function") or {}
                    name = fn.get("name")
                    if call.get("type") != "function" or not isinstance(cid, str) or not 1 <= len(cid) <= 128 or cid in seen_ids or not isinstance(name, str) or len(name) > 80:
                        raise ResearchProtocolError("malformed_tool_call")
                    seen_ids.add(cid)
                    arguments = fn.get("arguments")
                    # Note bodies and scripts need room; every other tool keeps the small argument bound.
                    limit = 48000 if is_mcp and name in LARGE_ARGUMENT_TOOLS else 2048
                    if isinstance(arguments, str):
                        if len(arguments) > limit:
                            raise ResearchProtocolError("tool_arguments_too_large")
                        try:
                            arguments = json.loads(arguments)
                        except ValueError:
                            arguments = None
                    if arguments is not None and len(json.dumps(arguments)) > limit:
                        raise ResearchProtocolError("tool_arguments_too_large")
                    # vLLM requires JSON strings on the wire and parses them for the Qwen template.
                    normalized.append({"id": cid, "type": "function", "function": {
                        "name": name, "arguments": json.dumps(arguments if isinstance(arguments, dict) else {})}})
                    call["_validated_arguments"] = arguments
                assistant = {"role": "assistant", "content": message.get("content") or "", "tool_calls": normalized}
                if isinstance(reasoning, str):
                    assistant["reasoning_content"] = reasoning
                messages.append(assistant)
                for call, normalized_call in zip(tool_calls, normalized):
                    name = normalized_call["function"]["name"]
                    principal.ensure_current()
                    allowed = principal.can_tool(public_model, name, collection(name))
                    app.state.identity.audit(principal, "tool", name if name in tool_names else "unregistered_tool", allowed, request_id=rid)
                    # Recheck profile, action and collection at execution; never trust model choice.
                    if force_read and name != "vault_read_note":
                        raise ResearchProtocolError("reserved_read_not_followed")
                    if name in tool_names:
                        principal.require_tool(public_model, name, collection(name))
                    step(describe_call(name if name in tool_names else "unregistered_tool", call["_validated_arguments"]))
                    if not is_mcp:
                        result_data = store.execute(name, call["_validated_arguments"])
                    elif name in owner:
                        result_data = await stores[owner[name].id].execute(name, call["_validated_arguments"])
                    else:
                        result_data = {"error": "tool_not_allowed"}
                    calls_used += 1
                    safe_name = name if name in tool_names else "unregistered_tool"
                    error = result_data.get("error")
                    reason = result_data.get("reason")
                    trace.append(safe_name + (" (" + error + (": " + reason if reason else "") + ")" if error else ""))
                    step(describe_result(result_data))
                    log.info(json.dumps({"event": "research_tool", "request_id": rid, "profile": public_model,
                        "tool": safe_name, "status": error or "ok", "call_number": calls_used,
                        "catalog_sha256": catalog_sha256}))
                    messages.append({"role": "tool", "tool_call_id": normalized_call["id"],
                                     "content": json.dumps(result_data, ensure_ascii=True)})
            raise HTTPException(400, "Research round limit exceeded")
    except (httpx.TimeoutException, TimeoutError):
        raise HTTPException(504, "Research deadline exceeded")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        code = str(exc) if isinstance(exc, ResearchProtocolError) else type(exc).__name__
        log.warning(json.dumps({"event": "research_backend_failure", "request_id": rid,
            "profile": public_model, "stage": stage, "round": round_index + 1,
            "code": code, "tool_calls": calls_used, "content_chars": content_chars,
            "finish_reason": finish_reason if isinstance(finish_reason, str) and finish_reason in {"stop", "length", "tool_calls", "content_filter"} else "other",
            "upstream_status": exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None}))
        raise HTTPException(502, "Research backend failed at " + stage + " (" + code + "). Request ID: " + rid)
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        log.info(json.dumps({"event": "research_generation", "request_id": rid, "profile": public_model,
            "profile_sha256": app.state.fingerprints[public_model], "catalog_sha256": catalog_sha256,
            "status": status, "tool_calls": calls_used, "completion_tokens": output_used,
            "elapsed_ms": round((time.monotonic() - started) * 1000)}))


async def research_response(app, profile, payload, public_model, stream, principal, servers=()):
    if app.state.slots.locked():
        raise HTTPException(429, "Harness concurrency limit reached", headers={"Retry-After": "1"})
    await app.state.slots.acquire()
    rid = str(uuid.uuid4())
    headers = {"X-Request-ID": rid, "X-Harness-Profile-SHA256": app.state.fingerprints[public_model]}
    if not stream:
        try:
            return JSONResponse(await run_research(app, profile, payload, public_model, rid, principal, servers), headers=headers)
        finally:
            app.state.slots.release()

    async def events():
        # Each round's reasoning and every tool call stream as reasoning_content while the
        # loop runs; the final answer is still delivered whole. Heartbeats cover quiet rounds.
        steps = asyncio.Queue()
        task = asyncio.create_task(run_research(app, profile, payload, public_model, rid, principal, servers, steps.put_nowait))
        base = {"id": "chatcmpl-" + rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": public_model}

        def reasoning_event(text, first):
            delta = {"reasoning_content": text + "\n\n", **({"role": "assistant"} if first else {})}
            return "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) + "\n\n"

        try:
            yield ": research started\n\n"
            sent = 0
            while not task.done() or not steps.empty():
                getter = asyncio.ensure_future(steps.get())
                done, _ = await asyncio.wait({task, getter}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield reasoning_event(getter.result(), sent == 0)
                    sent += 1
                    continue
                getter.cancel()
                if not done:
                    yield ": research running\n\n"
            result = await task
            base = {"id": result["id"], "object": "chat.completion.chunk", "created": result["created"], "model": public_model}
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {
                "role": "assistant", "content": result["choices"][0]["message"]["content"]}, "finish_reason": None}]}) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
            if payload.get("stream_options", {}).get("include_usage"):
                event = {**base, "choices": [], "usage": result["usage"]}
                if "harness_usage" in result:
                    event["harness_usage"] = result["harness_usage"]
                yield "data: " + json.dumps(event) + "\n\n"
            yield "data: [DONE]\n\n"
        except HTTPException as exc:
            yield "data: " + json.dumps({"error": {"message": exc.detail, "type": "harness_error", "code": exc.status_code}}) + "\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(task, return_exceptions=True)
            app.state.slots.release()

    return StreamingResponse(events(), media_type="text/event-stream", headers={**headers,
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
