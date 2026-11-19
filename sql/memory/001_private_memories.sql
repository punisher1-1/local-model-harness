-- Run once as an administrator in the dedicated local_ai_memory database.
-- No extension, embeddings, reranker, or RAG table dependency.
\set ON_ERROR_STOP on
SELECT current_database() = 'local_ai_memory' AS correct_database \gset
\if :correct_database
\else
  \echo 'Refusing migration outside local_ai_memory'
  \quit 3
\endif
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SET LOCAL ROLE harness_memory_owner;
CREATE SCHEMA harness_memory AUTHORIZATION harness_memory_owner;
REVOKE ALL ON SCHEMA harness_memory FROM PUBLIC;
CREATE TABLE harness_memory.memories (
    memory_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    namespace text NOT NULL CHECK (length(namespace) BETWEEN 1 AND 64),
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 128),
    content text NOT NULL CHECK (length(btrim(content)) > 0 AND octet_length(content) <= 8192),
    category text NOT NULL DEFAULT 'note' CHECK (category IN ('note', 'preference', 'fact')),
    source_conversation_id text CHECK (length(source_conversation_id) BETWEEN 1 AND 128),
    idempotency_key uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz CHECK (expires_at IS NULL OR expires_at > created_at),
    search_document tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, content)) STORED,
    UNIQUE (namespace, owner_id, idempotency_key)
);
CREATE INDEX memories_owner_recent ON harness_memory.memories (namespace, owner_id, created_at DESC, memory_id);
CREATE INDEX memories_text_search ON harness_memory.memories USING gin (search_document);
ALTER TABLE harness_memory.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE harness_memory.memories FORCE ROW LEVEL SECURITY;
CREATE POLICY memory_select ON harness_memory.memories FOR SELECT TO harness_memory_app
USING (
    namespace = nullif(current_setting('harness.namespace', true), '')
    AND owner_id = nullif(current_setting('harness.owner_id', true), '')
);
CREATE POLICY memory_insert ON harness_memory.memories FOR INSERT TO harness_memory_app
WITH CHECK (
    namespace = nullif(current_setting('harness.namespace', true), '')
    AND owner_id = nullif(current_setting('harness.owner_id', true), '')
    AND (expires_at IS NULL OR expires_at > now())
);
-- Ownership applies to expired rows too, so owners can list/manage/delete them.
CREATE POLICY memory_delete ON harness_memory.memories FOR DELETE TO harness_memory_app
USING (
    namespace = nullif(current_setting('harness.namespace', true), '')
    AND owner_id = nullif(current_setting('harness.owner_id', true), '')
);
GRANT USAGE ON SCHEMA harness_memory TO harness_memory_app;
GRANT SELECT, DELETE ON harness_memory.memories TO harness_memory_app;
GRANT INSERT (namespace, owner_id, content, category, source_conversation_id, idempotency_key, expires_at)
    ON harness_memory.memories TO harness_memory_app;
-- No UPDATE, TRUNCATE, schema CREATE, ownership, or owner-role membership for the app.
CREATE VIEW harness_memory.active_memories WITH (security_invoker = true) AS
SELECT * FROM harness_memory.memories WHERE expires_at IS NULL OR expires_at > now();
GRANT SELECT ON harness_memory.active_memories TO harness_memory_app;
CREATE TABLE harness_memory.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO harness_memory.schema_migrations(version) VALUES (1);
GRANT SELECT ON harness_memory.schema_migrations TO harness_memory_app;
COMMIT;
