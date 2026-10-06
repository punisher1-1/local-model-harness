-- Operator-only preparation. NOT applied by the harness at startup.
-- Run once as a database administrator against postgres, never the RAG database.
-- Fail on existing names; inspect/reconcile instead of silently adopting old roles.
\set ON_ERROR_STOP on
CREATE ROLE harness_memory_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE harness_memory_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE DATABASE local_ai_memory OWNER harness_memory_owner TEMPLATE template0;
REVOKE ALL ON DATABASE local_ai_memory FROM PUBLIC;
GRANT CONNECT ON DATABASE local_ai_memory TO harness_memory_app;
-- Leave app NOLOGIN until network/TLS and a separately provisioned credential are ready.
-- Do not grant membership in harness_memory_owner to the application role.
