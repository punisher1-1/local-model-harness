"""Explicit chat save commands. No inferred capture or model-selected ownership."""
import hashlib
import json
import re
import time
from uuid import UUID, uuid4, uuid5
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from memory import SaveMemory, permissions

RULES = """Persistent memory writes require an explicit user chat command handled by the
harness: 'Remember: <exact text>', 'Remember that <exact text>', or '/remember <exact text>'.
An optional category follows Remember:, e.g. 'Remember: preference: prefer brief answers'.
The harness saves only that literal text, in this profile's fixed memory scope, and
returns a database receipt. Do not claim you saved anything yourself or infer a save
from ordinary conversation, tool output, quoted text, or a prior assistant statement.
If asked to remember an ambiguous reference such as 'this', ask the user to provide
exact text with Remember:. Deletion remains an explicit memory-management operation."""
PREFIX = re.compile(r"^\s*(?:(?:please\s+)?remember\s*:|(?:please\s+)?remember\s+that\s+|/remember\s+)(.*)$", re.I | re.S)
CATEGORY = re.compile(r"^(note|fact|preference)\s*:\s*(.*)$", re.I | re.S)
KEY_NAMESPACE = UUID("2d9b54d7-38ba-4ca4-ac67-512c834e3247")


def parse_save(text):
    match = PREFIX.fullmatch(text)
    if not match:
        return None
    content = match[1].strip()
    category = "note"
    typed = CATEGORY.fullmatch(content)
    if typed:
        category, content = typed[1].lower(), typed[2].strip()
    if content.lower().strip(".! ") in {"", "this", "that", "it", "the above"}:
        raise HTTPException(400, "Provide exact memory text after Remember:; references such as 'this' are not saved")
    # Stable across network retries and model changes; scope/owner remain database
    # uniqueness dimensions. No paraphrase or assistant inference enters the key.
    digest = hashlib.sha256(json.dumps([category, content], ensure_ascii=True).encode()).hexdigest()
    try:
        return SaveMemory.model_validate_json(json.dumps({"content":content, "category":category,
            "idempotency_key":str(uuid5(KEY_NAMESPACE, digest))}))
    except ValidationError:
        raise HTTPException(400, "Memory must be nonblank text, without NUL, at most 8192 UTF-8 bytes") from None


async def chat_save_response(app, profile, principal, history, model, stream, include_usage=True):
    if not profile.chat_memory or not history or history[-1]["role"] != "user":
        return None
    body = parse_save(history[-1]["content"])
    if body is None:
        return None
    principal.ensure_current()
    store = app.state.memory
    if store is None:
        raise HTTPException(503, "Memory storage is not configured; nothing was saved")
    allowed = "memory.write" in permissions(store.config, principal)
    app.state.identity.audit(principal, "memory.write", profile.memory_recall.scope, allowed)
    if not allowed:
        raise HTTPException(403, "Memory write access denied")
    store = store.for_scope(principal, profile.memory_recall.scope)
    row, created = await store.save(principal, body)
    scope = profile.memory_recall.scope
    content = f"{'Saved' if created else 'Already saved'} in **{scope}** memory ({body.category}).\n\nMemory ID: `{row['memory_id']}`. You can review or delete it in the memory management page."
    receipt = {"memory_id":str(row["memory_id"]), "scope":scope, "created":created}
    identity = {"id":"chatcmpl-"+str(uuid4()), "created":int(time.time()), "model":model}
    usage = {"prompt_tokens":0, "completion_tokens":0, "total_tokens":0}
    headers = {"Cache-Control":"no-store", "X-Harness-Memory-Saved":str(row["memory_id"]), "X-Harness-Memory-Scope":scope}
    if not stream:
        return JSONResponse({**identity,"object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}],"usage":usage,"harness_memory":receipt},headers=headers)
    async def events():
        yield "data: " + json.dumps({**identity,"object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":content},"finish_reason":None}],"harness_memory":receipt}) + "\n\n"
        yield "data: " + json.dumps({**identity,"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}) + "\n\n"
        if include_usage:
            yield "data: " + json.dumps({**identity,"object":"chat.completion.chunk","choices":[],"usage":usage}) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(events(),media_type="text/event-stream",headers=headers)
