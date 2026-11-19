#!/usr/bin/env python3
"""Move the shared service-key chats, projects and skills to one signed-in account.

Before OIDC sign-in (ADR-004), everyone in /chat/ used the service key, so all saved
data belongs to the `lab-service` owner. Once the account has signed in at least once,
run this inside the harness container:

    python scripts/claim_shared_data.py                    # list accounts and what is shared
    python scripts/claim_shared_data.py --to alice@example.com      # dry run: show what would move
    python scripts/claim_shared_data.py --to alice@example.com --apply

It moves rows in one transaction and never deletes anything. Chats keep their IDs,
revisions and projects. Take a backup first (scripts/backup_chat_history.py).
"""
import argparse
from contextlib import closing
import json
import os
import sqlite3
import sys

SERVICE_OWNER = json.dumps(["service_key", "lab-service"])
TABLES = ("conversations", "projects", "user_skills")


def connect(path):
    if not path or not os.path.exists(path):
        sys.exit("Set HARNESS_CHAT_DB to the chat database (it is set inside the harness container).")
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def counts(db, owner):
    return {t: db.execute(f"SELECT count(*) FROM {t} WHERE owner=?", (owner,)).fetchone()[0] for t in TABLES}


def find_account(db, who):
    rows = db.execute("SELECT * FROM accounts WHERE lower(email)=lower(?) OR subject=? OR actor_id=?", (who, who, who)).fetchall()
    if len(rows) != 1:
        sys.exit(f"No single signed-in account matches {who!r}. Run without --to to list accounts; "
                 "an account appears after its first sign-in.")
    return rows[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", default=os.getenv("HARNESS_CHAT_DB"))
    parser.add_argument("--to", help="email, subject or actor ID of a signed-in account")
    parser.add_argument("--apply", action="store_true", help="move the rows (default is a dry run)")
    args = parser.parse_args(argv)
    with closing(connect(args.db)) as db:
        try:
            accounts = db.execute("SELECT * FROM accounts ORDER BY last_seen DESC").fetchall()
        except sqlite3.OperationalError:
            sys.exit("No accounts table yet: start the new harness version and sign in once first.")
        shared = counts(db, SERVICE_OWNER)
        if not args.to:
            print("Shared (service key):", ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in shared.items()))
            print("Signed-in accounts:" if accounts else "No one has signed in yet.")
            for a in accounts:
                owner = json.dumps(["jwt_subject", a["actor_id"]])
                mine = counts(db, owner)
                print(f"  {a['name'] or '(no name)'} <{a['email'] or 'no email'}>  groups {json.loads(a['groups'])}  "
                      f"last sign-in {a['last_seen'][:16]}  owns {mine['conversations']} chats")
            return 0
        account = find_account(db, args.to)
        target = json.dumps(["jwt_subject", account["actor_id"]])
        clashes = {t: db.execute(f"SELECT count(*) FROM {t} s JOIN {t} d ON s.id=d.id WHERE s.owner=? AND d.owner=?",
                                 (SERVICE_OWNER, target)).fetchone()[0] for t in TABLES}
        label = f"{account['name'] or account['email']} <{account['email']}>"
        print(f"{'Moving' if args.apply else 'Would move'} to {label}:",
              ", ".join(f"{shared[t] - clashes[t]} {t.replace('_', ' ')}" for t in TABLES))
        if any(clashes.values()):
            print("Skipped (the account already has the same ID):", clashes)
        if not args.apply:
            print("Dry run only. Add --apply to move them.")
            return 0
        with db:
            db.execute("BEGIN IMMEDIATE")
            for t in TABLES:
                db.execute(f"UPDATE OR IGNORE {t} SET owner=? WHERE owner=?", (target, SERVICE_OWNER))
        print("Done. Left with the service key:", counts(db, SERVICE_OWNER))
    return 0


if __name__ == "__main__":
    sys.exit(main())
