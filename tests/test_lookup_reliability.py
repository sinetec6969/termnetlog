import asyncio
from datetime import timedelta

import httpx
import pytest

from termnetlog.lookup import hamdb, qrz
from termnetlog.lookup.base import LookupResult
from termnetlog.lookup.service import LookupService
from termnetlog.models import from_iso

from conftest import FakeProvider


async def test_partial_refresh_preserves_data_and_retries_after_cooldown(repo, monkeypatch):
    repo.apply_lookup(LookupResult('W1AW', 'hamdb', name='Old Name', city='Newington', grid='FN31'))
    partial = FakeProvider({'W1AW': LookupResult('W1AW', 'qrz', name='New Name')})
    fallback = FakeProvider(fail=True)
    service = LookupService(repo, [partial, fallback])
    outcome = await service.resolve('W1AW', force=True)
    assert (outcome.operator.name, outcome.operator.city, outcome.operator.grid) == ('New Name', 'Newington', 'FN31')
    assert outcome.errors
    attempt, status = repo.lookup_attempt('W1AW')
    assert status == 'partial'
    # Cooldown survives creating a new service (e.g. application restart).
    service = LookupService(repo, [partial, fallback])
    await service.resolve('W1AW')
    assert len(partial.calls) == 1
    monkeypatch.setattr('termnetlog.lookup.service.utcnow', lambda: from_iso(attempt) + timedelta(minutes=5))
    fallback.fail = False
    fallback.results['W1AW'] = LookupResult('W1AW', 'hamdb', city='New City')
    outcome = await service.resolve('W1AW')
    assert len(partial.calls) == 2 and outcome.operator.city == 'New City'
    assert repo.lookup_attempt('W1AW')[1] == 'complete'
    assert service.is_fresh(outcome.operator)


async def test_forced_refresh_bypasses_error_cooldown(repo):
    provider = FakeProvider(fail=True)
    service = LookupService(repo, [provider])
    await service.resolve('W1AW')
    await service.resolve('W1AW')
    assert len(provider.calls) == 1
    assert repo.get_operator('W1AW').lookup_at is None
    assert repo.lookup_attempt('W1AW')[1] == 'error'
    await service.resolve('W1AW', force=True)
    assert len(provider.calls) == 2


async def test_not_found_does_not_redate_old_data(repo):
    repo.apply_lookup(LookupResult('W1AW', 'hamdb', name='Known Name'))
    repo.conn.execute("UPDATE operators SET lookup_at = '2020-01-01T00:00:00Z'")
    repo.conn.commit()
    service = LookupService(repo, [FakeProvider()])
    outcome = await service.resolve('W1AW')
    cached = await service.resolve('W1AW')
    assert not outcome.found and not cached.found
    assert cached.operator.name == 'Known Name'
    assert cached.operator.lookup_at == '2020-01-01T00:00:00Z'


@pytest.mark.parametrize('body', [
    {'hamdb': None},
    {'hamdb': {'messages': 'unavailable'}},
    {'hamdb': {'messages': {'status': 'OK'}, 'callsign': {'call': 'W1AW', 'fname': 42}}},
    {'hamdb': {'messages': {'status': 'ERROR'}}},
    {'hamdb': {'messages': {'status': 'OK'}, 'callsign': []}},
    {'hamdb': {'messages': {'status': 'OK'}, 'callsign': {}}},
    [],
])
async def test_malformed_lookup_is_recoverable(repo, body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        outcome = await LookupService(repo, [hamdb.HamDBProvider(client)]).resolve('W1AW')
    assert outcome.errors
    assert repo.get_operator('W1AW').lookup_at is None
    assert repo.lookup_attempt('W1AW')[1] == 'error'


@pytest.mark.parametrize('response', ['<broken', '<html/>',
    '<QRZDatabase xmlns="http://xmldata.qrz.com"><Callsign><fname>Name</fname></Callsign></QRZDatabase>'])
async def test_bad_qrz_response_falls_back(repo, response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=response))) as client:
        provider = qrz.QRZProvider('user', 'secret', client)
        provider._key = 'session'
        fallback = FakeProvider({'W1AW': LookupResult('W1AW', 'fallback', name='Known', city='City')})
        outcome = await LookupService(repo, [provider, fallback]).resolve('W1AW')
    assert outcome.errors and outcome.operator.city == 'City'


async def test_unexpected_error_is_reported_without_secret(repo):
    class BrokenProvider:
        name = 'broken'

        async def lookup(self, call):
            raise ValueError('request password=SECRET')

    outcome = await LookupService(repo, [BrokenProvider()]).resolve('W1AW')
    assert outcome.errors == ['broken: unexpected ValueError']


async def test_qrz_errors_do_not_echo_response_secrets():
    response = '<QRZDatabase xmlns="http://xmldata.qrz.com"><Session><Error>SECRET</Error></Session></QRZDatabase>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=response))) as client:
        with pytest.raises(qrz.QRZAuthError, match='check credentials') as caught:
            await qrz.QRZProvider('user', 'SECRET', client).lookup('W1AW')
        assert 'SECRET' not in str(caught.value)


class BlockingProvider:
    name = 'blocking'

    def __init__(self, target=1):
        self.calls = []
        self.active = 0
        self.peak = 0
        self.target = target
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def lookup(self, call):
        self.calls.append(call)
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active >= self.target:
            self.entered.set()
        try:
            await self.release.wait()
            return LookupResult(call, self.name, name='Name', city='City')
        finally:
            self.active -= 1

    async def aclose(self):
        assert self.active == 0
        self.closed = True


async def test_bounded_concurrency(repo):
    provider = BlockingProvider(target=2)
    service = LookupService(repo, [provider], max_concurrent=2)
    tasks = [asyncio.create_task(service.resolve(call)) for call in ['W1AW', 'K9XYZ', 'N0CALL', 'AA7BQ']]
    await asyncio.wait_for(provider.entered.wait(), 2)
    assert len(provider.calls) == 2
    provider.release.set()
    await asyncio.wait_for(asyncio.gather(*tasks), 2)
    assert len(provider.calls) == 4 and provider.peak == 2
    await service.aclose()


async def test_cancelling_one_caller_keeps_shared_lookup(repo):
    provider = BlockingProvider()
    service = LookupService(repo, [provider])
    first = asyncio.create_task(service.resolve('W1AW'))
    await asyncio.wait_for(provider.entered.wait(), 2)
    second = asyncio.create_task(service.resolve('W1AW', force=True))
    await asyncio.sleep(0)  # let the second caller subscribe before cancelling
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert provider.active == 1
    provider.release.set()
    outcome = await asyncio.wait_for(second, 2)
    assert outcome.operator.city == 'City' and provider.calls == ['W1AW']
    assert not service._pending
    await service.aclose()


async def test_cancelling_last_caller_cancels_request_and_allows_retry(repo):
    provider = BlockingProvider()
    service = LookupService(repo, [provider])
    task = asyncio.create_task(service.resolve('W1AW'))
    await asyncio.wait_for(provider.entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.active == 0 and not service._pending
    assert repo.lookup_attempt('W1AW') is None
    provider.release.set()
    assert (await service.resolve('W1AW')).updated
    assert len(provider.calls) == 2
    await service.aclose()


async def test_shutdown_cancels_active_and_queued_requests_before_closing(repo):
    provider = BlockingProvider()
    service = LookupService(repo, [provider], max_concurrent=1)
    tasks = [asyncio.create_task(service.resolve(call)) for call in ['W1AW', 'K9XYZ']]
    await asyncio.wait_for(provider.entered.wait(), 2)
    await service.aclose()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert provider.closed and provider.calls == ['W1AW']
    assert not service._pending
    with pytest.raises(RuntimeError, match='closed'):
        await service.resolve('W1AW')


async def test_manual_edit_during_lookup_is_preserved(repo):
    provider = BlockingProvider()
    service = LookupService(repo, [provider])
    task = asyncio.create_task(service.resolve('W1AW'))
    await asyncio.wait_for(provider.entered.wait(), 2)
    repo.update_operator('W1AW', name='My Name', city='')
    provider.release.set()
    outcome = await task
    assert outcome.operator.name == 'My Name' and outcome.operator.city is None
    assert not outcome.updated
    await service.resolve('W1AW', force=True)
    assert provider.calls == ['W1AW']


async def test_concurrent_qrz_requests_share_login(fixture_text):
    logins = []

    async def handler(request):
        if 'username' in request.url.params:
            logins.append(request)
            await asyncio.sleep(0)
            return httpx.Response(200, text=fixture_text('qrz_login.xml'))
        return httpx.Response(200, text=fixture_text('qrz_callsign.xml'))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = qrz.QRZProvider('user', 'secret', client)
        results = await asyncio.gather(*(provider.lookup(call) for call in ['W1AW', 'AA7BQ', 'K9XYZ']))
    assert len(logins) == 1 and all(results)


async def test_concurrent_expired_sessions_share_relogin(fixture_text):
    both_expired = asyncio.Event()
    old_requests = []
    logins = []

    async def handler(request):
        if 'username' in request.url.params:
            logins.append(request)
            await asyncio.sleep(0)
            return httpx.Response(200, text=fixture_text('qrz_login.xml'))
        if request.url.params['s'] == 'expired':
            old_requests.append(request)
            if len(old_requests) == 2:
                both_expired.set()
            await both_expired.wait()
            return httpx.Response(200, text=fixture_text('qrz_timeout.xml'))
        return httpx.Response(200, text=fixture_text('qrz_callsign.xml'))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = qrz.QRZProvider('user', 'secret', client)
        provider._key = 'expired'
        results = await asyncio.wait_for(asyncio.gather(provider.lookup('W1AW'), provider.lookup('AA7BQ')), 2)
    assert len(logins) == 1 and len(old_requests) == 2 and all(results)


async def test_provider_results_are_not_mutated(repo):
    result = LookupResult('ALIAS', 'first', name='Name')
    first = FakeProvider({'W1AW': result})
    second = FakeProvider({'W1AW': LookupResult('W1AW', 'second', city='City')})
    outcome = await LookupService(repo, [first, second]).resolve('W1AW')
    assert outcome.operator.callsign == 'W1AW' and outcome.operator.city == 'City'
    assert result.callsign == 'ALIAS' and result.city is None
