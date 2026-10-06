-- Synthetic conformance tests. Run after 001, as administrator, in a scratch DB.
-- Everything inserted here is rolled back. Errors abort the test.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE harness_memory_app;
DO $$ BEGIN
 IF (SELECT count(*) FROM harness_memory.memories) <> 0 THEN
   RAISE EXCEPTION 'Missing scope exposed rows';
 END IF;
 BEGIN
   INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key)
   VALUES ('test-a','alice','unscoped',gen_random_uuid());
   RAISE EXCEPTION 'Missing scope permitted insert';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
SELECT set_config('harness.namespace','test-a',true), set_config('harness.owner_id','alice',true);
INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key)
VALUES ('test-a','alice','Synthetic preference: concise answers','00000000-0000-0000-0000-000000000001');
DO $$ BEGIN
 IF (SELECT count(*) FROM harness_memory.memories) <> 1 THEN RAISE EXCEPTION 'Owner cannot read'; END IF;
 IF (SELECT count(*) FROM harness_memory.memories WHERE search_document @@ plainto_tsquery('simple','concise')) <> 1 THEN RAISE EXCEPTION 'Search failed'; END IF;
 BEGIN
  INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key)
  VALUES ('test-a','bob','forged owner',gen_random_uuid());
  RAISE EXCEPTION 'Forged owner permitted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  UPDATE harness_memory.memories SET content='unexpected';
  RAISE EXCEPTION 'Update permitted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
  TRUNCATE harness_memory.memories;
  RAISE EXCEPTION 'Truncate permitted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
DO $$ BEGIN
 BEGIN
  INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key)
  VALUES ('test-a','alice','duplicate','00000000-0000-0000-0000-000000000001');
  RAISE EXCEPTION 'Duplicate idempotency key accepted';
 EXCEPTION WHEN unique_violation THEN NULL; END;
 BEGIN
  INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key)
  VALUES ('test-a','alice',repeat('x',8193),gen_random_uuid());
  RAISE EXCEPTION 'Oversized memory accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
RESET ROLE;
INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key,created_at,expires_at)
VALUES ('test-a','alice','expired synthetic memory','00000000-0000-0000-0000-000000000002',now()-interval '2 days',now()-interval '1 day');
SET LOCAL ROLE harness_memory_app;
DO $$ DECLARE affected integer; BEGIN
 IF (SELECT count(*) FROM harness_memory.active_memories) <> 1 THEN RAISE EXCEPTION 'Expired memory recalled'; END IF;
 DELETE FROM harness_memory.memories WHERE idempotency_key='00000000-0000-0000-0000-000000000002';
 GET DIAGNOSTICS affected = ROW_COUNT;
 IF affected <> 1 THEN RAISE EXCEPTION 'Owner cannot delete expired memory'; END IF;
END $$;
SELECT set_config('harness.namespace','',true), set_config('harness.owner_id','',true);
DO $$ BEGIN
 IF (SELECT count(*) FROM harness_memory.memories) <> 0 THEN RAISE EXCEPTION 'Missing scope exposed existing rows'; END IF;
END $$;
SELECT set_config('harness.namespace','test-a',true);
SELECT set_config('harness.owner_id','bob',true);
DO $$ DECLARE affected integer; BEGIN
 IF (SELECT count(*) FROM harness_memory.memories) <> 0 THEN RAISE EXCEPTION 'Cross-owner read'; END IF;
 DELETE FROM harness_memory.memories WHERE namespace='test-a';
 GET DIAGNOSTICS affected = ROW_COUNT;
 IF affected <> 0 THEN RAISE EXCEPTION 'Cross-owner delete'; END IF;
END $$;
INSERT INTO harness_memory.memories(namespace,owner_id,content,idempotency_key)
VALUES ('test-a','bob','Synthetic Bob memory','00000000-0000-0000-0000-000000000001');
SELECT set_config('harness.namespace','test-b',true);
DO $$ BEGIN
 IF (SELECT count(*) FROM harness_memory.memories) <> 0 THEN RAISE EXCEPTION 'Cross-namespace read'; END IF;
END $$;
SELECT set_config('harness.namespace','test-a',true), set_config('harness.owner_id','alice',true);
DO $$ DECLARE affected integer; BEGIN
 DELETE FROM harness_memory.memories WHERE idempotency_key='00000000-0000-0000-0000-000000000001';
 GET DIAGNOSTICS affected = ROW_COUNT;
 IF affected <> 1 THEN RAISE EXCEPTION 'Owner delete failed'; END IF;
END $$;
ROLLBACK;
-- A new transaction must not inherit a prior request's identity.
BEGIN;
SET LOCAL ROLE harness_memory_app;
DO $$ BEGIN
 IF nullif(current_setting('harness.owner_id',true),'') IS NOT NULL OR
    nullif(current_setting('harness.namespace',true),'') IS NOT NULL THEN
   RAISE EXCEPTION 'Transaction-local scope leaked';
 END IF;
END $$;
ROLLBACK;
\echo 'Memory ownership and privilege checks passed; synthetic rows rolled back.'
