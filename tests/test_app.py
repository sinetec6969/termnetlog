from termnetlog.config import Config
from termnetlog.lookup.base import LookupResult
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.screens.net import NetScreen
from termnetlog.tui.widgets.checkin_table import CheckinTable

from conftest import FakeProvider


def make_app(repo, tmp_path):
    provider = FakeProvider(
        {"W1AW": LookupResult("W1AW", "fake", first_name="Hiram", name="Hiram Maxim", city="Newington", state="CT")}
    )
    cfg = Config(my_callsign="N0ME", db_path=tmp_path / "test.db")
    cfg.net.ncs_callsign = "KX9ABC"
    app = NetLogApp(cfg, repo, LookupService(repo, [provider]), export_dir=tmp_path / "exports")
    return app, provider


async def type_text(pilot, text):
    for ch in text:
        await pilot.press("space" if ch == " " else ch)


async def test_log_a_net(repo, tmp_path):
    app, provider = make_app(repo, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("n")  # new net modal
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, NetScreen)
        net_id = app.screen.net_id

        await type_text(pilot, "w1aw t")
        await pilot.press("enter")
        await type_text(pilot, "k9xyz/m via w1aw weak")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        rows = repo.list_checkins(net_id)
        assert [r.checkin.logged_as for r in rows] == ["W1AW", "K9XYZ/M"]
        assert rows[0].checkin.has_traffic == 1
        assert rows[0].operator.name == "Hiram Maxim"  # looked up in background
        assert rows[1].checkin.relayed_by == "W1AW" and rows[1].checkin.notes == "weak"
        assert provider.calls == ["W1AW", "K9XYZ"]

        # Duplicate is refused.
        await type_text(pilot, "w1aw")
        await pilot.press("enter")
        await pilot.pause()
        assert len(repo.list_checkins(net_id)) == 2

        # Select W1AW in the list, mark ragchew, add a note.
        await pilot.press("escape")
        table = app.screen.query_one(CheckinTable)
        assert table.has_focus
        table.select_id(rows[0].checkin.id)
        await pilot.press("r")
        await pilot.press("enter")
        await pilot.pause()
        await type_text(pilot, "new beam")
        await pilot.press("ctrl+s")
        await pilot.pause()

        # Typing a callsign char in the list jumps back to the entry box.
        await pilot.press("w")
        await pilot.pause()
        assert app.screen.query_one("#call-input").value == "w"

        await pilot.press("ctrl+x")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        await pilot.press("ctrl+e")
        await pilot.pause()

    w1aw = repo.list_checkins(net_id)[0].checkin
    assert w1aw.ragchew == 1 and w1aw.notes == "new beam"
    assert not repo.get_net(net_id).is_open
    exports = sorted(p.suffix for p in (tmp_path / "exports").iterdir())
    assert exports == [".adi", ".txt"]


async def test_history_and_operator_screens(repo, tmp_path):
    from termnetlog import callsign
    from termnetlog.tui.screens.history import HistoryScreen
    from termnetlog.tui.screens.operators import OperatorsScreen

    net = repo.create_net("Nightly 2m Net", "146.520", "FM", "2m", "KX9ABC", "participant")
    repo.add_checkin(net.id, callsign.parse("W1AW"))
    repo.end_net(net.id)
    app, _ = make_app(repo, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("h")
        await pilot.pause()
        assert isinstance(app.screen, HistoryScreen)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, NetScreen) and app.screen.net_id == net.id
        # Participant mode hides the recognized flag; ended nets can't be ended again.
        assert app.screen.check_action("toggle_flag", ("recognized",)) is False
        assert app.screen.check_action("end_net", ()) is False
        await pilot.press("ctrl+b")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, OperatorsScreen)
        await pilot.press("slash")
        await type_text(pilot, "w1")
        await pilot.pause()
        assert [s.operator.callsign for s in app.screen.summaries] == ["W1AW"]


async def test_toggle_utc_local(repo, tmp_path):
    from termnetlog import callsign
    from termnetlog.tui import format as fmt

    net = repo.create_net("Nightly 2m Net", "146.520", "FM", "2m", "KX9ABC", "ncs")
    ci = repo.add_checkin(net.id, callsign.parse("W1AW"))
    repo.conn.execute("UPDATE checkins SET time_utc = '2026-09-13T01:30:00Z' WHERE id = ?", (ci.id,))
    app, _ = make_app(repo, tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        app.open_net(net.id)
        await pilot.pause()
        table = app.screen.query_one(CheckinTable)
        assert str(table.columns["time"].label) == "UTC"
        assert table.get_cell(str(ci.id), "time") == "0130"

        await pilot.press("ctrl+t")
        await pilot.pause()
        assert str(table.columns["time"].label) in ("EDT", "EST")  # heading follows today's offset
        assert table.get_cell(str(ci.id), "time") == "2130"  # previous evening, UTC-4
        assert fmt.date("2026-09-13T01:30:00Z") == "2026-09-12"
        assert fmt.zone("2026-01-13T01:30:00Z") == "EST"

        await pilot.press("ctrl+t")
        await pilot.pause()
        assert table.get_cell(str(ci.id), "time") == "0130"
