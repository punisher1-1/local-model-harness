# ADR-002: Separate explicit memory storage on ParadeDB

**Status:** Accepted; explicit storage deployed and verified
**Date:** 2026-09-07
**Deciders:** Project maintainer

## Context

The harness is stateless across chats apart from history supplied by Open WebUI.
A separate RAG corpus can share the PostgreSQL server. The design needs low-latency
memory without a reranker and a path from a single-user lab to separately deployed work systems.

## Decision

Use a dedicated `local_ai_memory` database with owner and restricted application
roles. Start with explicitly saved, bounded private records and lexical search. Use
server-derived scope, application permissions and row-level checks. Stage semantic
embeddings separately; bounded lexical recall was enabled on 2026-09-08. Storage
is opt-in; shared lab-service access requires explicit operator configuration,
with retention until deletion. Automatic capture remains off; recall is read-only
and profile-controlled.

## Options considered

| Option | Complexity | Cost | Scalability | Familiarity |
|---|---|---|---|---|
| Reuse RAG chunks/credentials | Low initially | Existing service | Couples retention and permissions | Familiar but wrong data/privilege boundary |
| Separate database on ParadeDB | Moderate | No additional service | Shared server resources; independent logical schema | Existing Postgres operations |
| Separate pgvector instance | Moderate | Additional running instance | Separate resource/lifecycle boundary | Existing but independently maintained candidate |

## Trade-offs

A separate database avoids treating personal memory as corpus evidence and permits
independent credentials and retention. It shares the server administrator and failure
resources. Lexical search has no embedding latency but misses semantic matches; a
later measured embedding migration can address that. A dedicated role must not
inherit RAG superuser privileges or broad database access through existing rules.

## Consequences

- The RAG corpus remains separate; the harness now exposes explicit memory management.
- Memory writes must be explicit and user-reviewable before retention is enabled.
- The service-key identity cannot distinguish individuals holding the same key.
- Native TLS, restricted login, scoped pool, API permissions and CLI are implemented.
- Bounded lexical recall is implemented; a frontend-independent memory management page is available at `/memory`.
- RLS context trusts the application; it is not independent token verification in SQL.

## Action items

1. [x] Check live database capabilities read-only.
2. [x] Prepare and validate SQL in disposable local PostgreSQL.
3. [x] Document security, deletion, retrieval and connection boundaries.
4. [x] Provision the live memory database and protected application connection.
5. [x] Implement explicit memory API and identity-scoped pool adapter.
6. [x] Verify end-to-end ownership/deletion before enabling real saves.
7. [ ] Evaluate bounded semantic recall without a reranker.

8. [x] Enable and verify bounded read-only recall with provenance and token checks (2026-09-08).

## 2026-09-16: Environment scopes

Reuse existing namespace/owner FORCE RLS rather than add a second data schema.
Operator mappings give home and work distinct namespaces; legacy retains all
existing records. Fixed profile recall selects scope, authorized management
requests select it via header, and JWT roles explicitly grant scopes. Service
keys manage all configured scopes. No chat-driven scope inference or fallback.
