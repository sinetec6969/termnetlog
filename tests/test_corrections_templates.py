from dataclasses import asdict
import sqlite3

import pytest
from textual.widgets import Input, OptionList

from termnetlog import callsign, config, entry, setup
from termnetlog.repo import DuplicateCheckIn
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CallInput, CheckinTable


def net(repo):
    return repo.create_net('Test', '146.520', 'FM', '2m', 'W1AW', 'ncs')


def test_correction_preserves_checkin_and_unrelated_history(repo):
    first, second = net(repo), net(repo)
    old = repo.record_entry(first.id, entry.parse('W1AW/m t r via K9XYZ entry note'))
    other = repo.add_checkin(second.id, callsign.parse('W1AW'))
    repo.set_operator_notes('W1AW', 'original private notes')
    repo.ensure_operator('K1ABC')
    repo.set_operator_notes('K1ABC', 'destination private notes')
    before = asdict(old)
    corrected = repo.correct_callsign(old.id, callsign.parse('K1ABC/P'))
    expected = dict(before, callsign='K1ABC', logged_as='K1ABC/P')
    assert asdict(corrected) == expected
    assert repo.get_checkin(other.id).callsign == 'W1AW'
    assert repo.get_operator('W1AW').operator_notes == 'original private notes'
    assert repo.get_operator('K1ABC').operator_notes == 'destination private notes'
    assert len(repo.operator_history('W1AW')) == 1
    assert len(repo.operator_history('K1ABC')) == 1


def test_duplicate_correction_leaves_both_records(repo):
    session = net(repo)
    first = repo.add_checkin(session.id, callsign.parse('W1AW'))
    second = repo.add_checkin(session.id, callsign.parse('K9XYZ'))
    with pytest.raises(DuplicateCheckIn):
        repo.correct_callsign(first.id, callsign.parse('K9XYZ/M'))
    assert repo.get_checkin(first.id) == first
    assert repo.get_checkin(second.id) == second


def test_correction_failure_rolls_back_new_operator(repo):
    first = repo.add_checkin(net(repo).id, callsign.parse('W1AW'))
    repo.conn.execute("CREATE TRIGGER reject_correction BEFORE UPDATE ON checkins BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.correct_callsign(first.id, callsign.parse('K1ABC'))
    assert repo.get_operator('K1ABC') is None
    assert repo.get_checkin(first.id) == first


def test_correction_preserves_outer_transaction(repo):
    first = repo.add_checkin(net(repo).id, callsign.parse('W1AW'))
    repo.conn.execute('BEGIN')
    repo.correct_callsign(first.id, callsign.parse('K1ABC'))
    assert repo.conn.in_transaction
    repo.conn.rollback()
    assert repo.get_checkin(first.id) == first
    assert repo.get_operator('K1ABC') is None


def test_named_templates_preserve_defaults_and_quotes(tmp_path):
    path = tmp_path / 'config.toml'
    setup.edit(path, [['net.name', 'Default'], ['net.notes', 'Opening notes']])
    setup.edit(path, [['net.name', 'Tuesday'], ['net.frequency', '147.000']], template='Club "A"')
    setup.edit(path, [['net.role', 'participant']], template='Other')
    setup.edit(path, [['net.ncs_callsign', 'W1AW']], template='Club "A"')
    cfg = config.load(path)
    assert cfg.net.name == 'Default'
    assert cfg.templates['Club "A"'].name == 'Tuesday'
    assert cfg.templates['Club "A"'].notes == 'Opening notes'
    assert cfg.templates['Other'].role == 'participant'
    assert cfg.templates['Club "A"'].ncs_callsign == 'W1AW'


@pytest.mark.parametrize('changes,name', [([['lookup.offline', 'true']], 'Club'), ([['net.role', 'bad']], 'Club'), ([], ' ')])
def test_invalid_template_does_not_modify_file(tmp_path, changes, name):
    path = tmp_path / 'config.toml'
    path.write_text(config.DEFAULT_CONFIG)
    with pytest.raises(config.ConfigError):
        setup.edit(path, changes, template=name)
    assert path.read_text() == config.DEFAULT_CONFIG


async def test_template_start_is_fresh_with_notes(repo, tmp_path):
    defaults = config.NetDefaults(name='Weekly', ncs_callsign='W1AW', notes='Opening script')
    app = NetLogApp(config.Config(templates={'Club': defaults}), repo, LookupService(repo, []), export_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        menu = app.screen.query_one(OptionList)
        menu.highlighted = 1  # new net, then first template
        await pilot.press('enter', 'ctrl+s')
        await pilot.pause()
        first = app.screen.net
        assert first.name == 'Weekly' and first.notes == 'Opening script'
        repo.add_checkin(first.id, callsign.parse('W1AW'))
        await pilot.press('ctrl+b')
        app.screen.start_with_defaults(defaults)
        await pilot.press('ctrl+s')
        assert app.screen.net_id != first.id
        assert repo.list_checkins(app.screen.net_id) == []


async def test_tui_correction_reopen_and_metadata(repo, tmp_path):
    session = net(repo)
    checkin = repo.record_entry(session.id, entry.parse('W1AW t original note'))
    repo.end_net(session.id)
    app = NetLogApp(config.Config(), repo, LookupService(repo, []), export_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_net(session.id)
        await pilot.pause()
        screen = app.screen
        screen.query_one(CallInput).value = 'K9XYZ'
        await pilot.press('enter')
        assert len(repo.list_checkins(session.id)) == 1
        assert screen.query_one(CallInput).value == 'K9XYZ'
        await pilot.press('f3')
        app.screen.query_one(Input).value = 'K1ABC'
        await pilot.press('enter', 'y')
        await pilot.pause()
        assert repo.get_checkin(checkin.id).callsign == 'K1ABC'
        assert repo.get_checkin(checkin.id).notes == 'original note'
        await pilot.press('ctrl+d')
        app.screen.query_one('#name', Input).value = 'Corrected net name'
        await pilot.press('ctrl+s')
        assert repo.get_net(session.id).name == 'Corrected net name'
        assert not repo.get_net(session.id).is_open
        await pilot.press('ctrl+o', 'y')
        assert repo.get_net(session.id).is_open
        screen.query_one(CallInput).focus()
        await pilot.press('enter')
        assert len(repo.list_checkins(session.id)) == 2


def test_failure_after_identity_update_rolls_back(repo, monkeypatch):
    first = repo.add_checkin(net(repo).id, callsign.parse('W1AW'))
    original = repo.get_checkin
    calls = 0
    def fail_second(checkin_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError('injected after update')
        return original(checkin_id)
    monkeypatch.setattr(repo, 'get_checkin', fail_second)
    with pytest.raises(sqlite3.OperationalError):
        repo.correct_callsign(first.id, callsign.parse('K1ABC'))
    assert original(first.id) == first
    assert repo.get_operator('K1ABC') is None


async def test_correction_cancel_and_duplicate_preview_leave_records(repo, tmp_path):
    session = net(repo)
    first = repo.add_checkin(session.id, callsign.parse('W1AW'))
    repo.add_checkin(session.id, callsign.parse('K9XYZ'))
    app = NetLogApp(config.Config(), repo, LookupService(repo, []), export_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_net(session.id)
        await pilot.pause()
        screen = app.screen
        screen.query_one(CheckinTable).select_id(first.id)
        await pilot.press('f3')
        app.screen.query_one(Input).value = 'K1ABC'
        await pilot.press('enter', 'n')
        assert repo.get_checkin(first.id) == first
        assert repo.get_operator('K1ABC') is None
        await pilot.press('f3')
        app.screen.query_one(Input).value = 'K9XYZ'
        await pilot.press('enter')
        assert app.screen is screen
        assert repo.get_checkin(first.id) == first


def test_cli_rejects_empty_template_name_without_creating_config(tmp_path):
    from termnetlog import cli
    path = tmp_path / 'config.toml'
    assert cli.main(['--config', str(path), 'config', '--template', '']) == 2
    assert not path.exists()
