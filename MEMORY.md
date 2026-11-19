# Persistent memory on ParadeDB

**Status, 2026-09-25:** Scoped storage, recall, browser management, and explicit
chat save commands are available. Ordinary conversation and compaction never
capture memories automatically. Existing records remain until explicitly deleted.

## Save directly from chat

On `local-home`, `local-work`, `local-tools`, `local-assistant`, or `local-creative`,
send one of these as the entire newest user message:

```text
Remember: fact: My home lab GPU is an RTX 4090.
Remember that I prefer concise troubleshooting steps.
/remember preference: Include commands with explanations.
```

The harness saves the exact supplied text after the command/category prefix and
returns a database receipt with scope and memory ID. This is a server-handled
chat action, not an LLM function exposed to Onyx. It requires no UI tool wiring,
no vLLM generation, and no additional model inference. A failed database write
returns an error, never a model-written success claim. Real inference usage is
zero for the acknowledgement. `local-research` remains read-only through chat.

Use `local-home` for home memory and `local-work` for work memory. The other
listed profiles save in legacy. A scope header or text mentioning another lab
does not override the profile. Category is optional (`note` by default); supported
categories are `note`, `fact`, and `preference`. Text is limited to 8,192 UTF-8 bytes.
Only these anchored command forms are accepted (case-insensitive; `please` is
optional before Remember). Quoted commands, tool results, old user messages, and
ordinary chat do not trigger a save. An ambiguous request such as “remember this”
needs exact text; the harness does not extract a guessed memory from chat history.

The same normalized category/text produces the same idempotency key within its
owner/scope, including after network retries. Repeating it returns “Already saved.”
A different category or text is a different memory. Deleting the record permits
saving it again later. There is no automatic edit, replacement, or deletion.

Review saved entries at `/memory` with the matching scope, then test recall in a
fresh chat using the same profile. A save confirms persistence, not guaranteed
retrieval for every question: recall remains bounded and relevance-dependent.
The browser, API, and CLI continue to support explicit management.

[COMPACTION.md](COMPACTION.md) describes a separate feature: temporarily summarizing
older history so the current request fits. It adds no persistent memory writes.

## How recall works

Each enabled profile has trusted configuration:

```yaml
memory_recall:
  enabled: true
  max_memories: 4
  max_context_bytes: 4096
```

The policy model defaults to disabled; the three bundled lab profiles explicitly
enable it. Disable it for profiles that should not read personal memory.

1. Verify profile access, then check `memory.read`. The existing approved shared key
   has access. A verified JWT without that grant gets ordinary chat with no lookup
   and a `not_authorized` diagnostic; selecting a profile cannot grant memory rights.
2. Extract up to 24 distinct lexical terms from the first 4,096 characters of the
   latest user message, ignoring common English filler and terms shorter than three
   characters. Match any term against active memories within the caller's scope.
   Preferences are eligible even without a lexical match. Rank matches first, then
   newest entries; select at most four candidates. Unrelated notes/facts are excluded.
3. Pack whole records into a JSON block of at most 4,096 bytes including its labels.
   Oversized records are skipped, not truncated. The bound includes JSON escaping;
   Unicode-heavy records may need more serialized space. An oversized candidate is
   not replaced by a second query for lower-ranked records.
4. Put the block in the latest **user message**, before its original text, keeping
   memory text out of the system role. Fixed system rules identify it as untrusted
   saved context, subordinate to current instructions and policy. Those rules and
   recall settings participate in the profile fingerprint. Research must not treat
   saved assertions as verified demo-corpus evidence or cite them as demo notes.
5. Count the complete augmented prompt using the existing tokenizer/context policy.
   Recall does not expand the model's context window or bypass output reservations.
   If the complete prompt exceeds the budget, the existing reject/trim policy applies;
   this version does not adaptively shrink memory to remaining context space. Enabled
   conversation compaction can summarize older chat turns before the final budget
   check; the memory block remains in the retained current user message.

This is lexical recall, not semantic understanding. Synonyms, pronouns and facts only
mentioned in older turns may miss. Saved preferences are broadly applicable candidates,
not guaranteed selections. The explicit search endpoint still uses **all** terms;
automatic recall uses **any** selected term. Neither path needs embeddings or reranking.

The model can report saved statements as memory, but prompt rules cannot guarantee
resistance to prompt injection. No write/delete tool or additional research capability
is granted. The model never gets a database password, owner ID or connection string.

Responses expose `X-Harness-Memory-Status` (`disabled`, `not_authorized`, `no_match`,
`budget_excluded`, `recalled`) and `X-Harness-Memory-Count`. Open WebUI may not display
these headers. Memory health reports `automatic_recall` and authorized `recall_profiles`.
Logs record status, selected count and byte size, never memory text or query terms.

A missing configured store or database failure returns an explicit 503 for a profile
using recall. It does not silently generate an answer after an unsuccessful lookup.
Profiles with recall disabled continue independently. Retrieval has its own bounded
memory-operation deadline before the generation deadline; it adds at most that stage's
8-second limit rather than consuming the configured model-generation allowance.

Deletion takes effect on the next retrieval. It cannot erase text already sent in an
in-flight prompt, an earlier answer, or history Open WebUI resends. Test deletion in a
**fresh chat**. The harness does not cache recall results between requests.

## Architecture and ownership

```mermaid
flowchart LR
  U[Explicit user save/list/search/delete] --> A[Harness authentication and memory permissions]
  A --> P[Bounded PostgreSQL connection pool]
  P -->|TLS verify-full| D[ParadeDB: local_ai_memory]
  D --> R[Namespace and owner row policies]
```

- The harness (`<harness host>:8200`) connects to PostgreSQL (`<database host>:5432`).
- The dedicated database is `local_ai_memory`; the deployment namespace is
  `personal_lab`. The RAG corpus remains in `myragdatabase`.
- `harness_memory_owner` is NOLOGIN. The application uses `harness_memory_app`,
  which has no superuser, BYPASSRLS, owner membership, database/schema creation,
  UPDATE or TRUNCATE privileges.
- Every operation derives owner ID from `Principal.actor_id` and namespace from
  trusted configuration. Request bodies cannot supply either. Queries bind values,
  apply explicit scope filters, and set transaction-local scope for row security.
  Commit and rollback clear scope before a pooled connection can be reused.
- The current key identifies **one service, not the owner as a verified person**. Every
  holder of that key can read, save and delete the same memories. The owner explicitly
  approved this. Introduce separate verified identities before adding someone
  else's private memories; do not silently assign existing service memories to a
  newly signed-in user.
- JWT role grants support separate `memory.read`, `memory.write`, `memory.delete`
  permissions. Profile or research-tool permissions alone grant no memory access.
  `/v1/identity` reports effective memory permissions.

RLS is defense against scope/query mistakes and untrusted caller input. The trusted
application sets the SQL context, so a compromised application credential could set
another scope. PostgreSQL administrators can also access the records. This is not
independent database verification of each user's token or an enterprise compliance
certification. A work deployment needs its own identities, namespace and database.

## Try it from the harness host

Enter the container from pve2, then use the CLI inside the running Docker service.
It reads the existing API key from the container environment, so no credential needs
to be pasted into a terminal argument or chat.

```bash
pct enter 270
cd /root/local-ai-harness

docker compose exec -T local-model-harness python scripts/memory_cli.py health

printf '%s' 'I prefer concise explanations with practical examples.' |   docker compose exec -T local-model-harness python scripts/memory_cli.py save --category preference

docker compose exec -T local-model-harness python scripts/memory_cli.py list

printf '%s' 'concise explanations' |   docker compose exec -T local-model-harness python scripts/memory_cli.py search

# Substitute the memory_id returned by save/list; this deletes that exact record.
docker compose exec -T local-model-harness python scripts/memory_cli.py delete MEMORY_UUID
```

The CLI prints the save's idempotency key **before** sending it. If a timeout makes
the result uncertain, retry the same text with `save --idempotency-key UUID`.
An identical retry returns the existing record; changed content with the same key
returns 409. Deleting the row also removes its idempotency record, so do not retry an
old save after deliberately deleting it. A repeated delete returns 404 once absent.

For a local client outside Docker, run `python scripts/memory_cli.py --url
http://<harness host>:8200 ...` with `HARNESS_API_KEY` or `HARNESS_TOKEN` set securely in
its environment. The CLI does not follow redirects or discover proxy settings.
The current lab API URL is HTTP; database TLS does not secure that separate client
connection. Use an authenticated TLS ingress and network restrictions for work.

## API contract

All routes require the configured Bearer credential. Nothing about a memory UUID,
conversation reference or client metadata grants access.

| Operation | Route | Permission | Result |
|---|---|---|---|
| Status | `GET /v1/memories/health` | `memory.read` | Database/policy readiness and scope mode |
| Save | `POST /v1/memories` | `memory.write` | 201 created; 200 identical replay; 409 conflict |
| List | `GET /v1/memories?limit=20&cursor=...` | `memory.read` | Records and optional next cursor |
| Search | `POST /v1/memories/search` | `memory.read` | Ranked, bounded keyword matches |
| Forget | `DELETE /v1/memories/{memory_id}` | `memory.delete` | 204 deleted; 404 absent or inaccessible |

Save body:

```json
{
  "content": "I prefer concise explanations.",
  "category": "preference",
  "source_conversation_id": "optional-client-reference",
  "idempotency_key": "db0664c8-c612-4a01-81c0-c82036b58747"
}
```

Generate a fresh UUID for each intentional save. `category` defaults to `note` and
also accepts `preference` or `fact`; a label does not establish truth. Source
conversation ID is untrusted provenance metadata, never proof of ownership.
Responses contain memory UUID, content, category, source reference, idempotency key,
creation time and expiry. This version saves with `expires_at: null`; callers cannot
set expiry, owner, namespace, creation time or memory UUID.

Search body is `{"query":"concise explanations","limit":10}`. Native PostgreSQL
`simple` full-text search matches **all supplied terms**, without stemming, synonyms,
embeddings, a model call or reranking. Empty search results do not prove something
was never saved; list/paginate to inspect records. Tokens over PostgreSQL's index
length limit may not be searchable. Search returns at most 50 results; list supports
1–100 per page with a creation-time/UUID cursor. Search has no pagination yet.

Content must be nonblank UTF-8 text, at most 8 KiB, with no NUL. JSON bodies are
limited to 16 KiB and reject unknown fields. Records are immutable: correction means
explicitly saving a replacement, then deleting the old record (two operations, not
an atomic edit). Memory payload responses use `Cache-Control: no-store`.

## Configuration and deployment

No memory configuration path means no database pool. Explicit memory operations
return 503, and chat works only on profiles with recall disabled. The bundled lab
profiles now enable recall, so configure storage or disable their `memory_recall`
settings before using the template without ParadeDB.

1. Apply `sql/memory/000_bootstrap.sql` as an administrator against `postgres`, then
   `001_private_memories.sql` against `local_ai_memory`. These are operator-run,
   once-only migrations, never application startup migrations. Bootstrap deliberately
   fails on existing names; inspect partial progress before retrying. Migration 001
   runs transactionally and records schema version 1.
2. Provision native PostgreSQL TLS and a matching host/IP SAN certificate; permit the
   app role only from the harness host, to the memory database, over TLS. Create its
   password separately; do not reuse the existing RAG administrator's credentials.
3. Copy `examples/memory.yaml` to ignored `memory-config/memory.yaml`. Provision its
   `database-password` and public `ca.crt` separately. Relative paths resolve beside
   the configuration. Restrict the directory to root and container group 10001:
   directory 0750, secret/config files 0640, public CA 0644. The Docker user is 10001.
4. Leave `allow_shared_service_identity: false` for verified-subject deployments.
   For a deliberately shared lab, explicitly set it true. JWT roles need separate
   grants regardless of this shared-key setting.
5. Enable the optional mount/environment overlay:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.memory.yml up -d --build
   ```

   The harness host has a deployment-only copy named `docker-compose.override.yml`, so its
   normal `docker compose up -d --build` continues to include memory. This override
   and `memory-config/` are git-ignored; credentials are excluded from image builds.
6. Check memory health, run a synthetic save/search/delete, then test normal chat.
   Changed files/secrets/config require an app restart; changed Compose environment
   or image requires recreation. The app never provisions SQL or rotates credentials.

The adapter hardcodes `sslmode=verify-full` and accepts only the dedicated database
and restricted username. Pool limits are four connections and eight waiting callers;
checkout timeout is three seconds, SQL statement timeout three seconds, idle
transaction timeout five seconds, and overall operation timeout eight seconds.
Every checkout verifies the expected role, ownership, forced RLS and migration version.
Memory failures return a generic 503 without private SQL exception details. They do
not call vLLM. Profiles with recall enabled fail explicitly when retrieval fails;
profiles with recall disabled remain independent. `/health/ready` still checks the generation
backend; use `/v1/memories/health` to check memory separately. Malformed local memory
configuration or unreadable secret files fail startup instead of silently disabling it.

## Live TLS and access rules

Native PostgreSQL TLS is on. The database host's existing RAG authentication rules were preserved;
these memory-specific rules precede them:

```text
local   all             harness_memory_app                       reject
hostssl local_ai_memory harness_memory_app <harness host>/32         scram-sha-256
host    all             harness_memory_app 0.0.0.0/0              reject
host    all             harness_memory_app ::0/0                 reject
```

Server certificate/key are in PostgreSQL's persistent data directory,
`/var/lib/postgresql/18/docker/tls/`, owned by postgres (UID 999); the key is 0600.
The dedicated lab CA signing material is root-only on pve2 under
`/root/harness-memory-pki`; only the public CA is mounted into the harness host.
The server certificate expires **2027-09-07 21:42:21 UTC**. Renewal is manual:
issue a replacement with the same IP SAN using the protected CA, install the pair
with matching ownership/modes, reload PostgreSQL, then verify a new client connection.
CA rotation also requires updating client trust and restarting the harness pool.
Keep an encrypted administrator backup of the CA signing material; the logical
memory dump does not include it. Automatic certificate renewal is not implemented.

## Retention, backup and rollback

Memories remain until explicitly deleted. Delete removes the live row and search
index entry, but **backups may retain it through their retention window**. The schema
has an active-memory view for future expiry support; expired rows are omitted from
search but still visible to their owner for list/delete. This API does not set expiry.

A separate pve2 job, `/usr/local/bin/harness-memory-backup.sh`, runs at 02:25 in the
host's America/Chicago timezone via `/etc/cron.d/harness-memory-backup`. It writes
custom-format dumps to `/mnt/pve/nas-backup/local-ai-memory/`, with approximately
30-day retention. It requires the NAS mount, takes an execution lock, validates the
archive listing, and removes incomplete output on failure. Logs go to
`/var/log/harness-memory-backup.log`. Successful scheduled runs and restore drills
still need operator monitoring; the job does not send alerts.

The integration uncovered a separate RAG backup failure: cron could not find `pct`,
leaving zero-byte `.dump.part` files. The existing RAG script now uses
`/usr/sbin/pct`; a fresh 38 MB dump completed under cron's restricted PATH and its
archive listing validated. This does not retroactively repair missing old backups.
The new memory backup's initial empty schema archive was also restored successfully
to a disposable database, and that database was removed afterward.

Logical dumps contain database objects/data, not cluster login passwords or TLS
files. Disaster recovery must provision the dedicated roles, restore into the memory
database, restore/reissue TLS, rotate/provision the app secret, and reapply network
rules before enabling the API. Validate forced RLS and application permissions.

To disable recall, set `memory_recall.enabled: false` on the affected profiles and
restart the harness. To disable storage as well, first disable recall on every
profile, then move `docker-compose.override.yml` outside the project and run
`docker compose up -d --force-recreate`. Stored data remains intact. The pre-recall
runtime archive is `/root/harness-before-recall-20260908.tar` (app, memory adapter,
profiles); restoring it does not require a database rollback. Pre-memory runtime rollback archive on the harness host:
`/root/harness-before-memory-20260907.tar`. Restore only after reviewing the archive;
its protected `.env` is a deployment secret. Do not drop the memory database to roll
back app code. HBA and `postgresql.auto.conf` pre-change copies are beside those
files with `.before-memory` suffixes; reverting them is an administrator operation.

## Validation and follow-ups

- **113 tests passed** with real disposable PostgreSQL 18.6 for memory and mocked
  generation, including pool reuse, JWT isolation, concurrent duplicate saves,
  rollback cleanup, size limits, SQL injection text, database outage and disabled RLS.
- Real PostgreSQL 18.4 SQL checks on the database host passed for scope isolation, privilege denial,
  expiration filtering and cleanup; their synthetic rows were rolled back.
- Live API save/replay/conflict/search/list/delete passed. Memory survived a harness
  restart; the synthetic record was deleted afterward.
- TLS 1.3 verified. Plaintext, wrong database, wrong hostname and untrusted CA failed.
- Separate initial memory backup restored successfully with forced RLS intact.
- Recall tests cover ownership/permissions, byte limits, full-prompt token accounting,
  expiry/deletion, storage failure and both research response modes.
- On 2026-09-08, all three live profiles recalled a synthetic saved code in fresh
  chats. After deletion, a fresh assistant chat did not recall it. Synthetic data was
  removed. Both scheduled database backups also succeeded overnight.
- All three profiles passed live streaming checks after vLLM completed its independent
  restart: research 6.6 s, assistant 0.2 s, creative 1.0 s on short synthetic prompts.
- Five small warm synthetic memory searches had a median response time of 1.8 ms
  from the harness container. This is not a load or large-corpus benchmark.

For development, install `requirements-dev.txt` and run `pytest`. Real database tests
are opt-in with `HARNESS_TEST_MEMORY_SOCKET` pointing to a disposable PostgreSQL Unix
socket below `/private/tmp/`. Apply migrations there first and enable the test app
role LOGIN. Never point those tests at the live lab; fixture cleanup deletes its
synthetic namespaces. Production offers no plaintext transport switch.

Next: collect recall-quality examples, then decide whether semantic embeddings and
a memory management UI are worthwhile. Save/delete remain explicit; do not grant
automatic model writes merely to improve retrieval.
Per-owner storage quotas, automatic certificate renewal and backup failure alerts
remain operational follow-ups before expanding beyond this personal lab.

References: [PostgreSQL RLS](https://www.postgresql.org/docs/18/ddl-rowsecurity.html),
[PostgreSQL TLS](https://www.postgresql.org/docs/18/ssl-tcp.html),
[Psycopg pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

## UI tool follow-ups — 2026-09-10

The new `local-tools` profile has the same bounded read-only memory recall. A request
may end with a tool result, so recall now selects the latest user message explicitly
and adds saved context there; it never treats the tool result as the user's query or
alters a returned result. Explicit save/delete behavior is unchanged. Attached BoltAI
or Open WebUI memory tools do not automatically write to this ParadeDB store.

## Browser management page (2026-09-16)

Open `/memory` on the harness host (lab: `http://<harness host>:8200/memory`).
Paste the existing harness API key or a verified identity bearer token. Do not use
the database password. The page holds the bearer credential in JavaScript memory
only, never a URL, cookie, or browser storage. Disconnect/reload clears it. Use a
trusted lab connection; use HTTPS when deploying beyond that environment.

The page is independent of Onyx, BoltAI, and Open WebUI. The UI shell is public;
every identity and memory request remains authenticated by the existing API.
It supports explicit save, newest-first paginated browsing, all-terms search
(up to 50 results), and confirmed deletion. Permissions control which actions
appear, and the server independently enforces them. No edit/update API is added.

Saves retain one idempotency key while the page is open if a response is lost.
Retry with unchanged fields. After reloading, check the list before saving again
because the page no longer has that retry identifier. A request timeout does not
prove a save failed. Search has a result limit, not a total-count guarantee.

Saved text renders literally, including Markdown and HTML. No third-party scripts
or assets are loaded. The page applies restrictive CSP and no-store headers.
The browser uses the existing memory API; it has no database credentials.

The current shared `lab-service` scope remains shared. Labels such as “home lab”
and “work lab” do not establish isolation. Automatic capture stays off, and
chat compaction never saves a memory. Deletion cannot remove copies already in
chat histories. Onyx chats only receive harness recall if their model requests
actually go through a recall-enabled harness profile. This page does not import
Onyx memories, index the vault, or change n8n workflows.

Suggested next stage: enforced home/work scopes with retrieval-isolation tests,
then deliberate n8n imports with source references and explicit write authority.

Browser regression checks are opt-in: install Playwright and its Chromium browser,
then run `HARNESS_BROWSER_TESTS=1 python -m pytest tests/test_memory_ui_browser.py`.
`HARNESS_CHROMIUM_PATH` optionally selects an existing Chromium executable. These
checks use synthetic intercepted API responses and never contact the live database.

## Home/work isolation (2026-09-16)

`local-home` and `local-work` are tool-capable profiles cloned from `local-tools`.
Each has a fixed `memory_recall.scope` (`home` or `work`). Add those model IDs in
Onyx and start separate new chats. Existing profiles retain `legacy` recall,
which preserves existing behavior and records. No records are automatically moved
or copied into either new scope. Saved preferences are also scope-isolated.

In `/memory`, select home, work, or legacy before saving/browsing. The selector
controls management only, not another application's chat profile. The CLI accepts
`--scope home` or `--scope work` before its action. API clients use
`X-Harness-Memory-Scope: home`; omitted headers select legacy for compatibility.
Unknown or unauthorized scopes return 403. A chat request's scope header cannot
override its configured profile. Prompt text cannot switch retrieval scope.

Operators map scopes to distinct namespaces in the protected memory YAML:

```yaml
scope_namespaces:
  home: harness_home
  work: harness_work
```

`namespace` continues to identify legacy. The existing PostgreSQL FORCE RLS
policies enforce namespace AND owner boundaries. Each request gets a separate
store view sharing the connection pool, and transaction-local namespace settings
prevent pooled connections carrying a previous request's scope. No schema change,
UPDATE grant, cross-scope fallback, or model-based environment detection is used.

JWT role grants now accept `memory_scopes: [home]`, in addition to memory operation
permissions and profile grants. Omitted scope grants allow only legacy for backward
compatibility. The shared service key can manage all configured scopes: this is
retrieval separation, not separation between people holding that same key.

Do not switch a conversation containing home history into the work profile and
expect history to disappear. The boundary controls memory retrieval, not user/UI
supplied chat text, Onyx retrieved documents, tool results, or model knowledge.
Use separate chats and appropriately scoped Onyx sources. Moving a legacy memory
is deliberately manual: review its text, save it in the intended scope, verify
the save, then explicitly delete its legacy copy if desired.

Validation includes real disposable PostgreSQL tests for conflicting facts and
preferences, listing/search/deletion isolation, idempotency per scope, alternating
connection use, and denied JWT scope selection. Browser tests cover switching
scopes without retaining the previous list.

## Memory in /chat/ and per-account ownership (2026-10-24)

Memories belong to the identity that saved them as well as to a scope. The service key
(`lab-service`) owns everything saved before OIDC sign-in and everything saved through
apps that use the key (Open WebUI, Onyx, n8n); a signed-in account owns its own, separate
set and recalls only those. The `/memory` page signs in with the key, so it shows the
service key's memories, not a signed-in account's.

**Settings → Memory** in `/chat/` manages the signed-in person's own memories: pick a
scope (only the scopes their grant allows), search, add, and delete. It says which
profiles recall the selected scope. No one can see another person's memories there.

To bring the service key's memories into an account, run inside the container after that
account has signed in once (dry run first; back up the memory database):

```bash
docker compose exec -T local-model-harness python scripts/move_memories.py --to alice@example.com --scope home
docker compose exec -T local-model-harness python scripts/move_memories.py --to alice@example.com --scope home --apply
```

Copies keep content, category and source conversation; creation time becomes the copy
time. A rerun after a failure never duplicates, and originals are deleted only after
every copy succeeded (`--keep` copies without deleting). Memories that apps still save
through the service key after the move land under `lab-service` again.

`local-tools` recalls the `home` scope since 2026-10-24, sharing it with `local-home`.
