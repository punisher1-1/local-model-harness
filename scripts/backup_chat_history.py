#!/usr/bin/env python3
"""Online SQLite snapshots with verification, atomic publication, and bounded retention."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

PATTERN = re.compile(r"chat-history-\d{8}T\d{12}Z\.sqlite3$")


def snapshot(source, destination):
    with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst, pages=256, sleep=0.1)
            if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("Backup integrity check failed")
            count = dst.execute("SELECT count(*) FROM conversations").fetchone()[0]
    return count


def backup(source, directory, keep=30):
    if keep < 1:
        raise ValueError("Retention must be positive")
    if not source.is_file():
        raise FileNotFoundError("Source database does not exist")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    with (directory/'.backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        final = directory/f'chat-history-{stamp}.sqlite3'
        fd, name = tempfile.mkstemp(prefix='.pending-', dir=directory)
        os.close(fd)
        pending = Path(name)
        try:
            count = snapshot(source, pending)
            digest = hashlib.sha256(pending.read_bytes()).hexdigest()
            with pending.open('rb') as data:
                os.fsync(data.fileno())
            pending.replace(final)
            with final.with_suffix('.json').open('w') as manifest:
                json.dump({'file':final.name,'sha256':digest,'conversations':count,'integrity':'ok'}, manifest)
                manifest.flush()
                os.fsync(manifest.fileno())
            os.chmod(final.with_suffix('.json'), 0o600)
            # Only prune this script's completed snapshots after a verified replacement exists.
            old = sorted((p for p in directory.iterdir() if p.is_file() and PATTERN.fullmatch(p.name)), reverse=True)
            for item in old[keep:]:
                item.unlink()
                item.with_suffix('.json').unlink(missing_ok=True)
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            print(json.dumps({'backup':str(final),'integrity':'ok','conversations':count,'retention':keep}))
            return final
        finally:
            pending.unlink(missing_ok=True)


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--keep', type=int, default=30)
    args = parser.parse_args()
    backup(args.database, args.directory, args.keep)
