# ADR-008: Team knowledge base in the harness (SQLite FTS5)

Status: accepted, 2026-11-16

## Context

The IT troubleshooting profile needs a knowledge base of the team's own runbooks and
known fixes. The ParadeDB RAG gateway handles large document sets (standards,
textbooks), but it needs its own container, an embedder and an ingest pipeline, and
nobody can edit a document from the harness. For a few hundred short articles that the
team writes themselves, all of that is more than the job needs.

## Decision

Keep the articles in the harness's existing SQLite file (`HARNESS_CHAT_DB`) and search
them with SQLite FTS5, ranked by BM25 (`kb_store.py`).

- **Tools:** `kb_search` returns the best article sections (at most two per article) with
  id, title, section heading and text, in the same shape as `rag_search`. `kb_read`
  returns one whole article. Both are registered as the `kb` server on the `team_kb`
  collection.
- **Only published articles are indexed.** Drafts never reach the model.
- **Editing happens in the UI:** the Settings > Knowledge base tab. Everyone who has
  `kb_search` on `team_kb` can read published articles and try a search. Anyone with the
  `kb_editor` grant can also see drafts and write, publish and delete. Editors publish
  directly; there is no separate approval step.
- **The harness enforces permissions** on the signed-in identity. The service key is not
  a person and cannot edit. Every save records the editor and keeps the earlier
  revision in `kb_revisions`. Saves use optimistic concurrency: a save based on an old
  revision is refused.
- **Off by default.** The `it-troubleshoot` template offers `kb` but does not turn it on.
  A deployment turns it on in `profiles.local.yaml`.

## Turning it on for a deployment

1. Grant access in the identity config (`role_grants`):

   ```yaml
   harness-it:
     profiles: [it-troubleshoot]
     tools: [kb_search, kb_read]
     collections: [team_kb]
   harness-it-editors:
     profiles: [it-troubleshoot]
     tools: [kb_search, kb_read]
     collections: [team_kb]
     kb_editor: true
   ```

2. In `profiles.local.yaml`, list `kb` in the profile's `mcp_servers` and `mcp_default`
   (for example `mcp_servers: [kb]`, `mcp_default: [kb]` where it is the only knowledge base).
3. Run `python scripts/check_config.py`, then restart the harness. The tables are
   created on first start.

Back up `HARNESS_CHAT_DB` to keep the articles; they live in the same file as chat history.

## Consequences

- No new service, container or embedder. Search is by keyword: a query has to share words
  with the article (FTS5 stemming catches word forms, so "renaming" finds "rename").
  Exact error text works well. Paraphrases with no shared words do not. If that becomes a
  problem, add embeddings later or move the content to the RAG gateway.
- `weak` is a heuristic: a result is weak when the top section contains fewer than half of
  the query's meaningful words.
- This replaces the planned `it` collection on the RAG gateway for now. The IT Glue import
  in the planned knowledge flow could write into `kb_articles` instead of the gateway.
