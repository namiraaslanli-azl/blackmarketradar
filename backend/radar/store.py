"""Deduplicating writes. Every importer and collector goes through `upsert_finding`."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radar.models import Finding, FindingEvent, Link, Operator
from radar.normalize import EntityRef, identify

# Funnel order: a merge never moves an entity backwards in enforcement.
STATUS_RANK = {"false_positive": 0, "new": 1, "confirmed": 2, "reported": 3, "blocked": 4}
_ARRAY_FIELDS = ("tags", "matched_keywords", "brands", "media_urls", "review_reasons")
_METRIC_FIELDS = ("views", "followers", "subscribers", "likes")
_FILL_FIELDS = (
    "entity_type", "host", "handle", "title", "text", "landing_url", "landing_raw", "advertiser",
    "published_at", "operator_id", "category", "suggested_action", "original_status", "complaint_status",
    "is_live", "ai_label", "ai_score", "ai_reason",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def merge_status(a: str | None, b: str | None) -> str:
    a, b = a or "new", b or "new"
    return a if STATUS_RANK.get(a, 1) >= STATUS_RANK.get(b, 1) else b


def public_id_for(key: str) -> str:
    return "F" + hashlib.sha1(key.encode()).hexdigest()[:10]


@dataclass
class FindingIn:
    url: str
    source: str | None = None  # override identify() only when the caller knows better
    entity_type: str | None = None
    canonical_key: str | None = None
    host: str | None = None
    handle: str | None = None
    title: str | None = None
    text: str | None = None
    media_urls: list[str] = field(default_factory=list)
    landing_url: str | None = None
    landing_raw: str | None = None
    advertiser: str | None = None
    seen_at: datetime | None = None
    published_at: datetime | None = None
    operator_id: int | None = None
    brands: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    status: str | None = None
    original_status: str | None = None
    complaint_status: str | None = None
    is_live: bool | None = None
    category: str | None = None
    suggested_action: str | None = None
    category_suggested: bool = False
    tags: list[str] = field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    is_impersonation: bool = False
    views: int | None = None
    followers: int | None = None
    subscribers: int | None = None
    likes: int | None = None
    ai_label: str | None = None
    ai_score: float | None = None
    ai_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    enrichment: dict[str, Any] = field(default_factory=dict)
    origin: str | None = None
    public_id: str | None = None

    def resolve(self) -> EntityRef:
        ref = identify(self.url)
        return EntityRef(
            source=self.source or ref.source,
            entity_type=self.entity_type or ref.entity_type,
            key=self.canonical_key or ref.key,
            url=ref.url,
            host=self.host or ref.host,
            handle=self.handle or ref.handle,
        )


@dataclass
class UpsertResult:
    finding: Finding
    created: bool
    changed: bool


def _raw_id(raw: dict) -> dict:
    """Source record identity without the import batch, so re-importing a file adds nothing."""
    return {k: v for k, v in raw.items() if k != "import"}


def _union(a: list | None, b: list | None) -> list:
    out = list(a or [])
    for v in b or []:
        if v not in out:
            out.append(v)
    return out


def _apply(f: Finding, data: FindingIn, ref: EntityRef, *, is_new: bool, status_policy: str) -> bool:
    changed = False
    seen = data.seen_at or utcnow()

    def setv(name, value):
        nonlocal changed
        if getattr(f, name) != value:
            setattr(f, name, value)
            changed = True

    if is_new:
        f.source, f.canonical_key, f.url = ref.source, ref.key, ref.url
        f.public_id = data.public_id or public_id_for(ref.key)
        f.first_seen = f.last_seen = seen
        f.status = data.status or "new"
        f.raw = {"sources": [data.raw]} if data.raw else {}
        f.origin = data.origin
    else:
        if f.first_seen is None or seen < f.first_seen:
            setv("first_seen", seen)
        if f.last_seen is None or seen > f.last_seen:
            setv("last_seen", seen)
        if data.status and status_policy == "max":
            setv("status", merge_status(f.status, data.status))
        if data.raw:
            sources = list((f.raw or {}).get("sources", []))
            if _raw_id(data.raw) not in [_raw_id(x) for x in sources]:
                sources.append(data.raw)
                setv("raw", {**(f.raw or {}), "sources": sources})

    values = {"entity_type": ref.entity_type, "host": ref.host, "handle": ref.handle}
    for name in _FILL_FIELDS:
        v = values.get(name, getattr(data, name, None))
        if v is not None and v != "" and getattr(f, name) in (None, ""):
            setv(name, v)
    for name in _ARRAY_FIELDS:
        merged = _union(getattr(f, name), getattr(data, name))
        if merged != list(getattr(f, name) or []):
            setv(name, merged)
    for name in _METRIC_FIELDS:
        v = getattr(data, name)
        if v is not None and (getattr(f, name) is None or v > getattr(f, name)):
            setv(name, v)
    if data.enrichment:
        merged = dict(f.enrichment or {})
        for k, v in data.enrichment.items():
            merged[k] = {**merged.get(k, {}), **v} if isinstance(v, dict) and isinstance(merged.get(k), dict) else v
        if merged != (f.enrichment or {}):
            setv("enrichment", merged)
    if data.needs_review and not f.needs_review:
        setv("needs_review", True)
    if data.is_impersonation and not f.is_impersonation:
        setv("is_impersonation", True)
    if data.category and data.category_suggested is False and f.category_suggested:
        setv("category", data.category)
        setv("category_suggested", False)
    elif is_new:
        f.category_suggested = data.category_suggested
    return changed


def upsert_finding(session: Session, data: FindingIn, *, status_policy: str = "max", actor: str | None = None) -> UpsertResult:
    """Insert or merge a finding identified by its canonical key.

    status_policy: "max" merges status along the funnel (imports); "keep" never touches
    an existing status (collectors re-detecting an entity a human already labeled).
    """
    ref = data.resolve()
    existing = session.scalar(select(Finding).where(Finding.canonical_key == ref.key).with_for_update())
    if existing is None:
        f = Finding()
        _apply(f, data, ref, is_new=True, status_policy=status_policy)
        try:
            with session.begin_nested():
                session.add(f)
                session.flush()
        except IntegrityError:  # lost a race with another worker — merge instead
            existing = session.scalar(select(Finding).where(Finding.canonical_key == ref.key))
            if existing is None:
                raise
        else:
            session.add(FindingEvent(finding_id=f.id, kind="detected", actor=actor or data.origin,
                                     data={"url": data.url}))
            return UpsertResult(f, True, True)
    changed = _apply(existing, data, ref, is_new=False, status_policy=status_policy)
    session.add(FindingEvent(finding_id=existing.id, kind="redetected", actor=actor or data.origin,
                             data={"url": data.url, "changed": changed}))
    session.flush()
    return UpsertResult(existing, False, changed)


def add_link(session: Session, src_id: int, link_type: str, *, dst_id: int | None = None,
             operator_id: int | None = None, value: str = "", confidence: float = 1.0) -> None:
    stmt = pg_insert(Link).values(src_id=src_id, dst_id=dst_id, operator_id=operator_id,
                                  link_type=link_type, value=value or "", confidence=confidence)
    session.execute(stmt.on_conflict_do_nothing(constraint="uq_links_edge"))


def operator_index(session: Session) -> tuple[dict[str, list[str]], dict[str, int]]:
    ops = session.scalars(select(Operator)).all()
    aliases = {o.slug: list({o.name.lower(), *[a.lower() for a in o.aliases]}) for o in ops}
    ids = {o.slug: o.id for o in ops}
    return aliases, ids
