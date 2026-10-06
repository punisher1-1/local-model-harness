"""Policy-owned, text-only OpenAI-compatible local inference gateway."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Literal
import uuid
from urllib.parse import urlsplit

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator, field_validator

from backend import BackendPreset, catalog, resolve_profile, runtime_headers
from chat_memory import chat_save_response, RULES as CHAT_MEMORY_RULES
from client_tools import ToolCall, ToolDefinition, NamedChoice, prepare_history, RULES as CLIENT_TOOL_RULES
from telemetry import backend_metrics, record_usage, attach_accounting
from research import ResearchPolicy, NoteStore, research_response
from identity import IdentityProvider
from compaction import CompactionPolicy, compact_context, context_headers, CONTEXT_RULES, context_notice
from memory import allowed_scopes, MemoryConfig, MemoryStore, install_routes, permissions as memory_permissions, RecallPolicy, apply_recall, recall_headers, RECALL_RULES

log = logging.getLogger("uvicorn.error")


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend_model: str = Field(min_length=1)
    system_prompt_file: str
    rules: list[str] = Field(default_factory=list)
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    top_p: float | None = Field(default=0.9, gt=0, le=1)
    presence_penalty: float | None = Field(default=0.0, ge=-2, le=2)
    request_timeout_seconds: float | None = Field(default=None, gt=0)
    max_output_tokens: int = Field(default=2048, gt=0)
    context_window: int = Field(default=16384, gt=0)
    context_margin: int = Field(default=256, ge=0)
    token_count_mode: Literal["vllm", "utf8_estimate"] = "vllm"
    overflow: Literal["reject", "trim_oldest"] = "reject"
    client_system_prompt: Literal["discard", "reject"] = "discard"
    allow_client_params: list[Literal["temperature", "top_p", "max_tokens", "seed"]] = Field(default_factory=list)
    seed: int | None = None
    stop: list[str] = Field(default_factory=list, max_length=4)
    backend_options: dict = Field(default_factory=dict)
    backend_presets: dict[str, BackendPreset] = Field(default_factory=dict)
    client_tools: bool = False
    research: ResearchPolicy | None = None
    chat_memory: bool = False
    memory_recall: RecallPolicy = Field(default_factory=RecallPolicy)
    compaction: CompactionPolicy = Field(default_factory=CompactionPolicy)

    @model_validator(mode="after")
    def valid_budget(self):
        if self.max_output_tokens + self.context_margin >= self.context_window:
            raise ValueError("Output and margin must leave room for the prompt")
        allowed = {"top_k", "min_p", "repetition_penalty", "chat_template_kwargs"}
        if self.backend_options.keys() - allowed:
            raise ValueError("Unsupported backend_options; routing and policy cannot be overridden")
        for preset in self.backend_presets.values():
            if preset.backend_options.keys() - allowed:
                raise ValueError("Unsupported backend preset options")
        if self.client_tools and (self.research or self.token_count_mode != "vllm" or self.overflow != "reject"):
            raise ValueError("Client tools require exact counting, reject overflow and no research loop")
        if self.research and (self.token_count_mode != "vllm" or self.overflow != "reject"):
            raise ValueError("Research requires exact vLLM token counting and reject overflow")
        if self.compaction.summarize_tool_results and not self.client_tools:
            raise ValueError("Tool evidence summarization requires a client-tools profile")
        if self.chat_memory and not self.memory_recall.enabled:
            raise ValueError("Chat memory saves require a configured recall scope")
        if self.compaction.enabled:
            if self.token_count_mode != "vllm" or self.overflow != "reject":
                raise ValueError("Compaction requires exact vLLM counting and reject overflow")
            if self.compaction.max_summary_tokens + self.context_margin >= self.context_window:
                raise ValueError("Compaction summary must leave room for source history")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_request_bytes: int = Field(default=262144, gt=0)
    max_concurrent_requests: int = Field(default=4, gt=0)
    request_timeout_seconds: float = Field(default=180, gt=0)
    profiles: dict[str, Profile] = Field(min_length=1)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = Field(default=None, max_length=16)
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=128)
    # Client compatibility only: accept these typed fields, then discard them.
    reasoning_content: str | None = Field(default=None, exclude=True)
    reasoning: str | None = Field(default=None, exclude=True)


    @field_validator("content", mode="before")
    @classmethod
    def text_parts(cls, value):
        # Some clients represent extracted Markdown as multiple text blocks.
        # Never coerce file/image/audio blocks to text or silently drop them.
        if isinstance(value, list):
            if not 1 <= len(value) <= 512 or any(
                not isinstance(p, dict) or set(p) != {"type", "text"}
                or p["type"] != "text" or not isinstance(p["text"], str) for p in value):
                raise ValueError("Only plain text content parts are supported; extract file text in the client")
            return "".join(p["text"] for p in value)
        return value


class Chat(BaseModel):
    # Only validated fields below can enter the upstream payload.
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=512)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)  # server-owned
    seed: int | None = None
    stop: str | list[str] | None = None  # accepted, server policy wins
    stream_options: dict | None = None
    user: str | None = None  # accepted, untrusted identity; never forwarded/logged
    metadata: dict | None = None
    n: Literal[1] = 1
    # Only the opt-in client-tools profile forwards function definitions and choices.
    tools: list[ToolDefinition] | None = Field(default=None, max_length=32)
    tool_choice: Literal["none", "auto", "required"] | NamedChoice | None = None
    parallel_tool_calls: bool | None = None


def create_app(config_path=None, api_key=None, backend_url=None, transport=None, identity_path=None, memory_path=None):
    @asynccontextmanager
    async def lifespan(app):
        path = Path(config_path or os.getenv("HARNESS_CONFIG", "profiles.yaml")).resolve()
        settings = Settings.model_validate(yaml.safe_load(path.read_text()))
        key = api_key or os.getenv("HARNESS_API_KEY", "")
        app.state.identity = IdentityProvider(identity_path or os.getenv("HARNESS_IDENTITY_CONFIG"), key, settings.profiles)
        url = (backend_url or os.getenv("GEN_URL", "http://gpu-node:8000/v1")).rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or not parsed.path.endswith("/v1"):
            raise RuntimeError("GEN_URL must be an http(s) URL ending in /v1, without credentials/query")
        research_stores = {}
        prompts = {}
        fingerprints = {}
        for name, profile in settings.profiles.items():
            if profile.backend_model.startswith("REPLACE_"):
                raise RuntimeError(f"Configure backend_model for profile {name}")
            prompt = (path.parent / profile.system_prompt_file).read_text().strip()
            if not prompt:
                raise RuntimeError(f"Empty system prompt for {name}")
            prompts[name] = prompt + "\n\nRules:\n" + "\n".join(f"- {r}" for r in profile.rules)
            if profile.client_tools:
                prompts[name] += "\n\n" + CLIENT_TOOL_RULES
            if profile.compaction.enabled:
                prompts[name] += "\n\n" + CONTEXT_RULES
            if profile.memory_recall.enabled:
                prompts[name] += "\n\n" + RECALL_RULES
            if profile.chat_memory:
                prompts[name] += "\n\n" + CHAT_MEMORY_RULES
            if profile.research:
                research_stores[name] = NoteStore(path.parent, profile.research.notes_directory)
            fingerprints[name] = hashlib.sha256(json.dumps({"profile": profile.model_dump(), "prompt": prompts[name]}, sort_keys=True).encode()).hexdigest()
        app.state.research_stores = research_stores
        app.state.settings = settings
        app.state.key = key
        app.state.prompts = prompts
        app.state.fingerprints = fingerprints
        app.state.slots = asyncio.Semaphore(settings.max_concurrent_requests)
        headers = {}
        if os.getenv("GEN_API_KEY"):
            headers["Authorization"] = f"Bearer {os.environ['GEN_API_KEY']}"
        async with httpx.AsyncClient(headers=headers, timeout=settings.request_timeout_seconds, transport=transport, trust_env=False, follow_redirects=False) as client:
            app.state.client = client
            app.state.url = url
            memory_config_path = memory_path or os.getenv("HARNESS_MEMORY_CONFIG")
            app.state.memory = MemoryStore(MemoryConfig.load(memory_config_path)) if memory_config_path else None
            try:
                if app.state.memory:
                    await app.state.memory.pool.open()
                yield
            finally:
                if app.state.memory:
                    await app.state.memory.pool.close()

    app = FastAPI(title="Local Model Harness", lifespan=lifespan)

    async def auth(request: Request):
        principal = app.state.identity.authenticate(request.headers.get("authorization", ""))
        request.state.principal = principal
        return principal

    install_routes(app, auth)
    from memory_ui import install_ui
    install_ui(app)

    @app.exception_handler(HTTPException)
    async def error(request, exc):
        return JSONResponse({"error": {"message": exc.detail, "type": "harness_error", "code": exc.status_code}}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/v1/identity", dependencies=[Depends(auth)])
    async def current_identity(request: Request):
        p = request.state.principal
        return {"kind": p.kind, "actor_id": p.actor_id, "profiles": sorted(p.profiles),
                "tools": sorted(p.tools), "collections": sorted(p.collections),
                "expires_at": p.expires_at,
                "client_tools": p.client_tools, "backend_metrics": p.backend_metrics,
                "memory_scopes": allowed_scopes(app.state.memory.config if app.state.memory else None, p),
                "memory_permissions": sorted(memory_permissions(app.state.memory.config if app.state.memory else None, p))}

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready", dependencies=[Depends(auth)])
    async def ready():
        available = await catalog(app)
        for profile in app.state.settings.profiles.values():
            if profile.backend_model == "auto":
                await resolve_profile(app, profile, available)
            elif profile.backend_model not in available:
                raise HTTPException(503, "Configured backend model not loaded")
            else:
                await resolve_profile(app, profile, available)
        return {"status": "ready"}

    @app.get("/v1/backend/metrics", dependencies=[Depends(auth)])
    async def metrics(request: Request):
        return await backend_metrics(app, request.state.principal)

    @app.get("/v1/models", dependencies=[Depends(auth)])
    async def models(request: Request):
        return {"object": "list", "data": [{"id": name, "object": "model", "created": 0, "owned_by": "local-harness"} for name in app.state.settings.profiles if request.state.principal.can_profile(name)]}

    @app.post("/v1/chat/completions", dependencies=[Depends(auth)])
    async def chat(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > app.state.settings.max_request_bytes:
                raise HTTPException(413, "Request exceeds configured byte limit")
        try:
            body = Chat.model_validate_json(raw)
        except ValidationError as exc:
            # Locations/types only: never log rejected values or conversation text.
            issues = [
                {"field": ".".join(str(part) for part in error["loc"])[:100],
                 "type": error["type"]}
                for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]
            ]
            log.info(json.dumps({"event": "request_validation_failed", "issues": issues}))
            detail = "; ".join(f"{item['field'] or 'body'} ({item['type']})" for item in issues)
            raise HTTPException(400, "Invalid request: " + detail + ". This profile supports text chat only.")
        principal = request.state.principal
        # Identity and authorization are server-owned; body.user/metadata are not claims.
        profile = app.state.settings.profiles.get(body.model)
        if profile is None:
            raise HTTPException(404, "Unknown harness model profile")
        app.state.identity.audit(principal, "profile", body.model, principal.can_profile(body.model))
        principal.require_profile(body.model)
        if body.max_tokens is not None and body.max_completion_tokens is not None:
            raise HTTPException(400, "Use only one output token parameter")
        if profile.client_system_prompt == "reject" and any(m.role in {"system", "developer"} for m in body.messages):
            raise HTTPException(400, "Client system/developer prompts are disabled")
        history, tool_payload = prepare_history(body, profile, principal)
        if body.stream_options is not None:
            if body.stream_options.keys() - {"include_usage"} or not isinstance(body.stream_options.get("include_usage", False), bool):
                raise HTTPException(400, "Only stream_options.include_usage is supported")
        saved = await chat_save_response(app, profile, principal, history, body.model, body.stream, body.stream_options is None or body.stream_options.get("include_usage", False))
        if saved is not None:
            return saved
        profile = await resolve_profile(app, profile)
        messages = [{"role": "system", "content": app.state.prompts[body.model]}, *history]
        payload = {"model": profile.backend_model, "messages": messages, "stream": body.stream,
                   "temperature": profile.temperature, "top_p": profile.top_p,
                   "presence_penalty": profile.presence_penalty,
                   "max_tokens": profile.max_output_tokens, **profile.backend_options, **tool_payload}
        payload = {k: v for k, v in payload.items() if v is not None}
        if profile.seed is not None:
            payload["seed"] = profile.seed
        if profile.stop:
            payload["stop"] = profile.stop
        for param in profile.allow_client_params:
            value = (body.max_tokens or body.max_completion_tokens) if param == "max_tokens" else getattr(body, param)
            if value is not None:
                payload[param] = min(value, profile.max_output_tokens) if param == "max_tokens" else value
        if body.stream_options is not None:
            if body.stream:
                payload["stream_options"] = body.stream_options
        if body.stream and body.stream_options is None:
            payload["stream_options"] = {"include_usage": True}
        recall_state = await apply_recall(app, profile, principal, messages)
        if profile.research:
            result = await research_response(app, profile, payload, body.model, body.stream, principal)
            result.headers.update({**recall_headers(recall_state), **runtime_headers(profile)})
            return result
        if app.state.slots.locked():
            raise HTTPException(429, "Harness concurrency limit reached", headers={"Retry-After": "1"})
        await app.state.slots.acquire()
        rid = str(uuid.uuid4())
        started = time.monotonic()
        deadline = profile.request_timeout_seconds or app.state.settings.request_timeout_seconds
        response = None
        transferred = False
        dropped = 0
        count = None
        outcome = "failed"

        def audit(status):
            log.info(json.dumps({"event": "generation", "request_id": rid, "profile": body.model,
                "profile_sha256": app.state.fingerprints[body.model], "backend_model": profile.backend_model,
                "status": status, "elapsed_ms": round((time.monotonic() - started) * 1000),
                "prompt_tokens_or_estimate": count, "token_count_mode": profile.token_count_mode,
                "dropped_messages": dropped, "temperature": payload.get("temperature"), "top_p": payload.get("top_p"),
                "max_tokens": payload["max_tokens"], "seed": payload.get("seed"),
                "presence_penalty": payload.get("presence_penalty"),
                "enable_thinking": profile.backend_options.get("chat_template_kwargs", {}).get("enable_thinking"),
                "reasoning_effort": profile.backend_options.get("chat_template_kwargs", {}).get("reasoning_effort")}))

        try:
            async with asyncio.timeout(deadline):
                messages, compact_state = await compact_context(app, profile, payload, messages, principal, rid, payload.get("tools"))
                payload["messages"] = messages
                while True:
                    if profile.token_count_mode == "vllm":
                        token_payload = {"model": profile.backend_model, "messages": messages, "add_generation_prompt": True}
                        if payload.get("tools"):
                            token_payload["tools"] = payload["tools"]
                        if "chat_template_kwargs" in profile.backend_options:
                            token_payload["chat_template_kwargs"] = profile.backend_options["chat_template_kwargs"]
                        token_response = await app.state.client.post(app.state.url[:-3] + "/tokenize", json=token_payload, timeout=deadline)
                        token_response.raise_for_status()
                        count = token_response.json()["count"]
                        if type(count) is not int or count < 0:
                            raise ValueError("Invalid token count")
                    else:
                        count = sum(len(m["content"].encode("utf-8")) + 32 for m in messages) + 32
                    if count + payload["max_tokens"] + profile.context_margin <= profile.context_window:
                        break
                    next_user = next((i for i in range(2, len(messages)) if messages[i]["role"] == "user"), None)
                    if profile.overflow == "reject" or next_user is None:
                        raise HTTPException(400, "Context budget exceeded; shorten the conversation or use a larger configured profile")
                    dropped += next_user - 1
                    del messages[1:next_user]
                response = await app.state.client.send(app.state.client.build_request("POST", app.state.url + "/chat/completions", json=payload, timeout=deadline), stream=True)
                response.raise_for_status()
                headers = {"X-Request-ID": rid, "X-Harness-Profile-SHA256": app.state.fingerprints[body.model],
                           "X-Harness-Dropped-Messages": str(dropped), **recall_headers(recall_state), **context_headers(compact_state), **runtime_headers(profile)}
                if not body.stream:
                    await response.aread()
                    result = response.json()
                    attach_accounting(result, compact_state)
                    record_usage(result.get("usage"), rid, body.model, profile.backend_model)
                    result["model"] = body.model
                    if compact_state["status"] == "compacted":
                        for choice in result.get("choices", []):
                            msg = choice.get("message", {})
                            if isinstance(msg.get("content"), str):
                                msg["content"] += context_notice(compact_state)
                        result["harness_context"] = compact_state
                    outcome = "completed"
                    return JSONResponse(result, headers=headers)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise ValueError("Backend did not return SSE")

            async def events():
                status = "cancelled"
                notice_sent = False
                stream_identity = {"id": "chatcmpl-" + rid, "object": "chat.completion.chunk", "created": int(time.time())}
                def notice_event():
                    return "data: " + json.dumps({**stream_identity, "model": body.model,
                        "choices": [{"index": 0, "delta": {"content": context_notice(compact_state)}, "finish_reason": None}]}) + "\n\n"
                try:
                    remaining = deadline - (time.monotonic() - started)
                    async with asyncio.timeout(max(0.001, remaining)):
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                if compact_state["status"] == "compacted" and not notice_sent:
                                    yield notice_event()
                                    notice_sent = True
                                status = "completed"
                                yield "data: [DONE]\n\n"
                                return
                            event = json.loads(data)
                            if "error" in event:
                                raise ValueError("Backend stream error")
                            attach_accounting(event, compact_state)
                            record_usage(event.get("usage"), rid, body.model, profile.backend_model)
                            event["model"] = body.model
                            stream_identity.update({k: event[k] for k in ("id", "created", "object") if k in event})
                            if (compact_state["status"] == "compacted" and not notice_sent
                                    and any(c.get("finish_reason") is not None for c in event.get("choices", []))):
                                # Some backends include the final text in the stop chunk.
                                # Deliver that text before our notice, then the stop marker.
                                content_choices = [{**c, "finish_reason": None} for c in event.get("choices", []) if c.get("delta")]
                                if content_choices:
                                    yield "data: " + json.dumps({**event, "choices": content_choices, "usage": None}) + "\n\n"
                                    event = {**event, "choices": [{**c, "delta": {}} for c in event["choices"]]}
                                yield notice_event()
                                notice_sent = True
                            yield "data: " + json.dumps(event) + "\n\n"
                        raise ValueError("Backend stream ended without DONE")
                except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
                    status = "stream_failed"
                    yield 'data: {"error":{"message":"Backend stream interrupted","type":"upstream_error"}}\n\n'
                    yield "data: [DONE]\n\n"
                finally:
                    try:
                        await response.aclose()
                    finally:
                        app.state.slots.release()
                        audit(status)

            transferred = True
            return StreamingResponse(events(), media_type="text/event-stream", headers={**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        except (httpx.TimeoutException, TimeoutError):
            raise HTTPException(504, "Backend deadline exceeded")
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(502, "Backend request failed; check model, tokenizer support, and server configuration")
        finally:
            if not transferred:
                try:
                    if response is not None:
                        await response.aclose()
                finally:
                    app.state.slots.release()
                    audit(outcome)

    return app


app = create_app()
