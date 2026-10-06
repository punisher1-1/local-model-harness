# Local Model Harness

A Python/FastAPI template for controlling local chat models through BoltAI or Open WebUI.
The harness owns policy and generation settings; the inference server owns model
loading, GPU execution, and the physical context window.

```text
Open WebUI → local-model-harness :8200/v1 → local inference server /v1
           → existing RAG gateway :8100/v1 → retrieval → inference
```

This is an independent repository, developed alongside the
[Homelab RAG project](https://github.com/punisher1-1/homelab-rag). The assistant and creative profiles have no corpus-retrieval tools (optional saved-memory recall is separate). The optional research
profile retrieves bundled synthetic notes using local Python tools, with no
embedding or database dependency. It uses the same OpenAI-compatible connection
pattern, preserves chat history, and exposes named profiles instead of backend model
names. Multiple profiles can use the same loaded model. The default profiles are
`local-assistant`, `local-creative`, `local-research`,
`local-tools`, `local-home`, and `local-work`. Memory is disabled by default;
the home/work profiles become separate memory scopes only after you configure storage.
They follow the single model currently served by vLLM. Exact-ID presets preserve the
Qwen recipe; unknown models inherit backend generation defaults. `local-tools` passes
attached client functions back to BoltAI/Open WebUI for execution.
See [TOOLS_AND_MODELS.md](TOOLS_AND_MODELS.md) and [TELEMETRY.md](TELEMETRY.md).

## Quick start

Requires Python 3.11+ or Docker. Run commands from this directory.

1. Copy `.env.example` to `.env`. Generate a random `HARNESS_API_KEY` using the
   command in that file. Set `GEN_URL` to your actual local backend URL including
   `/v1`, and `GEN_API_KEY` if required. No outbound cloud service is configured.
2. The bundled `backend_model: auto` requires exactly one ID and `max_model_len` from
   vLLM's `GET /v1/models`. Pin an exact ID if multiple models/aliases are advertised.
3. Review the context ceiling and exact-ID presets in `profiles.yaml`. Auto mode caps
   the chosen window to the advertised model capacity; pinned windows are operator-owned.
4. The defaults target vLLM and use its exact chat `/tokenize` endpoint. For
   Ollama, llama.cpp, LM Studio, or another server without that endpoint, use the
   [portable setup](#other-openai-compatible-servers) below.
5. The tracked `prompts/assistant.md.example` is ready to use. For a personal prompt,
   copy it to ignored `prompts/assistant.md` and update the desired profiles'
   `system_prompt_file`. Prompts are visible to the model; keep credentials out.
6. Memory needs no configuration for the default setup. Enable it separately
   using [MEMORY.md](MEMORY.md).
7. Start the service:

```bash
docker compose up -d --build
```

Native alternative:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --env-file .env --host 0.0.0.0 --port 8200 --no-access-log
```

In default service-key mode, startup intentionally fails for a missing/placeholder API key, placeholder model,
invalid profile, or missing/empty prompt. Config and prompts are loaded once at
startup. After profile/prompt edits: `docker compose restart`. After `.env` edits:
`docker compose up -d --force-recreate`. After code edits: rebuild.

### Other OpenAI-compatible servers

Use `profiles.portable.yaml` for a basic assistant without vLLM-specific tools,
compaction, or memory. It uses `utf8_estimate`, which is a heuristic rather than a
guaranteed token bound. These servers have not been live-tested with this template.

1. Set `GEN_URL` in `.env` to your backend URL ending in `/v1` and configure its key
   if needed. Use an address reachable from inside Docker when running containers.
2. Set `HARNESS_CONFIG=profiles.portable.yaml` in `.env`.
3. Edit `profiles.portable.yaml`: replace `backend_model: local-model` with the exact
   ID advertised by your backend's `/v1/models`. Set `context_window` to its actual
   configured capacity and keep `max_output_tokens` plus the margin below it.
4. Start with either command above. In Docker, the portable config is included in
   the image: rebuild after editing it. If switching an existing deployment, also
   recreate the container to apply `.env` changes.

Simply changing `token_count_mode` in the vLLM defaults is insufficient: enabled
compaction, research, and client tools require exact vLLM counting. The portable
config disables those features and pins the backend model instead of using vLLM
capacity discovery. Run the chat smoke check against your server before sharing it.

### Connect Open WebUI

Add an **OpenAI API** connection under Admin Settings → Connections:

- Base URL: `http://<harness-host>:8200/v1`
- API key: the actual `HARNESS_API_KEY` from `.env`
- Select `local-assistant`, `local-creative`, or `local-research` in the model picker.

Use a host/IP reachable from Open WebUI's container, not its `localhost`.
Leave the existing Parade-API connection in place to keep RAG available separately.
Do not select the raw backend connection when you want harness policy to apply.
Disable **Built-in Tools** and deselect attached tools for assistant, creative, and demo research.
The harness owns research tool execution; Open WebUI must not inject another tool set.
These three profiles reject nonempty tool definitions and tool histories. The separate
`local-tools` profile accepts OpenAI function schemas and complete tool exchanges.
All profiles remain text-only and reject images, audio, and unsupported fields. Empty/null `tools` and optional `tool_choice: auto|none` and
`parallel_tool_calls` are accepted for client compatibility and never forwarded
to the inference server on the three non-client-tool profiles. Forced tool choices
are supported only on `local-tools`.
Open WebUI background title/follow-up requests use the same profile if routed here;
choose a separate task model in Open WebUI if its system-based formatting is needed.
Client system/developer messages are discarded by default, including instructions
Open WebUI adds through custom prompts or its own retrieval features.

### Smoke check

Set a shell variable `HARNESS_API_KEY` to your configured key before these calls.

```bash
curl -fsS http://localhost:8200/health/live
curl -fsS http://localhost:8200/health/ready -H "Authorization: Bearer $HARNESS_API_KEY"
curl -fsS http://localhost:8200/v1/models -H "Authorization: Bearer $HARNESS_API_KEY"
curl -N http://localhost:8200/v1/chat/completions \
  -H "Authorization: Bearer $HARNESS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-assistant","messages":[{"role":"user","content":"Explain what a reverse proxy does in three sentences."}],"stream":true}'
```

Readiness checks backend reachability and that all configured model IDs are loaded.
It does not test the tokenizer/chat template; the chat smoke test does that.
Readiness is authenticated; liveness exposes no configuration or network details.

## Identity scaffold

[IDENTITY.md](IDENTITY.md) explains the opt-in JWT verifier and role-based profile,
tool and demo-collection permissions. The default deployment still uses the shared
lab service key; no enterprise login/token flow is enabled. `/v1/identity` reports
the authenticated context. [ADR-001](docs/ADR-001-identity-boundary.md) records the
architecture decision and remaining work.

## Long conversations and BoltAI

[COMPACTION.md](COMPACTION.md) documents the new bounded context-compaction stage.
All six default vLLM profiles summarize older visible turns near their input limit,
preserve
the current request, recheck the complete prompt, and show a notice when compaction
is used. Summaries are temporary request context, not saved memories. They may lose
detail and add latency; the original transcript remains in your client.

BoltAI's resubmitted `reasoning_content` and `reasoning` string/null fields are accepted
and discarded. They do not enter token counts, summaries or generation. Other unknown
fields and non-text/tool inputs remain rejected.

## Persistent memory

Memory storage, recall, and chat saves are **opt-in**. The default profiles work
without a database. [MEMORY.md](MEMORY.md) explains how to provision a dedicated
PostgreSQL database, enable recall and explicit saves, and manage permissions.

When enabled, save exact text with `Remember: fact: <exact text>` on a
`chat_memory` profile. Automatic capture stays off. `local-home` and `local-work`
use distinct configured memory scopes; start separate conversations because
supplied chat history is not isolated by memory scope.

The browser at `/memory` uses your harness bearer credential. It can manage saved
memories only after storage and permissions are configured. A shared service key
means every holder shares the same service-owned records; use verified individual
identities before storing private memories for multiple club members.

## Local research: first tool-enabled profile

[RESEARCH.md](RESEARCH.md) explains the implemented tool loop and its limits.
`local-research` has two server-owned read-only tools: `search_notes` and `read_note`.
They operate only on the bundled **synthetic** `demo_notes` catalog. No private vault,
MCP server, shell, internet search, database, or memory service is connected to those
research tools. The separate explicit memory API is described above.

Try: “Using the demo notes, did Cedar Works meet its recovery objectives in the last
exercise? Explain the numbers and cite the supporting notes.”

Keep Open WebUI Built-in Tools off for this profile. Research emits SSE heartbeats
while planning and returns the final answer together with a tool activity summary.
The final answer is buffered in this version, not token-streamed. Assistant and
creative streaming are unchanged.

## Qwen3.8 profile preset

The exact-ID `qwen3.8-27b` presets explicitly select the recipes from the
[Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B), checked 2026-09-06.
These are model-specific starting points, not universal enterprise defaults.

| Setting | local-assistant | local-creative |
|---|---|---|
| Thinking | Disabled | Enabled, explicit `medium` |
| Temperature / top-p | 0.7 / 0.80 | 1.0 / 0.95 |
| Presence penalty | 1.5 | 0.0 |
| Top-k / min-p / repetition penalty | 20 / 0.0 / 1.0 | 20 / 0.0 / 1.0 |
| Output budget (thinking + answer) | 2,048 | 8,192 |
| Overall request deadline | Global 180 seconds | 600 seconds |
| Total context budget | 16,384 | 16,384 |

The custom Qwen template remains on vLLM. The harness sends `chat_template_kwargs`
identically to token counting and generation; it does not render the template itself.
Explicit `medium` overrides the custom template's `low` default. Creative was reduced from xhigh after a real discussion-post task exhausted its
output budget before the final answer (2026-09-06). Medium changes the template
instruction, not a guaranteed reasoning-token limit. Preserved thinking is
disabled; incoming historical `reasoning_content`/`reasoning` fields are accepted
as compatibility metadata and discarded.
Current response reasoning fields pass through to the UI, but are not stored as memory.
The 8,192-token creative reservation leaves 7,936 prompt tokens after the 256-token
margin. It is a starting budget, not a promise that every thinking task will finish.
A 600-second deadline permits longer tasks; it does not make every task take that long.
Keep proxy/UI timeouts consistent. No vLLM restart is required for profile changes.

The harness's explicit parameters override `--generation-config auto` defaults.
`presence_penalty` remains server-owned even if the client sends one. For a different
model, auto mode omits Qwen-specific options and inherits backend generation defaults.
Add an exact-ID preset when that model needs explicit sampling/template controls.

## Controls you own

| Control | Location / behavior |
|---|---|
| System prompt | `prompts/assistant.md.example`; configure a separate file per profile if desired |
| Rules | Profile `rules`; appended to the server system prompt |
| Model identity | Profile `backend_model`: `auto` follows one advertised model per request, or pin an ID |
| Sampling | `temperature`, `top_p`, optional `seed`, `stop` |
| Output limit | `max_output_tokens`; also reserves room in the context budget |
| Context | `context_window`, `context_margin`, `token_count_mode`, `overflow` |
| Client overrides | `allow_client_params`; empty by default |
| Client system text | `client_system_prompt: discard` or `reject` |
| Backend extensions | Server-only `backend_options`: `top_k`, `min_p`, `repetition_penalty`, `chat_template_kwargs` |
| Capacity | Global `max_concurrent_requests`, `max_request_bytes`, `request_timeout_seconds` |
| Authentication | Separate harness and upstream keys in environment variables |
| Traceability | JSON metadata logs; request ID, profile hash, resolved model and context headers |
| UI tools | `client_tools: true` on `local-tools`; executor permissions remain in the UI |
| Usage / KV cache | OpenAI usage chunks; authenticated `/v1/backend/metrics`; see TELEMETRY.md |

To allow experiments, use `allow_client_params: [temperature, top_p, max_tokens, seed]`.
Client output limits are always capped at the profile maximum. Both `max_tokens`
and `max_completion_tokens` are accepted, but not together. The gateway sends
`max_tokens` upstream. Invalid parameter ranges fail even when overrides are locked.
Client `stop` is accepted for compatibility but server `stop` always wins. Unknown
fields fail rather than being passed through. Backend extension names are validated;
their values and model-specific support must be checked against your serving stack.

The profiles are request settings, not instructions to load two models or allocate
additional GPUs. Changing a seed does not promise deterministic GPU output.
For reproducible vLLM experiments, also control its generation configuration
(e.g. `--generation-config vllm`), chat template, quantization, and serving version.
Only exposed parameters are controlled here; unspecified backend defaults still apply.

## Context budgeting

Admission requires:

```text
rendered prompt tokens + reserved output tokens + margin <= profile context window
```

`vllm` mode sends the final server prompt plus history to the backend's `/tokenize`
with `add_generation_prompt: true`, including configured `chat_template_kwargs`.
An unavailable/malformed tokenizer response fails closed. The count is exact only
when tokenization and generation use the same model/chat-template settings. Pin those
settings and run a boundary test on your deployed version before relying on the cap.

`utf8_estimate` counts UTF-8 bytes plus fixed per-message overhead. It is deliberately
generous for ordinary text, but **is a heuristic, not a guaranteed token bound** for
all tokenizers/templates. It can reject conversations that would actually fit. The
inference server remains the final authority; it may reject or truncate depending
on its implementation. Use exact tokenization before claiming an enforced token cap
on a different backend.

`overflow: reject` returns a clear 400 without modifying history. `trim_oldest`
removes complete older user turns and their assistant replies until the request
fits. It always retains the server prompt and latest user turn; if those do not fit,
the request fails. Removed-message count is logged and returned in
`X-Harness-Dropped-Messages`. Open WebUI may not display this header; prefer `reject`
when users must be explicitly aware of lost history. With compaction disabled, the rules above apply directly. Enabled compaction first
summarizes eligible older history near the limit; see COMPACTION.md.
Open WebUI or BoltAI must still send history with each request. Profiles with `memory_recall` enabled
also receive a bounded selection of saved memories, counted within the same budget.

Setting the harness window **does not increase the model server's window**. vLLM's
launch configuration controls its capacity. Ollama's OpenAI endpoint has no context
size parameter: configure an Ollama model with `PARAMETER num_ctx` (or its server
context setting) separately. LM Studio, llama.cpp, and Unsloth can be used via their
OpenAI-compatible chat endpoint with `utf8_estimate`, subject to validation against
their supported fields; they have not been live-tested with this template.

## Operational behavior and enterprise boundary

This is a tested starting template, not a completed enterprise security platform.
Research uses a shared synthetic catalog visible to every holder of the harness key;
do not replace it with sensitive notes before integrating trusted user tokens and
resource-level authorization.

- Default authentication uses a shared service key; every holder has the same lab
  service identity and configured profiles. Opt-in JWT mode verifies configured
  public keys and enforces role-based profile/tool/demo-collection grants. Work
  token forwarding, key refresh, and per-document/tenant authorization are pending;
  see [IDENTITY.md](IDENTITY.md).
- Prompt rules guide model behavior; they cannot guarantee truthfulness, defeat prompt
  injection, prevent data disclosure, or enforce authorization. No secrets belong in
  the system prompt. Tools require a separate authenticated execution/approval layer.
- Only the configured backend URL is used. Redirects and environment proxy discovery
  are disabled. No fallback silently sends data elsewhere. Use firewall/egress rules
  to make “local only” an infrastructure guarantee and prevent direct backend bypass.
- Place TLS and per-user rate limits at an authenticated reverse proxy. Streaming
  needs proxy buffering disabled and an adequate proxy timeout. The container binds
  port 8200 on all host interfaces; restrict it to your intended network.
- Capacity is bounded per process, and excess admitted chat requests receive 429.
  Run one worker for the configured concurrency budget; replicas/workers multiply it.
  Request byte limits are applied while reading; ingress connection/slow-upload limits
  belong at the reverse proxy. Generation has an overall deadline, including streaming.
- HTTP upstream errors are detected before streaming headers. Mid-stream failure is
  an SSE error, never fabricated assistant text. Backend error bodies are not returned
  or logged. There are no automatic generation retries that could duplicate work.
- Logs contain profile/model identity, full profile hash, effective sampling values,
  prompt count, trimmed-message count, duration, and completion/failure status. They
  exclude prompt/response text, keys, and client-supplied identity. Validation/auth/
  admission failures are not generation events. Add proxy-level audit coverage for
  these failures and a durable log sink/retention policy for production.
- Prompts/configs must be version-controlled to interpret the recorded hash later.
  Backend software/model artifact provenance and quality scoring are not collected
  automatically. Capture model revision, quantization, server image digest, and
  launch flags alongside any model comparison, as in the existing RAG eval practice.

## Verify and extend

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests run against a mocked backend with no GPU, network, API key, or RAG service.
They cover policy precedence, auth, model selection, parameter caps, input validation,
context rejection/turn trimming, tokenizer failure, capacity, and streaming errors.
Live model quality, real network disconnect behavior, load, and Docker deployment
still need validation in your environment.

Suggested next extensions: a local golden-prompt quality suite with recorded config
and model provenance; exact token counting adapters for other servers; enterprise token forwarding and key rotation; metrics/central logs; then opt-in tool execution with
separate authorization. Keep sampling experiments under named profiles so changing
Open WebUI defaults cannot quietly alter the baseline.

## Future role-scoped agents (design only)

[ROLE_AGENTS.md](ROLE_AGENTS.md) sketches payroll and help desk assistants sharing
one model while receiving different server-enforced capabilities and resource scopes.
Search for `FUTURE(role-agents)` in the code/config to find the planned integration
points. These comments do not enable new profiles, permissions, tools, or endpoints.

## Design references

Backend contracts checked against official documentation:
[vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
and [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).

## BoltAI tool/Markdown troubleshooting

For `application/octet-stream` attachment errors or oversized fetched-page results,
see [BOLTAI_TROUBLESHOOTING.md](BOLTAI_TROUBLESHOOTING.md). The 2026-09-11 fix enables
bounded current-tool evidence summaries and full available context on `local-tools`.
Plain text content arrays are accepted; binary files still need client-side extraction.

## License

[MIT](LICENSE). Model weights and third-party services have their own terms.

## Publishing a copy

Do not upload `.env`, personal prompts, identity/memory configuration, database
backups, or Git history containing private deployment details. `.gitignore` affects
future tracking; it cannot remove files or details from earlier commits.

For a source-only release, export the reviewed public files without `.git` or
deployment-only files. Extract them into a new directory and create a new
repository from that source. Making the original repository public would also expose its existing history. Keep that repository private until
its history is separately sanitized.
