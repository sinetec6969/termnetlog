import pytest
from textual.widgets import Input, Static

from termnetlog import adif, callsign, config, entry, export
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CallInput, CheckinTable
from conftest import FakeProvider


def net(repo):
    return repo.create_net('Test', '146.520', 'FM', '2m', 'W1AW', 'ncs')


@pytest.mark.parametrize('text, base', [
    ('w1a?', 'W1A?'),
    ('k?xyz', 'K?XYZ'),
    ('W?A?', 'W?A?'),
    ('w1a?/m', 'W1A?'),
])
def test_placeholder_parses_only_when_allowed(text, base):
    assert callsign.parse(text) is None
    parsed = callsign.parse(text, allow_unknown=True)
    assert parsed is not None and parsed.base == base


@pytest.mark.parametrize('text', ['?', '??', 'W???????', 'W1?AWXYZ', '1?'])
def test_placeholder_needs_a_possible_callsign(text):
    assert callsign.parse(text, allow_unknown=True) is None


def test_entry_line_accepts_placeholder():
    parsed = entry.parse('w1a? t weak')
    assert parsed.call.base == 'W1A?' and parsed.flags == {'has_traffic'} and parsed.note == 'weak'


def test_placeholder_suggests_known_calls_and_is_not_new(repo):
    session = net(repo)
    repo.add_checkin(session.id, callsign.parse('W1AW'))
    repo.add_checkin(session.id, callsign.parse('W1AX'))
    repo.add_checkin(session.id, callsign.parse('W2AW'))
    ci = repo.record_entry(session.id, entry.parse('W1A?'))
    assert [s.operator.callsign for s in repo.suggest_callsigns('W1A?')] == ['W1AW', 'W1AX']
    assert [s.operator.callsign for s in repo.suggest_callsigns('W?AW')] == ['W1AW', 'W2AW']
    assert all('?' not in s.operator.callsign for s in repo.search_operators(''))
    row = next(r for r in repo.list_checkins(session.id) if r.checkin.id == ci.id)
    assert row.checkin.incomplete and not row.is_new


def test_correcting_placeholder_drops_empty_profile_and_undo_still_works(repo):
    first, second = net(repo), net(repo)
    removed = repo.delete_checkin(repo.record_entry(first.id, entry.parse('W1A?')).id)
    ci = repo.record_entry(second.id, entry.parse('W1A? r note'))
    corrected = repo.correct_callsign(ci.id, callsign.parse('W1AW'))
    assert (corrected.callsign, corrected.ragchew, corrected.notes) == ('W1AW', 1, 'note')
    assert repo.get_operator('W1A?') is None
    restored = repo.restore_checkin(removed)
    assert restored.callsign == 'W1A?'


def test_correction_keeps_placeholder_profile_with_notes(repo):
    ci = repo.record_entry(net(repo).id, entry.parse('W1A?'))
    repo.set_operator_notes('W1A?', 'sounded like Bob')
    repo.correct_callsign(ci.id, callsign.parse('W1AW'))
    assert repo.get_operator('W1A?').operator_notes == 'sounded like Bob'


def test_adif_export_names_incomplete_checkin(repo):
    session = net(repo)
    repo.add_checkin(session.id, callsign.parse('W1AW'))
    repo.record_entry(session.id, entry.parse('K?XYZ'))
    rows = repo.list_checkins(session.id)
    with pytest.raises(adif.ExportValidationError, match=r'#2 K\?XYZ: fill in the missing'):
        export.to_adif(session, rows)
    assert 'K?XYZ' in export.to_text(session, rows)


def test_adif_export_names_every_incomplete_checkin(repo):
    session = net(repo)
    repo.record_entry(session.id, entry.parse('K?XYZ'))
    repo.record_entry(session.id, entry.parse('W1A?'))
    with pytest.raises(adif.ExportValidationError, match=r'#1 K\?XYZ, #2 W1A\?: fill in'):
        export.to_adif(session, repo.list_checkins(session.id))


def test_operator_count_skips_placeholders(repo):
    session = net(repo)
    repo.add_checkin(session.id, callsign.parse('W1AW'))
    repo.record_entry(session.id, entry.parse('W1A?'))
    assert repo.counts()[1] == 1


async def test_tui_logs_placeholder_without_lookup_and_fixes_with_f3(repo, tmp_path):
    session = net(repo)
    provider = FakeProvider()
    app = NetLogApp(config.Config(), repo, LookupService(repo, [provider]), export_dir=tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app.open_net(session.id)
        await pilot.pause()
        screen = app.screen
        screen.query_one(CallInput).value = 'w1a? t'
        await pilot.press('enter')
        await pilot.pause()
        ci = repo.list_checkins(session.id)[0].checkin
        assert ci.logged_as == 'W1A?' and ci.has_traffic
        assert 'W1A?' not in provider.calls
        assert '1 incomplete' in str(screen.query_one('#net-header', Static).render())
        screen.query_one(CheckinTable).focus()
        await pilot.press('f3')
        app.screen.query_one(Input).value = 'W1AW'
        await pilot.press('enter', 'y')
        await pilot.pause()
        assert repo.get_checkin(ci.id).logged_as == 'W1AW'
        assert 'incomplete' not in str(screen.query_one('#net-header', Static).render())
