import json

import httpx
import pytest

from termnetlog.lookup import hamdb, qrz
from termnetlog.lookup.base import LookupFailed, LookupResult
from termnetlog.lookup.service import LookupService

from conftest import FakeProvider


def test_qrz_parse_full(fixture_text):
    call_el, session = qrz.parse_response(fixture_text("qrz_callsign.xml"))
    r = qrz.parse_callsign(call_el)
    assert r.callsign == "AA7BQ"
    assert r.name == "Fred L Lloyd"
    assert r.first_name == "Fred"
    assert (r.city, r.state, r.county, r.grid) == ("Scottsdale", "AZ", "Maricopa", "DM32af")
    assert r.license_class == "Extra"
    assert r.complete


def test_qrz_parse_partial(fixture_text):
    call_el, _ = qrz.parse_response(fixture_text("qrz_partial.xml"))
    r = qrz.parse_callsign(call_el)
    assert r.first_name == "Arrl" and r.city is None
    assert not r.complete


def qrz_client(responses):
    """MockTransport that serves fixture bodies in order, recording requests."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, text=responses.pop(0))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


async def test_qrz_login_and_lookup(fixture_text):
    client, seen = qrz_client([fixture_text("qrz_login.xml"), fixture_text("qrz_callsign.xml")])
    p = qrz.QRZProvider("me", "secret", client=client)
    r = await p.lookup("AA7BQ")
    assert r.name == "Fred L Lloyd"
    assert seen[0]["username"] == "me"
    assert seen[1]["s"] == "abc123sessionkey" and seen[1]["callsign"] == "AA7BQ"


async def test_qrz_relogin_on_timeout(fixture_text):
    client, seen = qrz_client(
        [
            fixture_text("qrz_login.xml"),
            fixture_text("qrz_timeout.xml"),
            fixture_text("qrz_login.xml"),
            fixture_text("qrz_callsign.xml"),
        ]
    )
    p = qrz.QRZProvider("me", "secret", client=client)
    r = await p.lookup("AA7BQ")
    assert r is not None and len(seen) == 4


async def test_qrz_not_found(fixture_text):
    client, _ = qrz_client([fixture_text("qrz_login.xml"), fixture_text("qrz_notfound.xml")])
    assert await qrz.QRZProvider("me", "secret", client=client).lookup("N0CALL") is None


async def test_qrz_bad_login():
    bad = '<QRZDatabase xmlns="http://xmldata.qrz.com"><Session><Error>Username/password incorrect</Error></Session></QRZDatabase>'
    client, _ = qrz_client([bad])
    with pytest.raises(qrz.QRZAuthError):
        await qrz.QRZProvider("me", "wrong", client=client).lookup("W1AW")


async def test_qrz_unconfigured_skips():
    assert await qrz.QRZProvider("", "").lookup("W1AW") is None


def test_hamdb_parse(fixture_text):
    r = hamdb.parse(json.loads(fixture_text("hamdb_w1aw.json")))
    assert r.name == "Arrl Hq Operators Club"
    assert (r.city, r.state, r.grid, r.license_class) == ("Newington", "CT", "FN31pr", "Club")
    assert hamdb.parse(json.loads(fixture_text("hamdb_notfound.json"))) is None


async def test_hamdb_http_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    with pytest.raises(LookupFailed):
        await hamdb.HamDBProvider(client=client).lookup("W1AW")


async def test_service_merges_and_caches(repo):
    partial = FakeProvider({"W1AW": LookupResult("W1AW", "qrz", first_name="Hiram", name="Hiram Maxim")})
    fallback = FakeProvider({"W1AW": LookupResult("W1AW", "hamdb", name="ARRL", city="Newington", state="CT", grid="FN31")})
    svc = LookupService(repo, [partial, fallback])

    out = await svc.resolve("W1AW")
    assert out.updated and out.found
    op = out.operator
    assert (op.name, op.city, op.grid, op.lookup_source) == ("Hiram Maxim", "Newington", "FN31", "qrz")

    out2 = await svc.resolve("W1AW")  # cached
    assert not out2.updated and len(partial.calls) == 1

    await svc.resolve("W1AW", force=True)
    assert len(partial.calls) == 2


async def test_service_complete_result_skips_fallback(repo):
    full = FakeProvider({"W1AW": LookupResult("W1AW", "qrz", name="Hiram", city="Newington", state="CT")})
    fallback = FakeProvider()
    await LookupService(repo, [full, fallback]).resolve("W1AW")
    assert fallback.calls == []


async def test_service_offline_retries_later(repo):
    svc = LookupService(repo, [FakeProvider(fail=True)])
    out = await svc.resolve("W1AW")
    assert not out.found and out.errors == ["fake: offline"]
    assert repo.get_operator("W1AW").lookup_at is None  # will retry


async def test_service_not_found_is_remembered(repo):
    prov = FakeProvider()
    svc = LookupService(repo, [prov])
    await svc.resolve("N0CALL")
    out = await svc.resolve("N0CALL")
    assert not out.found and len(prov.calls) == 1
