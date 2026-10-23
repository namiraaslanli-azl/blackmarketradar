"""Collector framework.

A collector is a class with `collect(ctx)` yielding `FindingIn` objects. `run_collector`
handles the rest: config + secrets check, collector_runs logging, deduplicating upserts,
whitelist exclusion, optional per-item post-processing and the linker pass.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar, Iterable, Iterator

from sqlalchemy import select, update

from radar.config import get_settings
from radar.db import session_scope
from radar.models import CollectorConfig, CollectorRun, Finding, Keyword, TrackedTarget, WhitelistEntry
from radar.normalize import EntityRef, NotAUrl, registrable_domain
from radar.runs import RunStats, track_run
from radar.store import FindingIn, operator_index, upsert_finding

log = logging.getLogger(__name__)
REGISTRY: dict[str, "Collector"] = {}
BATCH = 50


@dataclass
class KeywordRow:
    term: str
    kind: str
    lang: str | None


@dataclass
class Whitelist:
    domains: set[str] = field(default_factory=set)
    handles: set[str] = field(default_factory=set)
    apps: set[str] = field(default_factory=set)

    def covers(self, ref: EntityRef) -> bool:
        if ref.source == "organic_domain":
            return ref.host in self.domains or registrable_domain(ref.host) in self.domains
        if ref.source in ("play_store_app", "app_store_app"):
            return (ref.handle or "").lower() in self.apps
        return (ref.handle or "").lower().lstrip("@") in self.handles


@dataclass
class Ctx:
    name: str
    params: dict
    keywords: list[KeywordRow]
    targets: dict[str, list[str]]
    aliases: dict[str, list[str]]
    whitelist: Whitelist
    stats: RunStats
    touched_targets: set[tuple[str, str]] = field(default_factory=set)

    def terms(self, *kinds: str, lang: str | None = None) -> list[str]:
        return [k.term for k in self.keywords if (not kinds or k.kind in kinds) and (lang is None or k.lang in (lang, None, ""))]

    def error(self, msg: str) -> None:
        log.warning("%s: %s", self.name, msg)
        self.stats.error(msg)

    def mark_target(self, kind: str, value: str) -> None:
        self.touched_targets.add((kind, value))


class CollectorNotConfigured(RuntimeError):
    pass


class Collector:
    name: ClassVar[str]
    title: ClassVar[str]               # shown in the UI (Azerbaijani)
    schedule: ClassVar[dict] = {}       # celery crontab kwargs, Asia/Baku
    defaults: ClassVar[dict] = {}
    requires: ClassVar[tuple[str, ...]] = ()  # Settings attributes that must be non-empty

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if getattr(cls, "name", None):
            REGISTRY[cls.name] = cls()

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        raise NotImplementedError

    def after_upsert(self, session, finding: Finding, item: FindingIn, ctx: Ctx) -> None:
        """Optional per-item hook (OCR, linked accounts…). Runs inside the batch transaction."""

    def after_run(self, ctx: Ctx, touched: list[int]) -> None:
        """Optional hook after all items are stored and linked."""

    def missing_secrets(self) -> list[str]:
        s = get_settings()
        return [r.upper() for r in self.requires if not getattr(s, r, None)]


def load_context(session, name: str, params: dict, stats: RunStats) -> Ctx:
    kws = [KeywordRow(k.term, k.kind, k.lang) for k in session.scalars(select(Keyword).where(Keyword.active))]
    targets: dict[str, list[str]] = defaultdict(list)
    for t in session.scalars(select(TrackedTarget).where(TrackedTarget.active).order_by(TrackedTarget.id)):
        targets[t.kind].append(t.value)
    wl = Whitelist()
    for w in session.scalars(select(WhitelistEntry)):
        v = w.value.lower().lstrip("@")
        {"domain": wl.domains, "handle": wl.handles, "app": wl.apps}.get(w.kind, set()).add(v)
    aliases, _ = operator_index(session)
    return Ctx(name, params, kws, dict(targets), aliases, wl, stats)


def effective_params(session, collector: Collector, override: dict | None = None) -> tuple[bool, dict]:
    cfg = session.get(CollectorConfig, collector.name)
    params = {**collector.defaults, **((cfg.params if cfg else None) or {}), **(override or {})}
    return (cfg.enabled if cfg else True), params


def _record_skip(name: str, reason: str) -> None:
    with session_scope() as s:
        now = datetime.now(timezone.utc)
        s.add(CollectorRun(collector=name, status="skipped", started_at=now, finished_at=now, duration_ms=0,
                           error_log=reason, params={}))


def _batched(it: Iterator, n: int):
    batch = []
    for x in it:
        batch.append(x)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


def run_collector(name: str, override: dict | None = None, force: bool = False) -> dict:
    collector = REGISTRY[name]
    missing = collector.missing_secrets()
    if missing:
        _record_skip(name, f"missing secrets in .env: {', '.join(missing)}")
        return {"status": "skipped", "missing": missing}
    with session_scope() as s:
        enabled, params = effective_params(s, collector, override)
    if not enabled and not force:
        return {"status": "disabled"}

    with track_run(name, params) as stats:
        with session_scope() as s:
            ctx = load_context(s, name, params, stats)
        summary = ingest(name, collector.collect(ctx), ctx, collector)
        collector.after_run(ctx, summary.pop("touched"))
    return {"status": "ok" if not stats.errors else "partial", **summary}


def ingest(name: str, items: Iterable[FindingIn], ctx: Ctx, collector: Collector | None = None) -> dict:
    """Upsert items in batches (whitelist excluded), then link the touched findings."""
    from radar.linker import run_linker

    stats = ctx.stats
    touched: list[int] = []
    whitelisted = 0
    for batch in _batched(iter(items), BATCH):
        with session_scope() as s:
            for item in batch:
                stats.found += 1
                try:
                    ref = item.resolve()
                except NotAUrl:
                    ctx.error(f"bad url: {item.url!r}"[:200])
                    continue
                if ctx.whitelist.covers(ref):
                    whitelisted += 1
                    continue
                try:
                    with s.begin_nested():
                        res = upsert_finding(s, item, status_policy="keep", actor=name)
                        if collector is not None:
                            collector.after_upsert(s, res.finding, item, ctx)
                except Exception as exc:  # noqa: BLE001 — one bad item must not stop the run
                    ctx.error(f"{item.url}: {exc!r}"[:300])
                    continue
                stats.new += res.created
                stats.updated += (not res.created) and res.changed
                touched.append(res.finding.id)
    if touched:
        with session_scope() as s:
            for chunk in range(0, len(touched), 500):
                ids = touched[chunk:chunk + 500]
                run_linker(s, list(s.scalars(select(Finding).where(Finding.id.in_(ids)))), cluster=False)
    if ctx.touched_targets:
        with session_scope() as s:
            now = datetime.now(timezone.utc)
            for kind, value in ctx.touched_targets:
                s.execute(update(TrackedTarget).where(TrackedTarget.kind == kind, TrackedTarget.value == value)
                          .values(last_collected_at=now))
    return {"found": stats.found, "new": stats.new, "updated": stats.updated, "errors": stats.errors,
            "whitelisted": whitelisted, "touched": touched}


def run_items(name: str, items: list[FindingIn], params: dict | None = None) -> dict:
    """Ingest a ready list of items as one logged run (used by streaming sources such as CertStream)."""
    with track_run(name, params or {}) as stats:
        with session_scope() as s:
            ctx = load_context(s, name, params or {}, stats)
        return ingest(name, items, ctx)
