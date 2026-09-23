from contextlib import closing
import json
import sqlite3

import pytest

from termnetlog import backup, cli, db


def seed(path, label='original', version=None):
    if version is None:
        version = len(db.MIGRATIONS)
    with closing(sqlite3.connect(path)) as conn:
        for script in db.MIGRATIONS[:version]:
            conn.executescript(script)
        conn.execute(f'PRAGMA user_version={version}')
        conn.execute("INSERT INTO operators(callsign, operator_notes, created_at) VALUES ('W1AW', 'private note', '2026-01-01')")
        conn.execute("INSERT INTO nets(name,started_utc,notes) VALUES (?, '2026-01-01', 'net note')", (label,))
        conn.execute("INSERT INTO checkins(net_id,callsign,logged_as,seq,time_utc,mobile,has_traffic,relayed_by,notes) VALUES (1,'W1AW','W1AW/M',1,'2026-01-01',1,1,'K9XYZ','entry note')")
        conn.commit()


def contents(path):
    with closing(sqlite3.connect(path)) as conn:
        return {name: conn.execute(f'SELECT * FROM {name}').fetchall()
                for name in ('operators', 'nets', 'checkins')}


def test_complete_recovery_and_safety_snapshot(tmp_path):
    original, target = tmp_path / 'original.db', tmp_path / 'target.db'
    seed(original)
    snapshot = backup.backup(original, tmp_path / 'snapshots')
    metadata = json.loads((snapshot / 'metadata.json').read_text())
    assert metadata['schema_version'] == len(db.MIGRATIONS) and metadata['app_version']
    assert set(p.name for p in snapshot.iterdir()) == {'netlog.db', 'metadata.json'}
    assert backup.restore(snapshot, target) is None
    assert contents(target) == contents(original)
    with closing(sqlite3.connect(target)) as conn:
        conn.execute("UPDATE nets SET name='changed'")
        conn.commit()
    previous = contents(target)
    safety = backup.restore(snapshot, target, replace=True)
    assert contents(safety / 'netlog.db') == previous
    assert contents(target) == contents(original)


def test_wal_snapshot_includes_committed_pages(tmp_path):
    path = tmp_path / 'live.db'
    seed(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("UPDATE nets SET name='in WAL'")
        conn.commit()
        snapshot = backup.backup(path, tmp_path / 'snapshots')
        assert contents(snapshot / 'netlog.db')['nets'][0][1] == 'in WAL'


@pytest.mark.parametrize('kind', ['corrupt', 'future', 'unrelated', 'foreign_key'])
def test_invalid_candidate_preserves_destination(tmp_path, kind):
    candidate, target = tmp_path / 'bad.db', tmp_path / 'target.db'
    seed(target)
    before = contents(target)
    if kind == 'corrupt':
        candidate.write_bytes(b'not SQLite')
    else:
        seed(candidate)
        with closing(sqlite3.connect(candidate)) as conn:
            if kind == 'future':
                conn.execute('PRAGMA user_version=999')
            elif kind == 'unrelated':
                conn.execute('CREATE TABLE surprise(x)')
            else:
                conn.execute('DELETE FROM operators')
            conn.commit()
    with pytest.raises((backup.BackupError, sqlite3.Error)):
        backup.restore(candidate, target, replace=True)
    assert contents(target) == before
    assert not (tmp_path / 'backups').exists()


def test_replace_requires_explicit_flag(tmp_path):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    seed(target, 'target')
    with pytest.raises(backup.BackupError, match='--replace'):
        backup.restore(source, target)
    assert contents(target)['nets'][0][1] == 'target'


@pytest.mark.parametrize('version', [1, 2])
def test_old_schema_upgrades_only_restored_copy(tmp_path, version):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source, version=version)
    backup.restore(source, target)
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == version
    with closing(sqlite3.connect(target)) as conn:
        assert backup.validate(conn) == len(db.MIGRATIONS)
    expected = contents(source)
    expected['checkins'] = [row + (0,) for row in expected['checkins']]
    assert expected == contents(target)


def test_failed_safety_backup_prevents_replacement(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    seed(target, 'target')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(backup, '_snapshot', fail)
    with pytest.raises(OSError):
        backup.restore(source, target, replace=True)
    assert contents(target)['nets'][0][1] == 'target'


def test_cli_recovery_ignores_broken_configuration(tmp_path, capsys):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    config = tmp_path / 'bad.toml'
    config.write_text('not valid TOML')
    assert cli.main(['--config', str(config), '--db', str(source), 'backup', '--directory', str(tmp_path / 'snapshots')]) == 0
    snapshot = next((tmp_path / 'snapshots').iterdir())
    assert cli.main(['--config', str(config), '--db', str(target), 'restore', str(snapshot)]) == 0
    assert contents(source) == contents(target)
    assert cli.main(['--db', str(target), 'restore', str(snapshot)]) == 1
    assert '--replace' in capsys.readouterr().err


def test_missing_source_does_not_create_database(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.Error):
        backup.backup(path, tmp_path / 'snapshots')
    assert not path.exists()


def test_restore_existing_wal_database(tmp_path):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    seed(target, 'target')
    with closing(sqlite3.connect(target)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    safety = backup.restore(source, target, replace=True)
    assert contents(safety / 'netlog.db')['nets'][0][1] == 'target'
    assert contents(target) == contents(source)


def test_active_writer_blocks_restore_without_changes(tmp_path):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    seed(target, 'target')
    with closing(sqlite3.connect(target)) as writer:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("UPDATE nets SET name='working'")
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            backup.restore(source, target, replace=True)
        writer.commit()
    assert contents(target)['nets'][0][1] == 'working'


def test_copy_failure_preserves_destination_and_safety(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    seed(target, 'target')
    original = backup._copy
    calls = 0
    def fail_last(src, dest):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError('write failure')
        original(src, dest)
    monkeypatch.setattr(backup, '_copy', fail_last)
    with pytest.raises(OSError):
        backup.restore(source, target, replace=True)
    assert contents(target)['nets'][0][1] == 'target'
    safety = next((tmp_path / 'backups').iterdir())
    assert contents(safety / 'netlog.db') == contents(target)


def test_snapshot_publication_failure_leaves_no_partial_bundle(tmp_path, monkeypatch):
    source = tmp_path / 'source.db'
    seed(source)
    def fail(*args):
        raise OSError('rename failure')
    monkeypatch.setattr(type(source), 'rename', fail)
    with pytest.raises(OSError):
        backup.backup(source, tmp_path / 'snapshots')
    assert list((tmp_path / 'snapshots').iterdir()) == []


def test_interrupted_sqlite_copy_rolls_back_written_pages(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.db', tmp_path / 'target.db'
    seed(source)
    seed(target, 'target')
    with closing(sqlite3.connect(source)) as conn:
        conn.execute('UPDATE operators SET operator_notes=?', ('x' * 100000,))
        conn.commit()
    original = backup._copy
    calls = 0
    def interrupt_last(src, dest):
        nonlocal calls
        calls += 1
        if calls != 3:
            return original(src, dest)
        def interrupted(status, remaining, total):
            assert remaining > 0
            raise OSError('interrupted after page write')
        src.backup(dest, pages=1, progress=interrupted)
    monkeypatch.setattr(backup, '_copy', interrupt_last)
    before = contents(target)
    with pytest.raises(OSError, match='page write'):
        backup.restore(source, target, replace=True)
    assert contents(target) == before
