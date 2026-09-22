import pytest
from textual.widgets import DataTable, Input, Static

from termnetlog import callsign
from termnetlog.config import Config
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.widgets.checkin_table import CheckinTable, CallInput


def net(repo, name='Nightly'):
    return repo.create_net(name, '146.520', 'FM', '2m', 'W1AW', 'ncs')


def app_for(repo, tmp_path):
    return NetLogApp(Config(), repo, LookupService(repo, []), export_dir=tmp_path)


def test_history_queries_are_bounded_literal_and_stable(repo):
    ids = [net(repo, '100%_Net' if i == 0 else 'Nightly').id for i in range(205)]
    repo.conn.execute("UPDATE nets SET started_utc='2026-01-01T00:00:00Z'")
    repo.conn.commit()
    assert repo.count_nets() == 205
    assert [n.id for n, _ in repo.list_nets(5, offset=200)] == list(reversed(ids[:5]))
    assert repo.count_nets('%_') == 1
    assert repo.count_nets('nightly') == 204
    assert repo.count_nets('2026-01-01') == 205
    assert repo.count_nets("' OR 1=1 --") == 0


async def test_history_reaches_oldest_searches_and_opens(repo, tmp_path):
    oldest = net(repo, 'Oldest special')
    for _ in range(204):
        repo.end_net(net(repo).id)
    app = app_for(repo, tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press('h')
        screen = app.screen
        table = screen.query_one(DataTable)
        assert table.row_count == 50 and screen.total == 205
        for _ in range(4):
            await pilot.press('ctrl+n')
        assert table.row_count == 5
        table.move_cursor(row=4)
        await pilot.pause()
        assert screen.selected_net_id() == oldest.id
        screen.reload()
        assert screen.selected_net_id() == oldest.id
        await pilot.press('slash')
        screen.query_one(Input).value = 'special'
        await pilot.pause()
        assert table.row_count == 1 and screen.page == 0
        await pilot.press('enter')  # search -> list
        await pilot.press('enter')  # list -> selected net
        assert app.screen.net_id == oldest.id


async def test_history_empty_results_and_last_page_deletion(repo, tmp_path):
    for _ in range(51):
        net(repo)
    app = app_for(repo, tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press('h', 'ctrl+n')
        screen = app.screen
        repo.delete_net(screen.selected_net_id())
        screen.reload()
        assert screen.page == 0 and screen.total == 50
        screen.query_one(Input).value = 'no such net'
        await pilot.pause()
        assert screen.query_one(DataTable).row_count == 0
        assert screen.selected_net_id() is None
        assert 'No matching nets' in str(screen.query_one('#history-page', Static).render())


@pytest.mark.parametrize('size', [(80, 24), (100, 30), (140, 40)])
async def test_roster_access_and_resize_preserve_entry_selection(repo, tmp_path, size):
    session = net(repo)
    ci = repo.add_checkin(session.id, callsign.parse('W1AW'))
    repo.update_operator('W1AW', name='A very long operator name', city='A very long city')
    app = app_for(repo, tmp_path)
    async with app.run_test(size=size) as pilot:
        app.open_net(session.id)
        await pilot.pause()
        screen = app.screen
        table = screen.query_one(CheckinTable)
        entry = screen.query_one(CallInput)
        entry.value = 'K9XYZ t unfinished'
        assert table.virtual_size.width <= table.size.width or table.styles.overflow_x == 'auto'
        assert table.compact == (size[0] < 120)
        assert screen.query_one('#card').display == (size[0] >= 120)
        if size[0] < 120:
            assert table.virtual_size.width <= table.size.width
            await pilot.press('f2')
            assert screen.query_one('#card').display
            assert not screen.query_one('#left').display
            await pilot.press('f2')
        await pilot.resize_terminal(140, 40)
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert entry.value == 'K9XYZ t unfinished'
        assert table.selected_id() == ci.id
        assert table.compact and 'location' not in table.columns
        await pilot.press('escape', 't')
        assert repo.get_checkin(ci.id).has_traffic == 1


async def test_operator_dialog_scrolls_to_last_field_at_80x24(repo, tmp_path):
    session = net(repo)
    repo.add_checkin(session.id, callsign.parse('W1AW'))
    app = app_for(repo, tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        app.open_net(session.id)
        await pilot.pause()
        await pilot.press('escape', 'e')
        for _ in range(8):
            await pilot.press('tab')
        await pilot.pause()
        field = app.screen.query_one('#license_class', Input)
        assert field.has_focus
        assert app.screen.query_one('.dialog').scroll_y > 0
        assert 0 <= field.region.y < 24
        field.value = 'Extra'
        await pilot.press('ctrl+s')
        assert repo.get_operator('W1AW').license_class == 'Extra'


async def test_roster_refresh_updates_cells_and_reorders_without_stale_rows(repo, tmp_path):
    first_net = net(repo)
    first = repo.add_checkin(first_net.id, callsign.parse('W1AW'))
    app = app_for(repo, tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        app.open_net(first_net.id)
        await pilot.pause()
        table = app.screen.query_one(CheckinTable)
        second = repo.add_checkin(first_net.id, callsign.parse('K9XYZ'))
        app.screen.refresh_all(select_id=second.id)
        assert table.row_count == 2
        repo.update_operator('W1AW', first_name='Updated')
        repo.toggle_flag(first.id, 'has_traffic')
        app.screen.refresh_all()
        assert table.get_cell(str(first.id), 'name') == 'Updated'
        assert 'T' in str(table.get_cell(str(first.id), 'flags'))
        repo.move_checkin(second.id, -1)
        app.screen.refresh_all()
        assert table.get_row_index(str(second.id)) == 0
        repo.delete_checkin(second.id)
        app.screen.refresh_all()
        assert table.row_count == 1 and table.get_row_index(str(first.id)) == 0
