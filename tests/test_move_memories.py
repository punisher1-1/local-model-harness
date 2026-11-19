"""scripts/move_memories.py against an in-memory stand-in for the memory store."""
import asyncio
import copy
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

spec = importlib.util.spec_from_file_location("move_memories", Path(__file__).parent.parent / "scripts" / "move_memories.py")
move_memories = importlib.util.module_from_spec(spec)
spec.loader.exec_module(move_memories)

NOW = datetime.now(timezone.utc)


class Config:
    def __init__(self, namespace):
        self.namespace = namespace


class FakeStore:
    """Rows keyed by (namespace, owner); scopes map to namespaces like the real config."""
    SCOPES = {"legacy": "personal_lab", "home": "harness_home"}

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else {}
        self.config = Config("personal_lab")

    def for_scope(self, principal, scope):
        scoped = copy.copy(self)
        scoped.config = Config(self.SCOPES[scope])
        return scoped

    def bucket(self, principal):
        return self.rows.setdefault((self.config.namespace, principal.actor_id), [])

    async def list(self, principal, limit, cursor=None):
        rows = self.bucket(principal)
        start = int(cursor or 0)
        return {"data": rows[start:start + limit], "next_cursor": str(start + limit) if start + limit < len(rows) else None}

    async def save(self, principal, body):
        rows = self.bucket(principal)
        if any(r["idempotency_key"] == body.idempotency_key for r in rows):
            return None, False
        rows.append({"memory_id": uuid4(), "content": body.content, "category": body.category,
                     "source_conversation_id": body.source_conversation_id, "idempotency_key": body.idempotency_key,
                     "created_at": NOW, "expires_at": None})
        return rows[-1], True

    async def delete(self, principal, memory_id):
        rows = self.bucket(principal)
        if not any(r["memory_id"] == memory_id for r in rows):
            raise HTTPException(404, "Memory not found")
        rows[:] = [r for r in rows if r["memory_id"] != memory_id]


def legacy_rows(n=150):
    rows = [{"memory_id": uuid4(), "content": f"fact {i}", "category": "preference" if i % 50 == 0 else "fact",
             "source_conversation_id": None, "idempotency_key": uuid4(), "created_at": NOW, "expires_at": None} for i in range(n)]
    rows.append({**rows[0], "memory_id": uuid4(), "content": "expired", "expires_at": NOW - timedelta(days=1)})
    return rows


def run(store, apply, keep=False):
    lines = []
    target = move_memories.target_principal("alice-actor", "home")
    asyncio.run(move_memories.move(store, target, "legacy", "home", apply, keep, "Alice <alice@example.test>", lines.append))
    return lines


def test_dry_run_changes_nothing():
    store = FakeStore({("personal_lab", "lab-service"): legacy_rows()})
    lines = run(store, apply=False)
    assert lines[0] == ("Would move 150 memories (147 facts, 3 preferences) from the service key's legacy scope "
                        "to Alice <alice@example.test> in home.")
    assert len(store.rows[("personal_lab", "lab-service")]) == 151 and ("harness_home", "alice-actor") not in store.rows


def test_apply_copies_every_page_then_deletes_and_a_rerun_never_duplicates():
    original = legacy_rows()
    store = FakeStore({("personal_lab", "lab-service"): list(original)})
    lines = run(store, apply=True)
    moved = store.rows[("harness_home", "alice-actor")]
    assert [r["content"] for r in moved] == [f"fact {i}" for i in range(150)]
    assert lines[1] == "Copied 150 (already there from an earlier run: 0)."
    assert [r["content"] for r in store.rows[("personal_lab", "lab-service")]] == ["expired"]

    # A failure before the delete leaves originals; rerunning copies nothing twice.
    store.rows[("personal_lab", "lab-service")] = list(original)
    assert run(store, apply=True)[1] == "Copied 0 (already there from an earlier run: 150)."
    assert len(store.rows[("harness_home", "alice-actor")]) == 150


def test_keep_copies_without_deleting():
    store = FakeStore({("personal_lab", "lab-service"): legacy_rows(3)})
    assert run(store, apply=True, keep=True)[-1] == "Originals kept (--keep)."
    assert len(store.rows[("personal_lab", "lab-service")]) == 4 and len(store.rows[("harness_home", "alice-actor")]) == 3


def test_an_accounts_own_legacy_memories_move_to_its_home_scope():
    store = FakeStore({("personal_lab", "alice-actor"): legacy_rows(2), ("personal_lab", "lab-service"): legacy_rows(1)})
    alice_legacy = move_memories.target_principal("alice-actor", "legacy")
    lines = []
    asyncio.run(move_memories.move(store, move_memories.target_principal("alice-actor", "home"), "legacy", "home", True, False,
                                   "Alice <alice@example.test>", lines.append, source=alice_legacy, source_label="Alice <alice@example.test>"))
    assert lines[0].startswith("Moving 2 memories (1 fact, 1 preference) from Alice <alice@example.test>'s legacy scope")
    assert [r["content"] for r in store.rows[("harness_home", "alice-actor")]] == ["fact 0", "fact 1"]
    assert [r["content"] for r in store.rows[("personal_lab", "alice-actor")]] == ["expired"]
    # The service key's memories are untouched.
    assert len(store.rows[("personal_lab", "lab-service")]) == 2


def test_same_owner_and_scope_is_refused():
    store = FakeStore({("personal_lab", "alice-actor"): legacy_rows(2)})
    lines = []
    alice = move_memories.target_principal("alice-actor", "legacy")
    asyncio.run(move_memories.move(store, alice, "legacy", "legacy", True, False, "Alice", lines.append, source=alice, source_label="Alice"))
    assert lines == ["Source and target are the same owner and scope; nothing to move."]
