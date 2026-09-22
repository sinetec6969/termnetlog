import asyncio

import httpx
import pytest

from termnetlog.config import Config
from termnetlog.lookup.base import LookupResult
from termnetlog.lookup.hamdb import HamDBProvider
from termnetlog.lookup.service import LookupService
from termnetlog.tui.app import NetLogApp
from termnetlog.tui.screens.net import NetScreen
from termnetlog.tui.widgets.checkin_table import CallInput

from conftest import FakeProvider


@pytest.mark.parametrize('failure', ['malformed', 'timeout', 'storage'])
async def test_lookup_failure_does_not_stop_logging(repo, tmp_path, monkeypatch, failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('SECRET', request=request)
        return httpx.Response(200, json={'hamdb': None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        providers = [HamDBProvider(client)]
        if failure == 'storage':
            providers = [FakeProvider({'W1AW': LookupResult('W1AW', 'fake', name='Name', city='City')})]

            def broken_save(result):
                raise RuntimeError('SECRET')

            monkeypatch.setattr(repo, 'apply_lookup', broken_save)
        app = NetLogApp(Config(), repo, LookupService(repo, providers), export_dir=tmp_path)
        errors = []
        monkeypatch.setattr(app, 'lookup_error', errors.append)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press('n', 'ctrl+s')
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, NetScreen)
            for call in ['W1AW', 'K9XYZ']:
                screen.query_one(CallInput).value = call
                await pilot.press('enter')
                # wait_for_complete raises for errored workers even if nonfatal;
                # poll their lifecycle instead to test the app's error boundary.
                for _ in range(100):
                    await pilot.pause()
                    if not screen.pending:
                        break
                assert not screen.pending
            assert app.screen is screen
            assert len(repo.list_checkins(screen.net_id)) == 2
            assert errors and all('SECRET' not in error for error in errors)


async def test_leaving_net_cancels_its_pending_lookup(repo, tmp_path):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class SlowProvider:
        name = 'slow'

        async def lookup(self, call):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    service = LookupService(repo, [SlowProvider()])
    app = NetLogApp(Config(), repo, service, export_dir=tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press('n', 'ctrl+s')
        await pilot.pause()
        net_id = app.screen.net_id
        app.screen.query_one(CallInput).value = 'W1AW'
        await pilot.press('enter')
        await asyncio.wait_for(entered.wait(), 2)
        await pilot.press('ctrl+b')
        await asyncio.wait_for(cancelled.wait(), 2)
        await pilot.pause()
        assert not service._pending
        assert repo.lookup_attempt('W1AW') is None
        assert repo.list_checkins(net_id)[0].checkin.callsign == 'W1AW'
