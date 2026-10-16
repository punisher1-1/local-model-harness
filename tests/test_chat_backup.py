import importlib.util
from pathlib import Path
import sqlite3
import json
import hashlib
import pytest

spec=importlib.util.spec_from_file_location('chat_backup',Path(__file__).parents[1]/'scripts/backup_chat_history.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_online_wal_restore_and_retention(tmp_path):
    source=tmp_path/'source.sqlite3';directory=tmp_path/'backups'
    with sqlite3.connect(source) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE conversations (content TEXT)')
        db.execute("INSERT INTO conversations VALUES ('synthetic restore evidence')")
        db.commit()
        first=module.backup(source,directory,keep=2)
        module.backup(source,directory,keep=2)
        latest=module.backup(source,directory,keep=2)
    assert not first.exists()
    assert len(list(directory.glob('*.sqlite3')))==2
    with sqlite3.connect(latest) as restored:
        assert restored.execute('SELECT content FROM conversations').fetchone()[0]=='synthetic restore evidence'
    assert latest.stat().st_mode & 0o777 == 0o600
    manifest=json.loads(latest.with_suffix('.json').read_text())
    assert manifest['sha256']==hashlib.sha256(latest.read_bytes()).hexdigest()


def test_failure_does_not_prune_or_publish(tmp_path):
    source=tmp_path/'bad.sqlite3';source.write_text('invalid database')
    directory=tmp_path/'backups';directory.mkdir()
    previous=directory/'chat-history-20000101T000000000000Z.sqlite3';previous.write_text('existing')
    with pytest.raises(sqlite3.DatabaseError):module.backup(source,directory,1)
    assert previous.exists()
    assert not list(directory.glob('.pending-*'))
    with pytest.raises(FileNotFoundError):module.backup(tmp_path/'missing',directory)
