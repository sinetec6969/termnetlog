"""Cache-first operator lookups: local DB -> QRZ -> HamDB."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
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
    def __init__(self, repo: Repo, providers: list[Provider], cache_days: int = 30,
                 max_concurrent: int = 4, retry_seconds: int = 300):
        if max_concurrent < 1 or retry_seconds < 0:
            raise ValueError("Invalid lookup concurrency or retry delay")
        self.repo = repo
        self.providers = providers
        self.cache_days = cache_days
        self.retry_seconds = retry_seconds
        self._slots = asyncio.Semaphore(max_concurrent)
        self._pending: dict[str, asyncio.Task[LookupOutcome]] = {}
        self._waiters: dict[asyncio.Task, int] = {}
        self._closed = False

    @classmethod
    def from_config(cls, repo: Repo, config: Config) -> LookupService:
        providers: list[Provider] = []
        if config.offline:
            return cls(repo, providers, config.cache_days)
        if config.qrz_username and config.qrz_password:
            providers.append(QRZProvider(config.qrz_username, config.qrz_password))
        if config.hamdb:
            providers.append(HamDBProvider())
        return cls(repo, providers, config.cache_days)

    def is_fresh(self, op: Operator) -> bool:
        if op.lookup_source == "manual":
            return True
        attempt = self.repo.lookup_attempt(op.callsign)
        if attempt:
            timestamp, status = attempt
            ttl = (timedelta(seconds=self.retry_seconds) if status in {"partial", "error"}
                   else timedelta(days=self.cache_days))
            return utcnow() - from_iso(timestamp) < ttl
        looked = from_iso(op.lookup_at)
        return looked is not None and utcnow() - looked < timedelta(days=self.cache_days)

    async def resolve(self, callsign: str, force: bool = False) -> LookupOutcome:
        """Coalesce calls across screens; cancel only after the last caller leaves.

        Force bypasses the cache/cooldown but joins an already-running refresh.
        Retries happen on a later resolve, never in an unbounded background loop.
        """
        if self._closed:
            raise RuntimeError("Lookup service is closed")
        task = self._pending.get(callsign)
        if task is None:
            task = asyncio.create_task(self._resolve(callsign, force))
            self._pending[callsign] = task
            self._waiters[task] = 0
        self._waiters[task] += 1
        try:
            return await asyncio.shield(task)
        finally:
            self._waiters[task] -= 1
            if self._waiters[task] == 0:
                del self._waiters[task]
                if self._pending.get(callsign) is task:
                    del self._pending[callsign]
                if not task.done():
                    task.cancel()
                # Retrieve failures and finish cancellation before releasing ownership.
                await asyncio.gather(task, return_exceptions=True)

    async def _resolve(self, callsign: str, force: bool) -> LookupOutcome:
        async with self._slots:
            return await self._fetch(callsign, force)

    async def _fetch(self, callsign: str, force: bool) -> LookupOutcome:
        op = self.repo.ensure_operator(callsign)
        if op.lookup_source == "manual" or (not force and self.is_fresh(op)):
            attempt = self.repo.lookup_attempt(callsign)
            found = bool(op.lookup_source and op.lookup_source != "none")
            if op.lookup_source != "manual" and attempt and attempt[1] == "not_found":
                found = False
            return LookupOutcome(op, found=found)

        result: LookupResult | None = None
        errors: list[str] = []
        for provider in self.providers:
            try:
                r = await provider.lookup(callsign)
                if r is not None:
                    if not isinstance(r, LookupResult) or not isinstance(r.source, str):
                        raise LookupFailed(f"{provider.name}: invalid result")
                    if any(value is not None and not isinstance(value, str)
                           for value in (getattr(r, f) for f in LookupResult.DATA_FIELDS)):
                        raise LookupFailed(f"{provider.name}: invalid result fields")
            except LookupFailed as e:
                errors.append(str(e))
                continue
            except Exception as e:
                # Report the bug without exposing request URLs, credentials or body text.
                # CancelledError is a BaseException and must continue to propagate.
                errors.append(f"{provider.name}: unexpected {type(e).__name__}")
                continue
            if r is None:
                continue
            r = replace(r, callsign=callsign)  # don't mutate shared provider records
            result = r if result is None else result.merge(r)
            if result.complete:
                break

        if result is not None:
            operator = self.repo.apply_lookup(result)
            self.repo.record_lookup_attempt(callsign, "complete" if result.complete and not errors else "partial")
            return LookupOutcome(operator, updated=operator.lookup_source != "manual", errors=errors)
        if not errors and self.providers:
            # Every provider answered "not found"; remember so we don't hammer them.
            self.repo.mark_looked_up(callsign, "none")
            self.repo.record_lookup_attempt(callsign, "not_found")
        elif errors:
            self.repo.record_lookup_attempt(callsign, "error")
        return LookupOutcome(self.repo.get_operator(callsign) or op, found=False, errors=errors)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for p in self.providers:
            close = getattr(p, "aclose", None)
            if close:
                await close()
