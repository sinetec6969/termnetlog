from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Protocol


class LookupFailed(Exception):
    """A lookup provider failed (network, auth, bad response)."""


@dataclass
class LookupResult:
    callsign: str
    source: str
    first_name: str | None = None
    name: str | None = None
    nickname: str | None = None
    city: str | None = None
    state: str | None = None
    county: str | None = None
    country: str | None = None
    grid: str | None = None
    license_class: str | None = None

    DATA_FIELDS = (
        "first_name", "name", "nickname", "city", "state",
        "county", "country", "grid", "license_class",
    )

    @property
    def complete(self) -> bool:
        """Has the fields a net logger cares about most."""
        return bool((self.first_name or self.name) and (self.city or self.state))

    def merge(self, other: LookupResult) -> LookupResult:
        """Fill our missing fields from another result."""
        for f in fields(self):
            if f.name in self.DATA_FIELDS and not getattr(self, f.name):
                setattr(self, f.name, getattr(other, f.name))
        return self


class Provider(Protocol):
    name: str

    async def lookup(self, callsign: str) -> LookupResult | None:
        """Return a result, None if the call isn't found; raise LookupFailed on failure."""
        ...


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None
