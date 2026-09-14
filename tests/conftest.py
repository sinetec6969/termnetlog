from __future__ import annotations

from pathlib import Path

import pytest

from termnetlog import db
from termnetlog.lookup.base import LookupResult
from termnetlog.repo import Repo

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(db.connect(tmp_path / "test.db"))


class FakeProvider:
    name = "fake"

    def __init__(self, results: dict[str, LookupResult] | None = None, fail: bool = False):
        self.results = results or {}
        self.fail = fail
        self.calls: list[str] = []

    async def lookup(self, callsign: str) -> LookupResult | None:
        from termnetlog.lookup.base import LookupFailed

        self.calls.append(callsign)
        if self.fail:
            raise LookupFailed("fake: offline")
        return self.results.get(callsign)


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text()
