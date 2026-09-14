"""HamDB (api.hamdb.org) — free, keyless lookups of US FCC (and some Canadian) data."""

from __future__ import annotations

import httpx

from termnetlog.lookup.base import LookupFailed, LookupResult, clean
from termnetlog.lookup.qrz import AGENT, CLASS_NAMES, tidy_case

URL = "https://api.hamdb.org/v1/{call}/json/{agent}"


def parse(data: dict) -> LookupResult | None:
    try:
        body = data["hamdb"]
    except (KeyError, TypeError) as e:
        raise LookupFailed("HamDB: unexpected response") from e
    status = (body.get("messages") or {}).get("status", "")
    cs = body.get("callsign") or {}
    if status != "OK" or cs.get("call") in (None, "", "NOT_FOUND"):
        return None

    fname = tidy_case(clean(cs.get("fname")))
    lname = tidy_case(clean(cs.get("name")))
    full = " ".join(p for p in (fname, clean(cs.get("mi")), lname) if p) or None
    cls = clean(cs.get("class"))
    return LookupResult(
        callsign=cs["call"].upper(),
        source="hamdb",
        first_name=fname.split()[0] if fname else None,
        name=full,
        city=tidy_case(clean(cs.get("addr2"))),
        state=clean(cs.get("state")),
        country=clean(cs.get("country")),
        grid=clean(cs.get("grid")),
        license_class=CLASS_NAMES.get(cls.upper(), cls) if cls else None,
    )


class HamDBProvider:
    name = "hamdb"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, follow_redirects=True)
        return self._client

    async def lookup(self, callsign: str) -> LookupResult | None:
        try:
            resp = await self.client.get(URL.format(call=callsign.lower(), agent=AGENT))
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LookupFailed(f"HamDB: {e}") from e
        return parse(data)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
