# Running the harness for a team

This guide covers running the harness for a small team that uses one profile, such as the
`it-troubleshoot` profile at a help desk. It explains what each piece does before showing the
commands, so someone new to self-hosting can follow it. Addresses here are placeholders.
Keep your real addresses and host names in a private site document, never in this repository.

The README covers the harness itself. [IDENTITY.md](../IDENTITY.md) has the full detail on
sign-in, and [ADR-008](ADR-008-team-knowledge-base.md) covers the knowledge base design.

## The pieces and how they connect

```text
 people's browsers
        │ HTTPS
        ▼
 reverse proxy ───────────────► identity provider (sign-in with passkeys)
        │
        ▼
 harness :8200  ── team knowledge base (inside the harness's SQLite file)
        │  ├────► web search server :8203 (optional)
        │  └────► Docling Serve :5001 (optional, converts attached documents)
        ▼
 inference server(s) /v1  (vLLM on a GPU machine)
```

| Piece | What it does | Required? |
|---|---|---|
| **Harness** | Receives every chat, applies the profile's prompt, rules, tools and limits, then calls the model. It holds chat history and the team knowledge base in one SQLite file. | Yes |
| **Inference server** | Loads the model onto a GPU and generates text. The harness talks to it through an OpenAI-compatible API (`/v1`). It knows nothing about users or profiles. | Yes |
| **Identity provider** | Proves who someone is. People sign in with a passkey; the provider tells the harness their name and groups. The harness turns groups into permissions. | Yes, for a team |
| **Reverse proxy** | One front door with a real HTTPS certificate. It forwards each site name to the right service, so people never type ports. | Recommended |
| **Web search server** | Lets the model search the web and read pages. It uses paid search credits, so chats start with it off. | Optional |
| **Docling Serve** | Turns attached PDF, Word, PowerPoint and Excel files into text the model can read. Markdown and plain text work without it. | Optional |

**Why sign-in matters for a team.** Without it, everyone shares one access key, so the harness
can't tell people apart: everyone sees the same chats, and nobody can be given editor rights.
With sign-in, each person has their own chats, and the harness checks their group before every
profile and tool use. Those checks happen in the harness code, not in the prompt, so a model
can't talk its way past them.

## Setup

These steps assume the harness host already runs Docker and has a checkout of this repository.
Settings live in untracked files, so `git pull` never overwrites them:

| File | Holds |
|---|---|
| `.env` | Keys, the inference server URL, tool server URLs |
| `identity-config/identity.yaml` | Sign-in settings and who may use what |
| `profiles.local.yaml` | Your profile set, mounted over the tracked `profiles.yaml` |
| `docker-compose.override.yml` | Mounts the two files above into the container |

### 1. Point the harness at the model

In `.env`, set `GEN_URL` to the inference server, including `/v1`, for example
`http://<inference host>:8000/v1`. Use an address the harness *container* can reach, not
`localhost`, which inside a container means the container itself.

Generate the access key with the command at the top of `.env.example` and set
`HARNESS_API_KEY`. Even with sign-in, apps that can't sign in (n8n, for example) use this key.

### 2. Turn on sign-in

Follow [IDENTITY.md, "Setting it up"](../IDENTITY.md#setting-it-up). For a team, create two
groups in the identity provider instead of the household ones:

- one for everyone who may use the profile (`harness_it` below), and
- one for the people who may write and publish knowledge base articles (`harness_it_editors`).

Then give each group its grants in `identity-config/identity.yaml`:

```yaml
role_grants:
  harness_it:
    profiles: [it-troubleshoot]
    tools: [kb_search, kb_read]
    collections: [team_kb]
  harness_it_editors:
    profiles: [it-troubleshoot]
    tools: [kb_search, kb_read]
    collections: [team_kb]
    kb_editor: true
```

Grants from several groups add up, so an editor can be in both. A person in neither group can
sign in but sees "no access". Add `web_search` and `web_read` to `tools`, and `web` to
`collections`, only if you run the web search server.

**Later, a company sign-in.** To use the company's identity provider (for example Microsoft
Entra ID) instead, change `issuer`, `client_id` and `roles_claim` in the same file. The grants
stay the same.

### 3. Set up the profile

In `profiles.local.yaml`, copy the `it-troubleshoot` profile from `profiles.yaml` and set its
tools to the ones you actually run. The template lists the RAG knowledge base and the vault,
which a team deployment usually doesn't have:

```yaml
    mcp_servers: [kb]          # add web if you run the web search server
    mcp_default: [kb]          # tools that are on when a chat starts
```

A profile that names a tool server without a URL stops the harness at startup, so list only
what exists. Check the file before restarting:

```bash
docker compose exec -T local-model-harness python scripts/check_config.py && docker compose restart
```

### 4. Optional services

- **Web search:** set `HARNESS_WEB_MCP_URL` and `HARNESS_WEB_MCP_TOKEN` in `.env`, and keep
  `HARNESS_WEB_POLICY=strict`. See [sandbox/README.md](../sandbox/README.md) for running the
  server, and [ADR-005](ADR-005-web-read-seen-urls.md) for what `strict` blocks.
- **Document attachments:** set `HARNESS_DOCLING_URL` (and `HARNESS_DOCLING_API_KEY` if Docling
  needs one). Without it, only Markdown and text files can be attached.
- **Time zone:** set `HARNESS_TIMEZONE` (for example `America/Chicago`) so the model gets the
  right date.

After any `.env` change, recreate the container: `docker compose up -d --force-recreate`.

## The team knowledge base

The knowledge base holds your team's own short articles: runbooks, known fixes, vendor quirks.
When the `it-troubleshoot` profile has it on, the model searches it before its first reply and
prefers what it finds over general knowledge.

**How search works.** It's keyword search (SQLite FTS5, ranked by BM25), not "AI search". An
article is found when it shares words with the question. Word forms match ("renaming" finds
"rename"), and exact error text matches very well. A question worded completely differently
from the article won't find it. So:

- put the exact error messages and symptom words people type into the article,
- use one `##` section per task, with the symptom in the heading, because results come back
  by section, and
- keep articles short; a few hundred of them is the intended size.

**Writing and publishing.** Editors open **Settings > Knowledge base** in `/chat/`. A new
article starts as a draft, which the model never sees. Publishing makes it searchable at once.
Every save records who made it and keeps the previous version. If two editors change the same
article, the second save is refused instead of silently overwriting the first.

Everyone with access can read published articles and try a search on that page.

## Operating it

### Back up

Chat history **and every knowledge base article** live in one SQLite file inside a Docker
volume. Losing that volume loses both. Back it up nightly with the included script and timer:

```bash
cp deploy/systemd/harness-chat-backup.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now harness-chat-backup.timer
systemctl start harness-chat-backup.service     # run one now
ls /var/backups/local-ai-harness/chat-history/  # a new chat-history-*.sqlite3 file
```

The service file assumes the checkout is at `/root/local-ai-harness`; edit its paths if yours
differs, and the timer's time zone to yours. Each backup is checked for integrity, and the
last 30 are kept. These copies are on the same machine, so also copy them somewhere else.

Also keep a copy of the settings files listed under Setup; they aren't in git.

### Update

```bash
cd <harness folder>
git status --short       # should list nothing; tracked edits would be overwritten
systemctl start harness-chat-backup.service
docker tag local-ai-harness-local-model-harness:latest local-ai-harness-local-model-harness:previous
git pull --ff-only
HARNESS_VERSION=$(git rev-parse --short HEAD) docker compose up -d --build
docker compose ps && curl -fsS http://127.0.0.1:8200/health/live
```

The `docker tag` line keeps the running image under the name `previous`, so you can go back
without rebuilding. `HARNESS_VERSION` puts the commit into the run line at the end of answers,
so you can always tell which version produced an answer.

### Roll back

```bash
git checkout <last good commit>
docker tag local-ai-harness-local-model-harness:previous local-ai-harness-local-model-harness:latest
docker compose up -d --no-build --force-recreate local-model-harness
```

Never run `docker compose down -v`: `-v` deletes the volume that holds chat history and the
knowledge base. Docker Compose also names volumes after the folder, so don't move or re-clone
the checkout into a new folder; the new folder would start with empty volumes.

### When sign-in fails

The sign-in page explains each failure code. The common ones:

| Message | Usual cause |
|---|---|
| no access | The person isn't in a group listed under `role_grants`, or the group's *Name* doesn't match exactly (the identity provider may turn hyphens into underscores). Group changes apply at the next sign-in. |
| provider unavailable | The harness container can't reach the identity provider by its HTTPS name. Test from inside the container (IDENTITY.md, step 5). |
| expired | The sign-in page sat open more than ten minutes. Try again. |

## What's built and what's planned

| Feature | Status |
|---|---|
| Sign-in with passkeys, per-person chats and grants | Built |
| Team knowledge base, edited in Settings | Built. Articles are added by hand or written during sessions |
| Web search | Built, optional |
| Importing approved articles from a documentation system | Planned, not built |
| Company identity provider | Planned; a settings change only |
| Case notes for long-running vendor issues | Planned, not built |
