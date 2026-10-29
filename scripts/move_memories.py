#!/usr/bin/env python3
"""Move memories to one signed-in account and scope: the shared service key's, or an
account's own memories from another scope.

Memories belong to the identity that saved them. Everything saved before OIDC sign-in
(ADR-004), and everything saved through apps that use the service key, belongs to
`lab-service`, so a signed-in account never recalls it. Run inside the harness container
after the account has signed in at least once:

    python scripts/move_memories.py --to alice@example.com --scope home            # dry run: counts only
    python scripts/move_memories.py --to alice@example.com --scope home --apply    # copy, then delete originals
    python scripts/move_memories.py --to alice@example.com --scope home --apply --keep   # copy only
    python scripts/move_memories.py --from-scope work --to alice@example.com --scope work  # another scope
    python scripts/move_memories.py --from alice@example.com --to alice@example.com --scope home    # own legacy -> home

Copies keep content, category and source conversation; their creation time is the copy
time. Each copy's idempotency key is derived from the original memory ID, so rerunning
after a failure never duplicates. Originals are deleted only after every copy succeeded.
Back up the memory database first.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import os
import sys
from uuid import UUID, uuid5

from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..")]
from identity import Principal  # noqa: E402
from memory import PERMISSIONS, MemoryConfig, MemoryStore, SaveMemory  # noqa: E402
from claim_shared_data import connect, find_account  # noqa: E402

# Fixed namespace for copy keys: the same original always yields the same key.
COPY_KEYS = UUID("8f0d6a8e-4c43-4f61-9a55-7d1f8c0e2b91")
SERVICE = Principal("service_key", "lab-service", frozenset(), frozenset(), frozenset())


def target_principal(actor_id, *scopes):
    return Principal("jwt_subject", actor_id, frozenset(), frozenset(), frozenset(),
                     memory_permissions=PERMISSIONS, memory_scopes=frozenset(scopes))


async def all_rows(store, principal):
    rows, cursor = [], None
    while True:
        page = await store.list(principal, 100, cursor)
        rows += page["data"]
        cursor = page["next_cursor"]
        if not cursor:
            return rows


async def move(store, target, from_scope, to_scope, apply, keep, label, out=print, source=SERVICE, source_label="the service key"):
    if source.actor_id == target.actor_id and from_scope == to_scope:
        out("Source and target are the same owner and scope; nothing to move.")
        return 0
    source_store = store.for_scope(source, from_scope)
    target_store = store.for_scope(target, to_scope)
    now = datetime.now(timezone.utc)
    rows = [r for r in await all_rows(source_store, source) if not r["expires_at"] or r["expires_at"] > now]
    kinds = Counter(r["category"] for r in rows)
    summary = ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in sorted(kinds.items())) or "nothing"
    out(f"{'Moving' if apply else 'Would move'} {len(rows)} memories ({summary}) "
        f"from {source_label}'s {from_scope} scope to {label} in {to_scope}.")
    if not apply:
        out("Dry run only. Add --apply to copy them" + ("." if keep else ", then delete the originals."))
        return 0
    created = 0
    for row in rows:
        body = SaveMemory(content=row["content"], category=row["category"],
                          source_conversation_id=row["source_conversation_id"],
                          idempotency_key=uuid5(COPY_KEYS, f"{source_store.config.namespace}:{row['memory_id']}"))
        _, new = await target_store.save(target, body)
        created += new
    out(f"Copied {created} (already there from an earlier run: {len(rows) - created}).")
    if keep:
        out("Originals kept (--keep).")
        return 0
    for row in rows:
        await source_store.delete(source, row["memory_id"])
    out(f"Deleted {len(rows)} originals from {source_label}'s {from_scope} scope.")
    return 0


async def run(args):
    with connect(args.db) as db:
        account = find_account(db, args.to)
        origin = find_account(db, args.source) if args.source else None
    config_path = os.getenv("HARNESS_MEMORY_CONFIG")
    if not config_path:
        sys.exit("Set HARNESS_MEMORY_CONFIG (it is set inside the harness container).")
    config = MemoryConfig.load(config_path)
    for scope in (args.scope, args.from_scope):
        if scope != "legacy" and scope not in config.scope_namespaces:
            sys.exit(f"Unknown scope {scope!r}; configured: legacy, " + ", ".join(sorted(config.scope_namespaces)))
    if not origin and not config.allow_shared_service_identity:
        sys.exit("The memory config does not allow the service key, so it owns no memories to move.")
    store = MemoryStore(config)
    await store.pool.open()
    try:
        name = lambda a: f"{a['name'] or a['email']} <{a['email']}>"
        source = target_principal(origin["actor_id"], args.from_scope) if origin else SERVICE
        return await move(store, target_principal(account["actor_id"], args.scope), args.from_scope, args.scope,
                          args.apply, args.keep, name(account), source=source,
                          source_label=name(origin) if origin else "the service key")
    except HTTPException as exc:
        sys.exit(f"Stopped: {exc.detail}. Nothing was deleted; rerunning is safe.")
    finally:
        await store.pool.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", default=os.getenv("HARNESS_CHAT_DB"), help="chat database, for the account lookup")
    parser.add_argument("--to", required=True, help="email, subject or actor ID of a signed-in account")
    parser.add_argument("--scope", required=True, help="target memory scope, such as home")
    parser.add_argument("--from", dest="source", help="move this signed-in account's memories instead of the service key's")
    parser.add_argument("--from-scope", default="legacy", help="the scope to move from (default: legacy)")
    parser.add_argument("--apply", action="store_true", help="copy the memories (default is a dry run)")
    parser.add_argument("--keep", action="store_true", help="with --apply, keep the originals")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
