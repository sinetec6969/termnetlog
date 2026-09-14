import pytest

from termnetlog import callsign, db
from termnetlog.lookup.base import LookupResult
from termnetlog.repo import DuplicateCheckIn


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
