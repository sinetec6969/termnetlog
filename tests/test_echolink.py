import sqlite3

from termnetlog import config, db, entry, export
from termnetlog.repo import Repo
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import flag_cell


def test_upgrade_preserves_existing_checkins(tmp_path):
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript('\n'.join(db.MIGRATIONS[:2]) + '\nPRAGMA user_version = 2;')
    conn.execute("INSERT INTO operators (callsign, created_at) VALUES ('W1AW', '2026-01-01T00:00:00Z')")
    conn.execute("INSERT INTO nets (name, started_utc) VALUES ('Test', '2026-01-01T00:00:00Z')")
    conn.execute("INSERT INTO checkins (net_id, callsign, logged_as, seq, time_utc, mobile, notes) VALUES (1, 'W1AW', 'W1AW/M', 1, '2026-01-01T00:00:00Z', 1, 'keep')")
    conn.commit()
    conn.close()
    conn = db.connect(path)
    try:
        ci = Repo(conn).get_checkin(1)
        assert ci.echolink == 0
        assert ci.mobile == 1 and ci.notes == 'keep'
        db.migrate(conn)
        assert Repo(conn).get_checkin(1) == ci
    finally:
        conn.close()


async def test_echolink_entry_toggle_export_and_undo(repo, tmp_path):
    net = repo.create_net('Test', '146.520', 'FM', '2m', 'W1AW', 'ncs')
    ci = repo.record_entry(net.id, entry.parse('K9XYZ E m t via W1AW test note'))
    assert ci.echolink == ci.mobile == ci.has_traffic == 1
    assert ci.notes == 'test note' and ci.relayed_by == 'W1AW'
    rows = repo.list_checkins(net.id)
    assert 'E ' in flag_cell(rows[0]).plain
    assert 'EchoLink' in export.to_text(net, rows)
    assert 'EchoLink' in export.to_adif(net, rows)
    snapshot = repo.delete_checkin(ci.id)
    assert repo.restore_checkin(snapshot) == ci
    app = NetLogApp(config.Config(offline=True), repo, export_dir=tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_net(net.id)
        await pilot.pause()
        await pilot.press('escape', 'e')
        assert repo.get_checkin(ci.id).echolink == 0
        await pilot.press('e')
        assert repo.get_checkin(ci.id).echolink == 1
