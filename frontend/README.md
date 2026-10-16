# Harness chat client

A small React client served by the harness at `/chat/`. Its layout comes from the earlier ai-frontend Electron app (top banner, sidebar with recent chats, chat bubbles with avatars, Settings modal), rebranded as Local Model Harness with a text logo placeholder (`src/components/Brand.jsx`). The original project is unchanged. Its RAG server, Electron integration, logos, feedback link, and document upload are not included.

Code layout: `src/App.jsx` owns sign-in state, conversations and streaming; `src/components/` holds `Login`, `Sidebar`, `ChatArea`, `MessageBubble`, `ChatInput`, `SettingsModal` and `Brand`, each with a stylesheet in `src/styles/`. Colour tokens live in `src/base.css`; inline style attributes are avoided because the shell's CSP is `style-src 'self'`.

## Use

Build/rebuild the harness Docker image, then open `http://<harness-host>:8200/chat/`. Enter an existing harness API key or access token. Use HTTPS through your trusted reverse proxy when sending credentials over a network.

Choose an authorized profile and optionally a workflow. Workflow and tool choices stick to the chat, and each one is saved with the chat. The workflow picker shows each skill's title and first sentence, and the chosen workflow is sent as `/skill <id>` on every turn. Automatic leaves selection to the harness. On profiles with harness MCP servers, a Tools row turns each server on or off for the chat. The choice is sent as `X-Harness-MCP`; new chats start from the profile's `mcp_default`. See [MCP_VAULT.md](../MCP_VAULT.md). Profiles lock after the first message; start a new chat to switch. The server remains responsible for permissions, prompts, memory, generation settings, and compaction.

The Settings modal shows the authenticated identity and the profiles, workflows and harness tools it may use; it is read-only. The client displays streamed answers, collapsible reasoning, Markdown tables/code, token usage, and compaction notices. Stop cancels the request; Copy copies a message. Clipboard access requires a browser secure context and may be unavailable over plain LAN HTTP.

Signing in exchanges the key once for a browser session (`POST /v1/session`). The harness returns an opaque `harness_session` cookie that is HttpOnly, `SameSite=Strict`, and `Secure` when served over HTTPS. Page scripts cannot read it, and the key is not kept in page memory or browser storage. A reload restores the session, and conversations are saved on the harness. Cookie-authenticated requests must also send `X-Harness-Client: chat`. A cross-origin page cannot add that header without a CORS preflight, which the harness never grants.

Sessions end after `HARNESS_SESSION_IDLE_MINUTES` without activity (default 720, so 12 hours). They also end at `HARNESS_SESSION_MAX_HOURS` after sign-in (default 168, so 7 days), however active they are. A JWT session never outlives its token. Disconnect ends the session on the server. Sessions are held in process memory, at most 256: restarting or redeploying the harness signs everyone out, and a rotated API key cannot outlive the old process. Any request that returns 401 sends the page back to sign-in with an expiry notice. Bearer credentials still work unchanged for other clients and always take precedence over the cookie. A shared service key still grants its existing shared permissions; selecting a profile does not create user isolation.

This first version supplies no web search, Python executor, attachments, or client tool definitions. Existing server-owned capabilities still follow profile policy. Reasoning is displayed but not replayed as conversation content. Failed or stopped assistant output is excluded from follow-up history. No UI system prompt, automatic title request, or second compaction layer is injected.

## Development

Use Node 22.12 or newer, from the repository root:

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

Start the Python harness after building to serve `/chat/`. Without `frontend/dist/index.html`, the static route is not mounted, so backend-only development remains supported. Docker builds the frontend in a separate Node stage; its runtime remains Python.

For the Vite development server:

```bash
HARNESS_DEV_TARGET=http://127.0.0.1:8200 npm --prefix frontend run dev
```

The `/v1` development proxy targets that backend. The production client uses same-origin URLs. GET `/v1/profiles` requires authentication (bearer or chat session) and returns only authorized profile IDs, enabled skill IDs, and the default skill, not prompts or credentials.

## Validation

Node tests cover history replay (only complete answers, workflow directive), the tool-selection header, saved per-chat choices, fragmented UTF-8/SSE, reasoning and usage events, server errors, missing DONE, malformed frames, authentication, and request forwarding. Python tests cover profile authorization and static-shell headers. Browser smoke testing uses a synthetic backend to verify connection, workflow selection, rendered output, usage, and disconnect. It does not establish live model quality or deployment health.

## Persistent history

The supplied Compose file enables `HARNESS_CHAT_DB=/app/chat-data/conversations.sqlite3` and mounts the named `chat-history` volume. Native development must set `HARNESS_CHAT_DB` to a writable SQLite path. Without this setting the history API returns 503, and the chat UI cannot connect; existing model APIs continue working.

History is separate from ParadeDB saved memories: it is not indexed, automatically recalled, or automatically extracted into facts. Only opening a conversation supplies its prior turns. Records are keyed by authenticated identity kind and actor ID, and checked against profile permissions on every operation. The shared lab key shares all its authorized conversations; profile names are not personal logins.

The UI saves a user turn before requesting generation, then saves the completed, stopped, or failed answer. Only complete assistant turns are replayed. Reasoning and token counters are shown during the current session but are not retained in the transcript. If a tab closes during generation, the user turn survives; interrupted output may not. Save failures are visible with Retry save. Concurrent updates/deletes require the latest revision, so stale tabs cannot overwrite saved changes silently.

Chats remain until explicitly deleted. Delete chat requires a browser confirmation and permanently removes the active record; backups may retain older copies. Limits: 2 MB per save, 4,096 messages per chat, 500,000 characters per message, and 1,000 conversations per identity. These are storage bounds, not model context allowances. Existing profile context/compaction policies still apply.

Authenticated API: GET `/v1/conversations?offset=0` returns summaries in pages of 100; GET `/v1/conversations/{uuid}` restores a transcript; PUT stores it using revision 0 for creation or the current revision for updates; DELETE requires `?revision=<current>`. Model APIs do not automatically write transcripts. UI chats from other applications are not imported.

### Backup and recovery

The database survives container rebuilds/recreation. Do not run `docker compose down -v`, which removes the named volume. Include it in backup planning separately from ParadeDB. From the harness deployment directory, take an online SQLite-consistent backup:

```bash
docker compose exec -T local-model-harness python -c "import sqlite3; s=sqlite3.connect('/app/chat-data/conversations.sqlite3'); d=sqlite3.connect('/tmp/chat-history-backup.sqlite3'); s.backup(d); d.close(); s.close()"
docker compose cp local-model-harness:/tmp/chat-history-backup.sqlite3 ./chat-history-backup.sqlite3
chmod 600 chat-history-backup.sqlite3
```

Move the backup to private backed-up storage, outside Git and Docker build context. For restore, stop the service, restore the SQLite backup to the volume with ownership 10001:10001, remove stale WAL/SHM sidecars only while stopped, and start the service. Keep a copy of the original database before restoring. The optional systemd backup schedule below is deployed on the harness host.

### Scheduled backups (the harness host)

`harness-chat-backup.timer` runs nightly at 02:30 America/Chicago and catches up
missed runs after downtime (`Persistent=true`). The service uses the Python standard
library SQLite online backup API while the app remains running. It verifies
`integrity_check` and the conversation table, publishes the completed database
atomically, and writes a SHA-256 manifest. Only after success does it retain the
latest 30 snapshots, including manually triggered ones. A lock prevents overlap;
a failure exits nonzero and leaves previous snapshots intact.

Destination: `/var/backups/local-ai-harness/chat-history` on the container filesystem,
with directory mode 0700 and snapshots/manifests mode 0600. This is outside the chat
Docker volume but remains on the harness host. It is not an off-container or disaster-recovery
copy. Include this directory in the Proxmox/NAS backup plan. Deleted chats can remain
in retained snapshots until their retention expires. There are no external failure
notifications configured; inspect the unit status/journal.

The deployment-specific units are in `deploy/systemd/`. They assume the checkout is
`/opt/local-model-harness` and the Docker volume path is
`/var/lib/docker/volumes/local-ai-harness_chat-history/_data`; verify/adapt these
paths before installing elsewhere. Schedule changes need `systemctl daemon-reload`
and a timer restart.

```bash
systemctl list-timers harness-chat-backup.timer
systemctl start harness-chat-backup.service
systemctl show harness-chat-backup.service -p Result -p ExecMainStatus
journalctl -u harness-chat-backup.service -n 20 --no-pager
```

To disable scheduling without deleting backups:
`systemctl disable --now harness-chat-backup.timer`.
Validation on 2026-10-13: WAL snapshot/content-restore and retention tests passed;
failure test preserved older backups. The first live snapshot's hash and isolated
restore passed (zero conversations existed at that time). No live database restore
or service restart was performed.
