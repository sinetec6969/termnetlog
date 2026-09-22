import sqlite3

import pytest

from termnetlog import db, entry
from termnetlog.config import Config
from termnetlog.lookup.service import LookupService
from termnetlog.models import FLAGS
from termnetlog.repo import DuplicateCheckIn, Repo
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CallInput

from conftest import FakeProvider


def net(repo):
    return repo.create_net('Test', '146.520', 'FM', '2m', 'W1AW', 'ncs')


def test_complete_entry_is_saved_in_one_operation(repo):
    session = net(repo)
    parsed = entry.parse('w1aw/m t s c r p via k9xyz testing complete save')
    ci = repo.record_entry(session.id, parsed)
    assert all(getattr(ci, flag) == 1 for flag in FLAGS)
    assert ci.notes == 'testing complete save' and ci.relayed_by == 'K9XYZ'
    assert ci.logged_as == 'W1AW/M' and ci.seq == 1
    assert repo.get_operator('W1AW') is not None
    assert not repo.conn.in_transaction


def test_failure_after_insert_rolls_back_new_operator_and_entry(repo, monkeypatch):
    session = net(repo)
    original = repo.get_checkin
    def fail(checkin_id):
        assert original(checkin_id).notes == 'keep this note'
        raise sqlite3.OperationalError('injected read failure after insert')
    monkeypatch.setattr(repo, 'get_checkin', fail)
    with pytest.raises(sqlite3.OperationalError):
        repo.record_entry(session.id, entry.parse('w1aw t r keep this note'))
    assert repo.get_operator('W1AW') is None
    assert repo.list_checkins(session.id) == []
    assert not repo.conn.in_transaction
    monkeypatch.setattr(repo, 'get_checkin', original)
    ci = repo.record_entry(session.id, entry.parse('w1aw t r keep this note'))
    assert ci.seq == 1 and ci.notes == 'keep this note'


def test_failure_preserves_existing_operator_and_notes(repo):
    session = net(repo)
    repo.update_operator('W1AW', name='My Name')
    repo.set_operator_notes('W1AW', 'Permanent notes')
    repo.conn.execute("""CREATE TRIGGER reject_entry AFTER INSERT ON checkins
                         BEGIN SELECT RAISE(ABORT, 'injected storage error'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_entry(session.id, entry.parse('w1aw t new entry'))
    assert repo.list_checkins(session.id) == []
    op = repo.get_operator('W1AW')
    assert op.name == 'My Name' and op.operator_notes == 'Permanent notes'
    assert op.lookup_source == 'manual'


def test_duplicate_does_not_modify_existing_entry(repo):
    session = net(repo)
    original = repo.record_entry(session.id, entry.parse('w1aw t original note'))
    with pytest.raises(DuplicateCheckIn) as caught:
        repo.record_entry(session.id, entry.parse('w1aw/m r via k9xyz replacement'))
    assert caught.value.existing.id == original.id
    assert repo.get_checkin(original.id) == original
    assert not repo.conn.in_transaction


def test_entry_save_does_not_commit_outer_transaction(repo):
    session = net(repo)
    repo.conn.execute('BEGIN')
    repo.conn.execute("UPDATE nets SET notes = 'outer change' WHERE id = ?", (session.id,))
    repo.record_entry(session.id, entry.parse('w1aw t nested entry'))
    assert repo.conn.in_transaction
    repo.conn.rollback()
    assert repo.get_net(session.id).notes == ''
    assert repo.get_operator('W1AW') is None
    assert repo.list_checkins(session.id) == []


def test_failed_entry_does_not_rollback_outer_changes(repo):
    session = net(repo)
    repo.conn.execute('BEGIN')
    repo.conn.execute("UPDATE nets SET notes = 'outer change' WHERE id = ?", (session.id,))
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_entry(99999, entry.parse('w1aw t missing net'))
    assert repo.get_net(session.id).notes == 'outer change'
    assert repo.get_operator('W1AW') is None
    assert repo.conn.in_transaction
    repo.conn.rollback()


def test_commit_failure_rolls_back_complete_entry():
    class FailRelease(sqlite3.Connection):
        fail = False

        def execute(self, sql, *args):
            if self.fail and sql == 'RELEASE SAVEPOINT record_entry':
                self.fail = False
                raise sqlite3.OperationalError('injected commit failure')
            return super().execute(sql, *args)

    conn = sqlite3.connect(':memory:', factory=FailRelease)
    conn.row_factory = sqlite3.Row
    db.migrate(conn)
    repo = Repo(conn)
    session = net(repo)
    conn.fail = True
    try:
        with pytest.raises(sqlite3.OperationalError):
            repo.record_entry(session.id, entry.parse('w1aw t failed commit'))
        assert repo.get_operator('W1AW') is None
        assert repo.list_checkins(session.id) == []
        assert not conn.in_transaction
    finally:
        conn.close()


async def test_failed_save_retains_input_and_can_be_retried(repo, tmp_path, monkeypatch):
    session = net(repo)
    provider = FakeProvider()
    app = NetLogApp(Config(), repo, LookupService(repo, [provider]), export_dir=tmp_path)
    notices = []
    monkeypatch.setattr(app, 'notify', lambda message, **kw: notices.append((str(message), kw)))
    original = repo.record_entry
    def fail(*args):
        raise sqlite3.OperationalError('database locked')
    monkeypatch.setattr(repo, 'record_entry', fail)
    async with app.run_test(size=(140, 40)) as pilot:
        app.open_net(session.id)
        await pilot.pause()
        box = app.screen.query_one(CallInput)
        text = 'w1aw/m t r via k9xyz keep this entry'
        box.value = text
        await pilot.press('enter')
        await pilot.pause()
        assert box.value == text and repo.list_checkins(session.id) == []
        assert provider.calls == []
        assert any(kw.get('title') == 'Save failed' for _, kw in notices)
        monkeypatch.setattr(repo, 'record_entry', original)
        await pilot.press('enter')
        await app.workers.wait_for_complete()
        ci = repo.list_checkins(session.id)[0].checkin
        assert ci.mobile and ci.has_traffic and ci.ragchew
        assert ci.notes == 'keep this entry' and ci.relayed_by == 'K9XYZ'
        assert box.value == '' and provider.calls == ['W1AW']
