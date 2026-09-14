"""Cache-first operator lookups: local DB -> QRZ -> HamDB."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from termnetlog.config import Config
from termnetlog.lookup.base import LookupFailed, LookupResult, Provider
from termnetlog.lookup.hamdb import HamDBProvider
from termnetlog.lookup.qrz import QRZProvider
from termnetlog.models import Operator, from_iso, utcnow
from termnetlog.repo import Repo


@dataclass
class LookupOutcome:
    operator: Operator
    updated: bool = False  # fresh data was fetched and stored
    found: bool = True
    errors: list[str] = field(default_factory=list)


class LookupService:
    def __init__(self, repo: Repo, providers: list[Provider], cache_days: int = 30):
        self.repo = repo
        self.providers = providers
        self.cache_days = cache_days

    @classmethod
    def from_config(cls, repo: Repo, config: Config) -> LookupService:
        providers: list[Provider] = []
        if config.qrz_username and config.qrz_password:
            providers.append(QRZProvider(config.qrz_username, config.qrz_password))
        if config.hamdb:
            providers.append(HamDBProvider())
        return cls(repo, providers, config.cache_days)

    def is_fresh(self, op: Operator) -> bool:
        if op.lookup_source == "manual":
            return True
        looked = from_iso(op.lookup_at)
        return looked is not None and utcnow() - looked < timedelta(days=self.cache_days)

    async def resolve(self, callsign: str, force: bool = False) -> LookupOutcome:
        op = self.repo.ensure_operator(callsign)
        if op.lookup_source == "manual" or (not force and self.is_fresh(op)):
            return LookupOutcome(op, found=bool(op.lookup_source and op.lookup_source != "none"))

        result: LookupResult | None = None
        errors: list[str] = []
        for provider in self.providers:
            try:
                r = await provider.lookup(callsign)
            except LookupFailed as e:
                errors.append(str(e))
                continue
            if r is None:
                continue
            r.callsign = callsign  # providers may return an alias; keep our key
            result = r if result is None else result.merge(r)
            if result.complete:
                break

        if result is not None:
            return LookupOutcome(self.repo.apply_lookup(result), updated=True, errors=errors)
        if not errors and self.providers:
            # Every provider answered "not found"; remember so we don't hammer them.
            self.repo.mark_looked_up(callsign, "none")
        return LookupOutcome(self.repo.get_operator(callsign) or op, found=False, errors=errors)

    async def aclose(self) -> None:
        for p in self.providers:
            close = getattr(p, "aclose", None)
            if close:
                await close()
