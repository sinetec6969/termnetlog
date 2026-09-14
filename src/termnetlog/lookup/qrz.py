"""QRZ.com XML data API client.

Docs: https://www.qrz.com/XML/current_spec.html
Login returns a session key that is reused for lookups until it expires.
Accounts without an XML subscription receive a reduced record.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from termnetlog import __version__
from termnetlog.lookup.base import LookupFailed, LookupResult, clean

URL = "https://xmldata.qrz.com/xml/current/"
AGENT = f"termnetlog-{__version__}"
NS = "{http://xmldata.qrz.com}"

CLASS_NAMES = {"E": "Extra", "A": "Advanced", "G": "General", "T": "Technician", "N": "Novice", "C": "Club"}


class QRZAuthError(LookupFailed):
    pass


def _text(el: ET.Element | None, tag: str) -> str | None:
    if el is None:
        return None
    child = el.find(NS + tag)
    return clean(child.text) if child is not None else None


def tidy_case(value: str | None) -> str | None:
    """FCC/QRZ data is often ALL CAPS; make names readable."""
    if value and value.isupper():
        return value.title()
    return value


def parse_response(xml_text: str) -> tuple[ET.Element | None, ET.Element | None]:
    """Return (Callsign element, Session element)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise LookupFailed(f"QRZ: bad XML: {e}") from e
    return root.find(NS + "Callsign"), root.find(NS + "Session")


def parse_callsign(el: ET.Element) -> LookupResult:
    fname = tidy_case(_text(el, "fname"))
    lname = tidy_case(_text(el, "name"))
    full = " ".join(p for p in (fname, lname) if p) or None
    first = fname.split()[0] if fname else None
    cls = _text(el, "class")
    return LookupResult(
        callsign=(_text(el, "call") or "").upper(),
        source="qrz",
        first_name=first,
        name=full,
        nickname=tidy_case(_text(el, "nickname")),
        city=tidy_case(_text(el, "addr2")),
        state=_text(el, "state"),
        county=tidy_case(_text(el, "county")),
        country=_text(el, "country"),
        grid=_text(el, "grid"),
        license_class=CLASS_NAMES.get(cls.upper(), cls) if cls else None,
    )


class QRZProvider:
    name = "qrz"

    def __init__(self, username: str, password: str, client: httpx.AsyncClient | None = None):
        self.username = username
        self.password = password
        self._client = client
        self._key: str | None = None
        self.message: str | None = None  # e.g. subscription notice

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, follow_redirects=True)
        return self._client

    async def _get(self, params: dict[str, str]) -> str:
        try:
            resp = await self.client.get(URL, params={**params, "agent": AGENT})
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Don't echo the URL: the login request carries the password.
            raise LookupFailed(f"QRZ: HTTP {e.response.status_code}") from None
        except httpx.HTTPError as e:
            raise LookupFailed(f"QRZ: {type(e).__name__}") from None
        return resp.text

    async def login(self) -> None:
        text = await self._get({"username": self.username, "password": self.password})
        _, session = parse_response(text)
        key = _text(session, "Key")
        if not key:
            raise QRZAuthError(f"QRZ login failed: {_text(session, 'Error') or 'no session key'}")
        self._key = key
        self.message = _text(session, "Message")

    async def lookup(self, callsign: str) -> LookupResult | None:
        if not self.username or not self.password:
            return None
        for attempt in range(2):
            if self._key is None:
                await self.login()
            text = await self._get({"s": self._key or "", "callsign": callsign})
            call_el, session = parse_response(text)
            if call_el is not None:
                self.message = _text(session, "Message")
                return parse_callsign(call_el)
            error = _text(session, "Error") or ""
            if error.lower().startswith("not found"):
                return None
            if not _text(session, "Key") and attempt == 0:
                # Session timed out or key invalid: log in again once.
                self._key = None
                continue
            raise LookupFailed(f"QRZ: {error or 'unexpected response'}")
        return None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
