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
names. Multiple profiles can use the same loaded model. The profiles are `local-assistant`, `local-creative`, `local-research`, and `local-tools`.
They follow the single model currently served by vLLM. Exact-ID presets preserve the
Qwen recipe; unknown models inherit backend generation defaults. `local-tools` passes
attached client functions back to BoltAI/Open WebUI for execution.
See [TOOLS_AND_MODELS.md](TOOLS_AND_MODELS.md) and [TELEMETRY.md](TELEMETRY.md).

## Built-in chat client

The Docker image includes a neutral web client at `/chat/`, with profile/workflow
selection, streaming Markdown, reasoning, token usage, persistent conversation
history, projects that group chats with their own default tools and workflow, and
your own Markdown skills that a chat or project can apply. Credentials clear on reload; saved chats return after reconnecting. See [frontend/README.md](frontend/README.md)
for setup, authentication boundaries, and current limitations.

## Quick start

Requires Python 3.11+ or Docker. Run commands from this directory.

1. Copy `.env.example` to `.env`. Generate a random `HARNESS_API_KEY` using the
   command in that file. Set `GEN_URL` to your actual local backend URL including
   `/v1`, and `GEN_API_KEY` if required. No outbound cloud service is configured.
2. The bundled `backend_model: auto` requires exactly one ID and `max_model_len` from
   vLLM's `GET /v1/models`. Pin an exact ID if multiple models/aliases are advertised.
3. Review the context ceiling and exact-ID presets in `profiles.yaml`. Auto mode caps
   the chosen window to the advertised model capacity; pinned windows are operator-owned.
4. For vLLM, keep `token_count_mode: vllm`. For a server without vLLM's chat
   `/tokenize` endpoint, select `utf8_estimate` and review its limitation below.
5. Start the service:

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

[IDENTITY.md](IDENTITY.md) explains the identity modes and role-based profile, tool
and collection permissions. The default deployment uses the shared lab service key.
OIDC mode ([ADR-004](docs/ADR-004-oidc-sign-in.md)) signs each person in to `/chat/`
with a passkey through Pocket ID, gives them their own chats, projects, skills and
grants, and keeps a scoped service key for apps such as Open WebUI. `/v1/identity`
reports the authenticated context. [ADR-001](docs/ADR-001-identity-boundary.md)
records the original identity boundary.

## Long conversations and BoltAI

[COMPACTION.md](COMPACTION.md) documents the new bounded context-compaction stage.
All four lab profiles summarize older visible turns near their input limit, preserve
the current request, recheck the complete prompt, and show a notice when compaction
is used. Summaries are temporary request context, not saved memories. They may lose
detail and add latency; the original transcript remains in your client.

BoltAI's resubmitted `reasoning_content` and `reasoning` string/null fields are accepted
and discarded. They do not enter token counts, summaries or generation. Other unknown
fields and non-text/tool inputs remain rejected.

## Persistent memory

Explicit chat saves are available on assistant, creative, tools, home, and work
profiles: `Remember: fact: <exact text>`. The harness returns the saved scope and
memory ID. Automatic capture stays off; see [MEMORY.md](MEMORY.md).

Use `local-home` and `local-work` for isolated home/work memory recall with UI tool
support. Existing profiles retain legacy memories. Start separate conversations
for each environment; supplied chat history is not isolated by memory scope.

Use `it-troubleshoot` for guided IT troubleshooting. Its default workflow,
`troubleshoot-session`, works one diagnostic step per turn, searches the knowledge base's
`it` collection first, and ends every reply with a case log. When the problem is solved,
choose **Troubleshooting write-up** in the Workflow menu to turn the session into
documentation; it is saved to the vault under `Troubleshooting/` only when you ask. The
profile has no memory, so it can serve as the template for a work deployment. Grant it to
admins only until it is tested.

Use `local-bench` for benchmark prompts. It has the same tools and sampling as
`local-home`, with `local-tools`' reasoning (medium effort, fixed 4,096-token budget),
the Python sandbox on by default, the number check on, and no memory or skills, so
saved data never changes an answer. Change it only on purpose,
and record the harness commit and model with each result. Grant it to admins only.

Manage saved memories in the browser at `/memory` on the harness host. Use your
harness API key (not the database password). See [MEMORY.md](MEMORY.md) for scope,
permissions, retry behavior, and integration with chat frontends.


[MEMORY.md](MEMORY.md) documents the deployed ParadeDB connection, explicit memory
API, CLI walkthrough, ownership, TLS, backups and rollback. Save/list/search/delete
are available on the harness host in the deliberately shared `lab-service` scope, retained until
explicit deletion. All four lab profiles now have **bounded read-only recall**:
up to four records and 4 KiB per request, with normal full-prompt token checks.
Automatic capture is off; save/delete remain explicit. Configure memory storage or
disable `memory_recall` in those profiles when reusing the template without ParadeDB.

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
| Thinking | Enabled, explicit `low` | Enabled, explicit `low` |
| Temperature / top-p | 0.7 / 0.80 | 1.0 / 0.95 |
| Presence penalty | 1.5 | 0.0 |
| Top-k / min-p / repetition penalty | 20 / 0.0 / 1.0 | 20 / 0.0 / 1.0 |
| Output budget (thinking + answer) | 8,192 | 8,192 |
| Overall request deadline | Global 180 seconds | 600 seconds |
| Total context budget | 16,384 | 16,384 |

The custom Qwen template remains on vLLM. The harness sends `chat_template_kwargs`
identically to token counting and generation; it does not render the template itself.
The preset explicitly selects `low`. Creative was previously reduced from xhigh to medium after a real discussion-post task exhausted its
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
| System prompt | `prompts/assistant.md`; use a separate file per profile if desired |
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

Reviewed local sources: `paradedb-rag-api/app.py` and its README; vault pages
`wiki/entities/open-webui.md`, `wiki/entities/parade-api.md`, and
`wiki/concepts/open-terminal-evaluation.md`. These informed server authority,
explicit model selection, preserved history, and separating tool execution from chat.
The vault describes historical deployments; no live infrastructure was changed or
assumed to have the same model loaded today.

Backend contracts checked against official documentation:
[vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
and [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).

## BoltAI tool/Markdown troubleshooting

For `application/octet-stream` attachment errors or oversized fetched-page results,
see [BOLTAI_TROUBLESHOOTING.md](BOLTAI_TROUBLESHOOTING.md). The 2026-09-11 fix enables
bounded current-tool evidence summaries and full available context on `local-tools`.
Plain text content arrays are accepted; binary files still need client-side extraction.

## Additional personal and course profiles

Extra profiles for one deployment (a family member's assistant, course-writing
workflows) belong in `profiles.local.yaml`, which is ignored by Git and mounted over
`profiles.yaml` by `docker-compose.override.yml`. Give each its own
`memory_recall.scope` and keep personal prompts in ignored files under `prompts/`.


### Reasoning output allowance and empty answers (2026-10-09)

Bundled chat profiles reserve 8,192 output tokens by default, shared by thinking
and the visible answer. `local-tools` now reserves 16,384 as described below. This does not enlarge the model context window. Input history,
system prompt, tools, output reservation, and safety margin must still fit.
The assistant and creative Qwen presets retain their 16,384 context ceilings.

An upstream response with reasoning but no final text or tool calls is an error,
not a successful answer. Nonstream requests return HTTP 502; streams emit an
`empty_response` error before `[DONE]`. Compaction notices cannot mask it.
Generation logs include finish reason and boolean text/tool/reasoning presence,
without generated content. A `length` finish means the output allowance was
exhausted; `stop` requires investigation of the upstream template/settings.
No automatic retry occurs, avoiding duplicate tool actions. Clients may still
show their own generic error instead of the SSE error detail.

The October 9 Onyx incident coincided with thinking-enabled requests consuming
all 4,096 output tokens. Historical logs did not record text presence, so this
is a likely explanation rather than proof of the original failure. Increasing
the allowance helps but cannot guarantee every reasoning task finishes.


### Bounded thinking for local-tools (2026-10-09 follow-up)

The Onyx retry confirmed `finish_reason=length`, 8,192 completion tokens,
reasoning present, and no text/tool calls. Its prompt was only 3,322 tokens;
compaction did not run. Increasing the shared output allowance alone was
insufficient for the six-section architecture benchmark.

`local-tools` now reserves 16,384 total output tokens and has a 600-second
request deadline. Its exact-ID Qwen preset sends `thinking_token_budget: 4096`
alongside medium thinking. The remainder is available for the visible answer.
At the live 75,000-token context ceiling and 256-token margin, input budget is
58,360 tokens. Other profiles keep their prior output settings.

The installed vLLM 0.31.0 supports the separate budget, verified with a small
live probe. See [vLLM thinking budget documentation](https://docs.vllm.ai/en/stable/features/reasoning_outputs/#thinking-budget-control).
This is a server-owned sampling option, not a client-controlled parameter or
chat-template instruction. It is enabled only for the verified Qwen preset,
so switching models does not silently apply it to an untested backend.
Values must be nonnegative integers smaller than the output allowance.
If a profile permits a smaller client output limit, its thinking budget is
clamped below that limit. Compaction calls remove it and keep thinking off.
The generation log records the effective budget without logging reasoning.

A hard reasoning cap can affect answer quality. A successful final answer is
not proof of meeting every benchmark requirement. Keep quality evaluation
separate from checking that the stream completes. Longer responses also need
compatible client/proxy timeouts; no automatic retry is performed.


Current reasoning preferences: `local-tools` uses medium; local-assistant,
local-creative, local-research, local-home, local-work, and any optional
deployment-only profiles use low. Thinking remains enabled. These are exact-ID Qwen settings,
not universal reasoning parameters for every model. Low is a template instruction,
not a hard token cap. The separate 4,096-token cap currently applies only to
local-tools. Other profiles retain their 8,192-token combined output allowance.


Validation: the supplied six-section RAG prompt completed through the deployed
local-tools streaming endpoint in 128.1 seconds, with 1,518 prompt tokens,
8,310 completion tokens (3,914 reasoning), visible output containing all six
section headings, no stream errors, and finish_reason stop. This was a fresh
harness request; Onyx's additional context was not included. Full benchmark
quality/rubric compliance was not evaluated. Regression suite: 204 passed,
27 skipped for optional integration requirements.


### Ratio-based reasoning cap (2026-10-15)

An exact-ID preset can set `thinking_budget_ratio` instead of a fixed
`thinking_token_budget`. The cap becomes that fraction of each call's actual output
allowance, so it shrinks when a client lowers `max_tokens` and is recomputed for every
round of a harness tool loop. At least one token always remains for the visible answer.
The ratio must be between 0 and 1, and a profile or preset may not set both a ratio and
a fixed budget. It is sent as vLLM's `thinking_token_budget`. Like the fixed budget, it is
only configured on the verified Qwen preset.

`local-home` and `local-work` use a ratio of 0.25 with a 16,384-token output allowance and
a 600-second deadline: 4,096 reasoning tokens, matching `local-tools`' fixed 4,096 of 16,384.
A first try at 0.5 of 8,192 cut off a long answer (`finish_reason: length`): the 4,096
reasoning cap held, but the answer itself needed more than the remaining 4,096 tokens.
Generation logs record the effective budget for each call. Profiles without a ratio or
budget are unchanged.


### MCP round cap and cut-off retry (2026-10-23)

Each harness MCP tool-loop round that may still call tools is capped at
`mcp_round_output_tokens` (default 8,192, reasoning included), so a single round cannot
spend the whole request budget. A long answer written in such a round could exceed the cap
and fail with "Research round hit its output limit". Raise the cap on a profile that writes
long answers, keeping room under `max_output_tokens` for a retry; for example 12,288 with a
20,480 output allowance.

When a tool-capable round is cut off (`finish_reason: length`), the harness discards it and
retries once with tools off and the remaining request allowance, asking for the complete
final answer from the evidence already returned. On that retry the reasoning cap is at most
a quarter of the allowance. The reasoning trace notes the retry and the log records a
`research_round_retry` event. A cut-off retry, or a cut-off round that already had tools off,
still fails as before. When streaming, text from the discarded round has already reached the
client, so the complete answer follows it.

## Repository-managed skills

The school profiles now compose reusable writing workflows from trusted Markdown
files. See [SKILLS.md](SKILLS.md) for defaults, explicit `/skill` selection,
capability boundaries, and deployment. Pasting a draft still returns only the
corrected draft.

## Hosted vault tools

`local-tools` supports harness-owned read-only Local_AI_Vault MCP when no client
tools are attached. See [MCP_VAULT.md](MCP_VAULT.md) for policy, UI behavior, limits,
and the separate client-tool execution mode.

## Python sandbox

`local-tools`, `local-home` and `local-work` can run Python through a sandboxed MCP server
on the Hermes VM. Each run is a fresh container with no network, and nothing persists
between runs. In `/chat/` it is the **Python sandbox** chip. It is on by default for
local-tools and off for home and work. The design is in
[docs/ADR-003-code-sandbox.md](docs/ADR-003-code-sandbox.md); setup, escape tests and
operations are in [sandbox/README.md](sandbox/README.md). It needs `HARNESS_CODE_MCP_URL` and
`HARNESS_CODE_MCP_TOKEN` in `.env` on any harness whose profiles list `code`.

When the sandbox is selected, its rules require Python for derived numbers the answer
depends on (totals, projections, threshold crossings), computed in one labeled script,
and forbid runs for numbers given in the request or a source. For a length limit, the
model drafts once, counts exactly the limited text with one run and adjusts once, instead
of redrafting in its reasoning.

## Web search

`local-tools`, `local-home` and `local-work` can search the web with Brave and read pages,
through a second server on the Hermes VM. The model is told to prefer `web_context`, which
uses Brave's LLM Context API to return only the query-relevant passages of the top pages
(2,048 tokens by default), over `web_search` plus a full 16,000-character `web_read`. In `/chat/` it is the **Web search** chip. It
starts off in every profile because searches use prepaid credits. The Brave key stays on
Hermes. Page fetches refuse private and LAN addresses, including after redirects. Setup and
guards are in [sandbox/README.md](sandbox/README.md#web-search-server-hermes-vm). For
troubleshooting questions the rules send the model to the product's own documentation and
setting names first, and to another source when a page does not match the symptom. It needs
`HARNESS_WEB_MCP_URL` and `HARNESS_WEB_MCP_TOKEN` in `.env`.

## Knowledge base search

The **Knowledge base** chip gives the model `rag_search`, which queries the ParadeDB RAG
gateway on the RAG gateway host (`POST /v1/search`). The gateway runs the same hybrid search, dedup,
rerank and abstention floor as a RAG chat turn, but returns passages with their title and
page or section locator instead of an answer. The harness model then writes the answer
and applies them to the conversation, alongside the vault, sandbox and web tools. The
gateway's own chat stays verbatim; here the knowledge base is a trusted source to reason
from. The rules ask for honest attribution: before saying a named document says something,
the model searches for it (or presents the point as its own knowledge), and anything
presented as the source's position or quoted must come from a returned passage, while the model's own analysis reads as its own.
It cites the passages it relies on and quotes only where wording matters. When the
gateway's floor calls a match weak, the model says so briefly and answers normally.

It is on by default in `local-tools` and available in `local-home` and `local-work`. It
needs `HARNESS_RAG_URL` (the gateway base URL, `http://<RAG gateway host>:8100`) and
`HARNESS_RAG_TOKEN`, which must match `SEARCH_TOKEN` in the gateway's `.env`. The search
endpoint stays off until that token is set. Results are capped at 10 passages of 4,000
characters each. Add `rag` to a profile's `mcp_servers` in `profiles.local.yaml` to enable it.

## Reasoning during tool use

When harness tools run on a stream request, every round streams from vLLM. Reasoning
tokens and a one-line summary of every tool call (for example `→ vault_search(Proxmox)`
then `✓ 3 results`) arrive as `reasoning_content`, and the final answer arrives token by
token as `content`, followed by the activity line. `/chat/` shows the newest reasoning
line in the bubble until the answer starts, with the full trace under Reasoning. BoltAI
and Open WebUI show it as reasoning too. Call summaries show only the target (a query,
path, URL or a script's first line), never note bodies, scripts or page text.

Answer text is held until it passes 200 characters, a tool call appears or the round
ends, so a short "let me check" preamble before a tool call is never shown as the
answer. The harness still requires vLLM's final usage chunk to enforce the output
budget. Non-stream responses use non-stream rounds and carry the trace in
`message.reasoning_content`.
