from contextlib import closing
from dataclasses import asdict
import sqlite3

import pytest

from termnetlog import backup, cli, config, db, entry, setup
from termnetlog.repo import Repo, DuplicateCheckIn
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CheckinTable


def session(repo):
    return repo.create_net('Test', '146.520', 'FM', '2m', 'W1AW', 'ncs')


def add(repo, net, call):
    return repo.record_entry(net.id, entry.parse(call))


def test_undo_preserves_fields_and_order(repo):
    net = session(repo)
    first = add(repo, net, 'W1AW')
    removed = add(repo, net, 'K9XYZ/m t r via W1AW entry note')
    last = add(repo, net, 'K1ABC')
    repo.set_operator_notes('K9XYZ', 'private note')
    snapshot = repo.delete_checkin(removed.id)
    assert snapshot == removed
    assert [r.checkin.seq for r in repo.list_checkins(net.id)] == [1, 2]
    restored = repo.restore_checkin(snapshot)
    assert restored == removed
    assert [r.checkin.id for r in repo.list_checkins(net.id)] == [first.id, removed.id, last.id]
    assert repo.get_operator('K9XYZ').operator_notes == 'private note'


def test_undo_handles_reused_id_and_keeps_later_entry(repo):
    net = session(repo)
    removed = add(repo, net, 'W1AW t note')
    repo.delete_checkin(removed.id)
    later = add(repo, net, 'K9XYZ')
    assert later.id == removed.id
    restored = repo.restore_checkin(removed)
    assert restored.id != later.id
    assert repo.get_checkin(later.id).callsign == 'K9XYZ'
    expected = asdict(removed)
    expected['id'] = restored.id
    assert asdict(restored) == expected
    assert [r.checkin.seq for r in repo.list_checkins(net.id)] == [1, 2]


def test_duplicate_undo_does_not_merge_or_reorder(repo):
    net = session(repo)
    removed = add(repo, net, 'W1AW t old note')
    repo.delete_checkin(removed.id)
    later = add(repo, net, 'W1AW r new note')
    with pytest.raises(DuplicateCheckIn):
        repo.restore_checkin(removed)
    assert repo.get_checkin(later.id) == later


def test_failed_restore_rolls_back_sequence_shift(repo):
    net = session(repo)
    removed = add(repo, net, 'W1AW')
    add(repo, net, 'K9XYZ')
    repo.delete_checkin(removed.id)
    before = [asdict(r.checkin) for r in repo.list_checkins(net.id)]
    repo.conn.execute("CREATE TRIGGER reject_restore BEFORE INSERT ON checkins BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.restore_checkin(removed)
    assert [asdict(r.checkin) for r in repo.list_checkins(net.id)] == before


def test_remove_and_restore_respect_outer_transaction(repo):
    net = session(repo)
    original = add(repo, net, 'W1AW')
    repo.conn.execute('BEGIN')
    snapshot = repo.delete_checkin(original.id)
    repo.conn.rollback()
    assert repo.get_checkin(original.id) == original
    repo.delete_checkin(original.id)
    repo.conn.execute('BEGIN')
    repo.restore_checkin(snapshot)
    repo.conn.rollback()
    assert repo.list_checkins(net.id) == []


async def test_tui_undo_survives_navigation_and_keeps_stack_after_failure(repo, tmp_path, monkeypatch):
    net = session(repo)
    removed = add(repo, net, 'W1AW t note')
    app = NetLogApp(config.Config(offline=True), repo, export_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_net(net.id)
        await pilot.pause()
        await pilot.press('escape', 'delete', 'y')
        assert repo.list_checkins(net.id) == []
        await pilot.press('ctrl+b')
        app.open_net(net.id)
        await pilot.pause()
        original = repo.restore_checkin
        def fail(record):
            raise sqlite3.OperationalError('disk full')
        monkeypatch.setattr(repo, 'restore_checkin', fail)
        await pilot.press('ctrl+z')
        assert len(app.removed_checkins[net.id]) == 1
        monkeypatch.setattr(repo, 'restore_checkin', original)
        await pilot.press('ctrl+z')
        assert repo.get_checkin(removed.id) == removed
        assert app.removed_checkins[net.id] == []
        assert app.screen.query_one(CheckinTable).selected_id() == removed.id


async def test_offline_setup_export_backup_restore_drill(tmp_path):
    cfg_path, db_path = tmp_path / 'config.toml', tmp_path / 'logs.db'
    assert cli.main(['--config', str(cfg_path), 'config', '--set', 'my_callsign', 'W1AW', '--set', 'lookup.offline', 'true']) == 0
    setup.edit(cfg_path, [['net.name', 'Weekly'], ['net.notes', 'Opening notes']], template='Club')
    cfg = config.load(cfg_path)
    cfg.db_path = db_path
    with closing(db.connect(db_path)) as conn:
        repo = Repo(conn)
        app = NetLogApp(cfg, repo, export_dir=tmp_path / 'exports')
        async with app.run_test(size=(80, 24)) as pilot:
            app.screen.start_with_defaults(cfg.templates['Club'])
            await pilot.press('ctrl+s')
            await pilot.pause()
            net_id = app.screen.net_id
            from termnetlog.tui.widgets.checkin_table import CallInput
            app.screen.query_one(CallInput).value = 'K9XYZ t r via W1AW entry note'
            await pilot.press('enter')
            await app.workers.wait_for_complete()
            repo.set_operator_notes('K9XYZ', 'private note')
            await pilot.press('ctrl+x', 'y', 'ctrl+e')
            await pilot.pause()
            assert not repo.get_net(net_id).is_open
            before = asdict(repo.list_checkins(net_id)[0].checkin)
        assert len(list((tmp_path / 'exports').rglob('*.adi'))) == 1
        assert len(list((tmp_path / 'exports').rglob('*.txt'))) == 1
    snapshot = backup.backup(db_path, tmp_path / 'snapshots')
    target = tmp_path / 'recovered.db'
    backup.restore(snapshot, target)
    with closing(db.connect(target)) as conn:
        recovered = Repo(conn)
        assert asdict(recovered.list_checkins(net_id)[0].checkin) == before
        assert recovered.get_operator('K9XYZ').operator_notes == 'private note'
        assert recovered.get_net(net_id).notes == 'Opening notes'
    assert cli.main(['--config', str(cfg_path), '--db', str(target), 'doctor']) == 0


def test_failed_removal_rolls_back_deleted_row_and_order(repo):
    net = session(repo)
    first = add(repo, net, 'W1AW')
    add(repo, net, 'K9XYZ')
    before = [asdict(r.checkin) for r in repo.list_checkins(net.id)]
    repo.conn.execute("CREATE TRIGGER reject_shift BEFORE UPDATE OF seq ON checkins BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_checkin(first.id)
    assert [asdict(r.checkin) for r in repo.list_checkins(net.id)] == before


def test_multiple_removals_restore_in_reverse_order(repo):
    net = session(repo)
    originals = [add(repo, net, call) for call in ('W1AW', 'K9XYZ', 'K1ABC')]
    snapshots = [repo.delete_checkin(originals[1].id), repo.delete_checkin(originals[2].id)]
    repo.restore_checkin(snapshots.pop())
    repo.restore_checkin(snapshots.pop())
    assert [r.checkin for r in repo.list_checkins(net.id)] == originals
