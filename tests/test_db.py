import pytest
import sqlite3

from termnetlog import callsign, db
from termnetlog.lookup.base import LookupResult
from termnetlog.repo import DuplicateCheckIn


def test_upgrade_v1_keeps_operator_data(tmp_path):
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript(db.MIGRATIONS[0] + '\nPRAGMA user_version = 1;')
    conn.execute("INSERT INTO operators (callsign, name, operator_notes, created_at) VALUES (?, ?, ?, ?)",
                 ('W1AW', 'Known Name', 'Keep my notes', '2020-01-01T00:00:00Z'))
    conn.commit()
    conn.close()
    conn = db.connect(path)
    try:
        row = conn.execute('SELECT * FROM operators').fetchone()
        assert (row['name'], row['operator_notes']) == ('Known Name', 'Keep my notes')
        assert conn.execute('SELECT COUNT(*) FROM lookup_attempts').fetchone()[0] == 0
        assert conn.execute('PRAGMA user_version').fetchone()[0] == len(db.MIGRATIONS)
    finally:
        conn.close()


def test_future_database_schema_is_rejected(repo):
    repo.conn.execute('PRAGMA user_version = 999')
    with pytest.raises(ValueError, match='requires a newer'):
        db.migrate(repo.conn)


def test_failed_migration_preserves_schema_version_and_data(repo, monkeypatch):
    repo.update_operator('W1AW', name='Existing operator')
    previous = repo.conn.execute('PRAGMA user_version').fetchone()[0]
    monkeypatch.setattr(db, 'MIGRATIONS', db.MIGRATIONS + [
        'CREATE TABLE migration_probe (id INTEGER); INSERT INTO nonexistent_table VALUES (1);'
    ])
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(repo.conn)
    assert repo.conn.execute('PRAGMA user_version').fetchone()[0] == previous
    assert repo.conn.execute("SELECT name FROM sqlite_master WHERE name = 'migration_probe'").fetchone() is None
    assert repo.get_operator('W1AW').name == 'Existing operator'
    assert not repo.conn.in_transaction


def test_history_uses_id_to_break_timestamp_ties(repo):
    first, second = make_net(repo), make_net(repo)
    a = repo.add_checkin(first.id, callsign.parse('W1AW'))
    b = repo.add_checkin(second.id, callsign.parse('W1AW'))
    repo.conn.execute("UPDATE checkins SET time_utc = '2026-09-22T01:00:00Z'")
    repo.conn.commit()
    first_row = repo.list_checkins(first.id)[0]
    second_row = repo.list_checkins(second.id)[0]
    assert first_row.nth == 1 and first_row.prev_seen is None
    assert second_row.nth == 2 and second_row.prev_seen == '2026-09-22T01:00:00Z'
    assert not second_row.is_new
    assert [ci.id for ci, _ in repo.operator_history('W1AW')] == [b.id, a.id]


def make_net(repo, **kw):
    args = dict(name="Test Net", frequency="146.520", mode="FM", band="2m", ncs_callsign="kx9abc", my_role="ncs")
    args.update(kw)
    return repo.create_net(**args)


def test_migrations_idempotent(tmp_path):
    path = tmp_path / "x.db"
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    conn.close()
    conn = db.connect(path)  # re-open runs no migrations
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_checkin_flow(repo):
    net = make_net(repo)
    assert net.ncs_callsign == "KX9ABC"
    a = repo.add_checkin(net.id, callsign.parse("w1aw"))
    b = repo.add_checkin(net.id, callsign.parse("k9xyz/m"))
    assert (a.seq, b.seq) == (1, 2)
    assert b.mobile == 1 and b.logged_as == "K9XYZ/M" and b.callsign == "K9XYZ"

    with pytest.raises(DuplicateCheckIn):
        repo.add_checkin(net.id, callsign.parse("K9XYZ"))

    repo.toggle_flag(a.id, "ragchew")
    repo.set_flag(a.id, "has_traffic")
    repo.set_checkin_notes(a.id, "new antenna")
    rows = repo.list_checkins(net.id)
    assert [r.checkin.callsign for r in rows] == ["W1AW", "K9XYZ"]
    assert rows[0].checkin.ragchew == 1 and rows[0].checkin.has_traffic == 1
    assert rows[0].checkin.notes == "new antenna"
    assert all(r.is_new for r in rows)

    repo.move_checkin(b.id, -1)
    assert [r.checkin.callsign for r in repo.list_checkins(net.id)] == ["K9XYZ", "W1AW"]

    repo.delete_checkin(b.id)
    rows = repo.list_checkins(net.id)
    assert [(r.checkin.callsign, r.checkin.seq) for r in rows] == [("W1AW", 1)]


def test_history_across_nets(repo):
    n1 = make_net(repo)
    repo.add_checkin(n1.id, callsign.parse("W1AW"))
    repo.end_net(n1.id)
    # Force distinct timestamps.
    repo.conn.execute("UPDATE checkins SET time_utc = '2026-09-01T01:00:00Z'")
    repo.conn.commit()

    n2 = make_net(repo)
    repo.add_checkin(n2.id, callsign.parse("W1AW"))
    repo.add_checkin(n2.id, callsign.parse("N0NEW"))
    rows = {r.checkin.callsign: r for r in repo.list_checkins(n2.id)}
    assert rows["W1AW"].nth == 2
    assert rows["W1AW"].prev_seen == "2026-09-01T01:00:00Z"
    assert not rows["W1AW"].is_new
    assert rows["N0NEW"].is_new

    assert repo.open_nets()[0].id == n2.id
    summary = repo.operator_summary("W1AW")
    assert summary.checkin_count == 2
    assert len(repo.operator_history("W1AW")) == 2
    assert [s.operator.callsign for s in repo.suggest_callsigns("w1")] == ["W1AW"]


def test_manual_edits_not_overwritten(repo):
    repo.apply_lookup(LookupResult(callsign="W1AW", source="hamdb", name="Arrl Hq", city="Newington", state="CT"))
    assert repo.get_operator("W1AW").city == "Newington"
    repo.update_operator("W1AW", name="Hiram Maxim", nickname="Hiram")
    repo.apply_lookup(LookupResult(callsign="W1AW", source="qrz", name="Someone Else"))
    op = repo.get_operator("W1AW")
    assert op.name == "Hiram Maxim" and op.lookup_source == "manual"

    repo.set_operator_notes("W1AW", "runs the Tuesday net")
    assert repo.search_operators("tuesday")[0].operator.callsign == "W1AW"


def test_delete_net_cascades(repo):
    net = make_net(repo)
    repo.add_checkin(net.id, callsign.parse("W1AW"))
    repo.delete_net(net.id)
    assert repo.conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] == 0
    assert repo.get_operator("W1AW") is not None  # operator DB survives
