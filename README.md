# Local Model Harness

A self-hosted FastAPI gateway that sits between chat clients and a local
OpenAI-compatible inference server (vLLM by default). Clients pick a named
**profile**; the harness owns everything about that profile: system prompt, rules,
sampling and reasoning settings, context budget, tools, memory and permissions. The
inference server only loads the model and runs it.

```text
/chat/ (built-in client) ─┐
Open WebUI / BoltAI ──────┼─► harness :8200/v1 ─► vLLM /v1
other OpenAI clients ─────┘        │
                                   ├─► MCP tools: vault · Python sandbox · web search · knowledge base
                                   ├─► ParadeDB (saved memories, optional)
                                   ├─► Docling Serve (document attachments, optional)
                                   └─► identity provider (OIDC sign-in, optional)
```

Profiles follow whichever single model vLLM is serving (`backend_model: auto`).
Exact-ID **presets** in `profiles.yaml` apply tested settings for a known model
(currently `qwen3.8-27b`); any other model inherits the backend's defaults.

## Profiles

| Profile | Purpose | Harness tools | Memory |
|---|---|---|---|
| `local-assistant` | General chat | none | recall + explicit saves |
| `local-creative` | Writing; looser sampling, 600 s deadline | none | recall + explicit saves |
| `local-research` | Demo of the harness tool loop over the bundled synthetic `demo_notes/` | `search_notes`, `read_note` | recall |
| `local-tools` | Main tool-using profile; also passes client function calls back to the UI | vault, Python, knowledge base on; web search off | `home` scope |
| `local-home` / `local-work` | Same tools, all off until a chat turns them on; separate memory scopes | vault, Python, web, knowledge base | `home` / `work` scope |
| `it-troubleshoot` | Guided IT troubleshooting, one diagnostic step per turn, then a write-up | knowledge base, vault on; web, Python available | none |
| `local-bench` | Fixed settings for benchmark prompts; change only on purpose | all four available, Python on; number check | none |

Deployment-specific profiles (personal assistants, course workflows) go in an
untracked `profiles.local.yaml`, mounted over `profiles.yaml` by
`docker-compose.override.yml`. A minimal profile for a server without vLLM's
`/tokenize` is in `profiles.portable.yaml` (public snapshot).

## What it does

- **Built-in chat client** at `/chat/`: streaming Markdown, collapsible reasoning
  (including a live trace of each tool call), token usage, saved conversations,
  projects with default profile/workflow/tools, per-chat tool chips, your own
  Markdown skills, and document attachments. See [frontend/README.md](frontend/README.md).
- **Harness-run tools** over MCP, chosen per chat with the `X-Harness-MCP` header:
  - **Vault** – read-only search and reading of an Obsidian vault ([MCP_VAULT.md](MCP_VAULT.md)).
  - **Python sandbox** – each run is a fresh, networkless container; answers that
    depend on derived numbers must compute them, and the number check flags figures no
    run printed ([docs/ADR-003-code-sandbox.md](docs/ADR-003-code-sandbox.md),
    [sandbox/README.md](sandbox/README.md)).
  - **Web search** – Brave search, LLM-context passages and page reads; private and LAN
    addresses are refused. Off by default because it spends paid credits.
  - **Knowledge base** – `rag_search` against the
    [Homelab RAG](https://github.com/punisher1-1/homelab-rag) gateway's `/v1/search`,
    returning cited passages rather than an answer.
- **Client tools** – `local-tools` accepts OpenAI function schemas from BoltAI or Open
  WebUI and returns tool calls for the client to execute ([TOOLS_AND_MODELS.md](TOOLS_AND_MODELS.md)).
- **Skills / workflows** – trusted repository Markdown in `skills/`, selected per
  profile or with `/skill <id>`; users can add their own, and share them with an
  identity group ([SKILLS.md](SKILLS.md)).
- **Persistent memory** – scoped ParadeDB storage with bounded read-only recall and
  explicit saves (`Remember: fact: …`); nothing is captured automatically. Manage
  memories at `/memory` or in `/chat/` ([MEMORY.md](MEMORY.md), [ADR-002](docs/ADR-002-persistent-memory.md)).
- **Document attachments** – Markdown and text natively; PDF, Word, PowerPoint, Excel
  and HTML through Docling Serve.
- **Context compaction** – near the limit, older turns are summarized for that request
  only and a notice is shown ([COMPACTION.md](COMPACTION.md)).
- **Identity** – shared service key by default; JWT mode; or OIDC mode with passkey
  sign-in (e.g. Pocket ID) that gives each person their own chats, projects, skills and
  grants ([IDENTITY.md](IDENTITY.md), [ADR-004](docs/ADR-004-oidc-sign-in.md)).
- **Traceability** – tool answers end with a run line naming the model, profile and
  harness commit; logs record metadata only, never prompt or response text
  ([TELEMETRY.md](TELEMETRY.md)).

## Quick start

Requires Docker (or Python 3.12+ for a native run).

1. `cp .env.example .env`, then set:
   - `HARNESS_API_KEY` – generate with the command in the file.
   - `GEN_URL` – your inference server, including `/v1`; `GEN_API_KEY` if it needs one.
   - The `HARNESS_*_MCP_URL` / `_TOKEN`, `HARNESS_RAG_*` and `HARNESS_DOCLING_*` values
     only for the services you run. A profile that lists a tool server needs its URL.
2. Review `profiles.yaml`. `backend_model: auto` needs exactly one model in vLLM's
   `GET /v1/models`; pin an ID if several are served. For a non-vLLM server, use
   `token_count_mode: utf8_estimate` (a heuristic, not an exact bound) or start from
   `profiles.portable.yaml`.
3. Start it:

```bash
HARNESS_VERSION=$(git rev-parse --short HEAD) docker compose up -d --build
```

Add saved memory with
`docker compose -f docker-compose.yml -f docker-compose.memory.yml up -d --build`
and a `memory-config/memory.yaml` (see [examples/memory.yaml](examples/memory.yaml)).

Native alternative:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --env-file .env --host 0.0.0.0 --port 8200 --no-access-log
```

Startup fails on a missing or placeholder key, an invalid profile, or a missing
prompt, skill or tool server. Check edits before restarting:

```bash
docker compose exec -T local-model-harness python scripts/check_config.py && docker compose restart
```

Profile/prompt edits need a restart, `.env` edits `docker compose up -d --force-recreate`,
code edits a rebuild. Deploying from git, backups and rollback are in
[deploy/README.md](deploy/README.md).

### Smoke check

```bash
curl -fsS http://localhost:8200/health/live
curl -fsS http://localhost:8200/health/ready -H "Authorization: Bearer $HARNESS_API_KEY"
curl -fsS http://localhost:8200/v1/models -H "Authorization: Bearer $HARNESS_API_KEY"
curl -N http://localhost:8200/v1/chat/completions \
  -H "Authorization: Bearer $HARNESS_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"local-assistant","messages":[{"role":"user","content":"Explain a reverse proxy in three sentences."}],"stream":true}'
```

Then open `http://<harness-host>:8200/chat/`.

## Connecting other clients

Add an OpenAI-compatible connection with base URL `http://<harness-host>:8200/v1` and
the harness key (or a scoped service key in OIDC mode). Use an address reachable from
the client's container, not its `localhost`.

- Pick harness profiles, not the raw backend model, or harness policy will not apply.
- In Open WebUI, turn off Built-in Tools for profiles other than `local-tools`; those
  profiles reject tool definitions. Client system prompts are discarded by default.
- BoltAI's replayed `reasoning_content` is accepted and dropped. For attachment and
  oversized-page issues see [BOLTAI_TROUBLESHOOTING.md](BOLTAI_TROUBLESHOOTING.md).

## Configuration

Each profile in `profiles.yaml` controls:

| Area | Keys |
|---|---|
| Prompt and policy | `system_prompt_file`, `rules`, `client_system_prompt`, `skills`, `default_skill` |
| Model and sampling | `backend_model`, `backend_presets`, `temperature`, `top_p`, `presence_penalty`, `seed`, `stop`, `backend_options` |
| Reasoning | `chat_template_kwargs` (effort), `thinking_token_budget` or `thinking_budget_ratio` |
| Budget | `max_output_tokens`, `context_window`, `context_margin`, `token_count_mode`, `overflow`, `request_timeout_seconds`, `mcp_round_output_tokens` |
| Tools | `mcp_servers`, `mcp_default`, `client_tools`, `verify_numbers`, `research` |
| Memory and history | `memory_recall`, `chat_memory`, `compaction` |
| Client overrides | `allow_client_params` (empty by default; output limits are always capped) |

Global limits: `max_concurrent_requests`, `max_request_bytes`, `request_timeout_seconds`.

Admission requires *prompt tokens + reserved output + margin ≤ context window*.
In `vllm` mode the prompt is counted with the backend's own `/tokenize` and fails
closed if that is unavailable. The harness window never enlarges the server's: vLLM's
launch flags (or Ollama's `num_ctx`) set the real capacity.

## Security boundary

This is a tested template for a trusted network, not a finished enterprise platform.

- Only the configured backend and tool URLs are contacted; redirects and proxy
  discovery are off. Enforce "local only" with firewall/egress rules too.
- Put TLS and rate limiting at a reverse proxy, with response buffering off for
  streaming. The container listens on all interfaces at port 8200.
- Prompt rules guide the model; they do not enforce authorization or stop prompt
  injection. Permissions are enforced by the harness per profile and identity.
- The shared service key gives every holder the same identity. Use OIDC or JWT mode for
  per-person separation.
- One worker per configured concurrency budget; excess requests get 429. There are no
  automatic generation retries apart from one tools-off retry of a cut-off tool round.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
npm --prefix frontend ci && npm --prefix frontend test
```

Tests use a mocked backend, so no GPU, network or keys are needed; integration tests
skip when their services are absent. Benchmark prompts and recorded runs are in
[benchmarks/](benchmarks/).

## Further reading

| Topic | Document |
|---|---|
| Tool loop and demo research profile | [RESEARCH.md](RESEARCH.md) |
| Client tools and model selection | [TOOLS_AND_MODELS.md](TOOLS_AND_MODELS.md) |
| Vault MCP and per-chat server choice | [MCP_VAULT.md](MCP_VAULT.md) |
| Sandbox and web servers | [sandbox/README.md](sandbox/README.md) |
| Memory | [MEMORY.md](MEMORY.md) |
| Skills | [SKILLS.md](SKILLS.md) |
| Compaction | [COMPACTION.md](COMPACTION.md) |
| Identity and sign-in | [IDENTITY.md](IDENTITY.md) |
| Usage, KV cache and metrics | [TELEMETRY.md](TELEMETRY.md) |
| Role-scoped agents (design only) | [ROLE_AGENTS.md](ROLE_AGENTS.md) |
| Design decisions | [docs/](docs/) |
