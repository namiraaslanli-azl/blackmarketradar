"""HTTP API for the dashboard. Phase 1: findings, evidence, imports, runs, settings."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, any_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.db import session_factory
from radar.models import (
    SOURCES,
    STATUSES,
    CollectorRun,
    Evidence,
    Finding,
    FindingEvent,
    ImportBatch,
    Keyword,
    Link,
    Operator,
    WhitelistEntry,
)
from radar.quality import quality_report

BAKU = ZoneInfo("Asia/Baku")
app = FastAPI(title="Black Market Radar API", version="0.1.0")


def db():
    s = session_factory()()
    try:
        yield s
        s.commit()
    finally:
        s.close()


def auth(x_api_token: str | None = Header(default=None)):
    token = get_settings().api_token
    if token and x_api_token != token:
        raise HTTPException(401, "invalid token")


def date_range(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to")):
    """Inclusive local-date range in Asia/Baku → UTC datetimes. Default: last 30 days."""
    today = datetime.now(BAKU).date()
    end = end or today
    start = start or end - timedelta(days=29)
    lo = datetime.combine(start, time.min, BAKU).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, BAKU).astimezone(timezone.utc)
    return lo, hi, start, end


def finding_summary(f: Finding) -> dict:
    shot = next((e for e in f.evidence if e.kind == "screenshot"), None) if "evidence" in f.__dict__ else None
    return {
        "id": f.public_id, "source": f.source, "entity_type": f.entity_type, "url": f.url, "host": f.host,
        "handle": f.handle, "title": f.title, "text": (f.text or "")[:280] or None, "status": f.status,
        "operator": f.operator.name if f.operator else None, "brands": f.brands,
        "matched_keywords": f.matched_keywords, "ai_score": f.ai_score, "category": f.category,
        "category_suggested": f.category_suggested, "tags": f.tags, "needs_review": f.needs_review,
        "is_live": f.is_live, "is_impersonation": f.is_impersonation,
        "first_seen": f.first_seen, "last_seen": f.last_seen,
        "views": f.views, "followers": f.followers, "subscribers": f.subscribers, "likes": f.likes,
        "screenshot": shot.id if shot else None,
    }


@app.get("/api/health")
def health(s: Session = Depends(db)):
    s.execute(select(1))
    return {"ok": True}


@app.get("/api/overview", dependencies=[Depends(auth)])
def overview(rng=Depends(date_range), s: Session = Depends(db)):
    lo, hi, start, end = rng
    # imported history ("imported" tag) is backfill, not a detection in this period
    in_range = and_(Finding.first_seen >= lo, Finding.first_seen < hi, ~(literal("imported") == any_(Finding.tags)))
    total = s.scalar(select(func.count()).select_from(Finding))
    new = s.scalar(select(func.count()).select_from(Finding).where(in_range))
    by_source = dict(s.execute(select(Finding.source, func.count()).where(in_range).group_by(Finding.source)).all())
    by_status = dict(s.execute(select(Finding.status, func.count()).group_by(Finding.status)).all())
    day = func.date(func.timezone("Asia/Baku", Finding.first_seen))
    daily = [{"day": d.isoformat(), "count": c} for d, c in
             s.execute(select(day, func.count()).where(in_range).group_by(day).order_by(day)).all()]
    top_ops = [{"operator": n, "count": c} for n, c in s.execute(
        select(Operator.name, func.count()).join(Finding, Finding.operator_id == Operator.id)
        .where(Finding.status.in_(("confirmed", "reported", "blocked")))
        .group_by(Operator.name).order_by(func.count().desc()).limit(10)).all()]
    last_runs = s.execute(
        select(CollectorRun).ext(distinct_on(CollectorRun.collector))
        .order_by(CollectorRun.collector, CollectorRun.started_at.desc())).scalars().all()
    return {
        "range": {"from": start, "to": end},
        "imported": s.scalar(select(func.count()).select_from(Finding).where(literal("imported") == any_(Finding.tags))),
        "total": total, "new": new, "by_source": by_source, "by_status": by_status, "daily": daily,
        "top_operators": top_ops,
        "needs_review": s.scalar(select(func.count()).select_from(Finding).where(Finding.needs_review)),
        "impersonation": s.scalar(select(func.count()).select_from(Finding).where(Finding.is_impersonation)),
        "collectors": [{"collector": r.collector, "status": r.status, "started_at": r.started_at,
                        "items_found": r.items_found, "errors": r.errors, "duration_ms": r.duration_ms}
                       for r in last_runs],
    }


@app.get("/api/findings", dependencies=[Depends(auth)])
def list_findings(
    source: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    operator: str | None = None,
    q: str | None = None,
    review: bool | None = None,
    impersonation: bool | None = None,
    tag: str | None = None,
    in_range: bool = Query(False, description="restrict to first_seen inside from/to"),
    sort: str = "-last_seen",
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    rng=Depends(date_range),
    s: Session = Depends(db),
):
    lo, hi, *_ = rng
    where = []
    if source:
        where.append(Finding.source.in_(source))
    if status:
        where.append(Finding.status.in_(status))
    if operator:
        where.append(Finding.operator.has(Operator.slug == operator))
    if review is not None:
        where.append(Finding.needs_review.is_(review))
    if impersonation is not None:
        where.append(Finding.is_impersonation.is_(impersonation))
    if tag:
        where.append(tag == any_(Finding.tags))
    if in_range:
        where.append(and_(Finding.first_seen >= lo, Finding.first_seen < hi, ~(literal("imported") == any_(Finding.tags))))
    if q:
        like = f"%{q.lower()}%"
        where.append(or_(func.lower(Finding.url).like(like), func.lower(Finding.title).like(like),
                         func.lower(Finding.text).like(like), func.lower(Finding.handle).like(like),
                         Finding.public_id == q, q.lower() == any_(Finding.matched_keywords),
                         Finding.id.in_(select(Link.src_id).where(func.lower(Link.value) == q.lower()))))
    col = {"last_seen": Finding.last_seen, "first_seen": Finding.first_seen, "ai_score": Finding.ai_score,
           "views": Finding.views, "subscribers": Finding.subscribers, "host": Finding.host}.get(sort.lstrip("-"), Finding.last_seen)
    order = col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last()
    total = s.scalar(select(func.count()).select_from(Finding).where(*where))
    rows = s.scalars(select(Finding).where(*where).order_by(order, Finding.id.desc())
                     .offset((page - 1) * limit).limit(limit)).all()
    shots = dict(s.execute(
        select(Evidence.finding_id, func.max(Evidence.id)).where(Evidence.kind == "screenshot",
                                                                 Evidence.finding_id.in_([r.id for r in rows]))
        .group_by(Evidence.finding_id)).all()) if rows else {}
    items = []
    for r in rows:
        d = finding_summary(r)
        d["screenshot"] = shots.get(r.id)
        items.append(d)
    return {"total": total, "page": page, "limit": limit, "items": items}


@app.get("/api/findings/{public_id}", dependencies=[Depends(auth)])
def get_finding(public_id: str, s: Session = Depends(db)):
    f = s.scalar(select(Finding).where(Finding.public_id == public_id))
    if not f:
        raise HTTPException(404)
    out_links = s.execute(select(Link, Finding).outerjoin(Finding, Finding.id == Link.dst_id)
                          .where(Link.src_id == f.id)).all()
    in_links = s.execute(select(Link, Finding).join(Finding, Finding.id == Link.src_id)
                         .where(Link.dst_id == f.id)).all()
    events = s.scalars(select(FindingEvent).where(FindingEvent.finding_id == f.id)
                       .order_by(FindingEvent.at.desc()).limit(100)).all()

    def link_dict(link: Link, other: Finding | None, direction: str):
        return {"type": link.link_type, "value": link.value, "direction": direction,
                "finding": {"id": other.public_id, "source": other.source, "url": other.url,
                            "status": other.status} if other else None}

    return {
        **finding_summary(f), "text": f.text, "landing_url": f.landing_url, "landing_raw": f.landing_raw,
        "advertiser": f.advertiser, "media_urls": f.media_urls, "suggested_action": f.suggested_action,
        "original_status": f.original_status, "complaint_status": f.complaint_status,
        "review_reasons": f.review_reasons, "ai_label": f.ai_label, "ai_reason": f.ai_reason,
        "published_at": f.published_at, "enrichment": f.enrichment, "enriched_at": f.enriched_at, "raw": f.raw,
        "evidence": [{"id": e.id, "kind": e.kind, "url": e.url, "sha256": e.sha256, "bytes": e.bytes,
                      "captured_at": e.captured_at} for e in f.evidence],
        "links": [link_dict(l, o, "out") for l, o in out_links] + [link_dict(l, o, "in") for l, o in in_links],
        "events": [{"at": e.at, "kind": e.kind, "actor": e.actor, "data": e.data} for e in events],
    }


class StatusIn(BaseModel):
    status: str = Field(pattern="|".join(STATUSES))
    actor: str | None = None


@app.post("/api/findings/{public_id}/status", dependencies=[Depends(auth)])
def set_status(public_id: str, body: StatusIn, s: Session = Depends(db)):
    f = s.scalar(select(Finding).where(Finding.public_id == public_id))
    if not f:
        raise HTTPException(404)
    old = f.status
    now = datetime.now(timezone.utc)
    f.status, f.status_changed_at, f.needs_review = body.status, now, False
    stamp = {"confirmed": "confirmed_at", "reported": "reported_at", "blocked": "blocked_at"}.get(body.status)
    if stamp and getattr(f, stamp) is None:
        setattr(f, stamp, now)
    s.add(FindingEvent(finding_id=f.id, kind="status", actor=body.actor, data={"from": old, "to": body.status}))
    return {"id": public_id, "status": f.status}


@app.get("/api/evidence/{evidence_id}", dependencies=[Depends(auth)])
def evidence_file(evidence_id: int, s: Session = Depends(db)):
    e = s.get(Evidence, evidence_id)
    if not e:
        raise HTTPException(404)
    root = get_settings().evidence_dir.resolve()
    path = (root / e.path).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(404)
    media = {"screenshot": "image/png", "favicon": "image/x-icon"}.get(e.kind, "text/plain; charset=utf-8")
    return FileResponse(path, media_type=media, headers={"X-Evidence-SHA256": e.sha256})


@app.get("/api/imports", dependencies=[Depends(auth)])
def imports(s: Session = Depends(db)):
    return [{"id": b.id, "kind": b.kind, "filename": b.filename, "sha256": b.sha256, "started_at": b.started_at,
             "report": b.report} for b in s.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()))]


@app.get("/api/quality", dependencies=[Depends(auth)])
def quality(s: Session = Depends(db)):
    return quality_report(s)


@app.get("/api/runs", dependencies=[Depends(auth)])
def runs(collector: str | None = None, limit: int = 100, s: Session = Depends(db)):
    q = select(CollectorRun).order_by(CollectorRun.started_at.desc()).limit(limit)
    if collector:
        q = q.where(CollectorRun.collector == collector)
    return [{"id": r.id, "collector": r.collector, "started_at": r.started_at, "finished_at": r.finished_at,
             "status": r.status, "items_found": r.items_found, "items_new": r.items_new,
             "items_updated": r.items_updated, "errors": r.errors, "duration_ms": r.duration_ms,
             "error_log": r.error_log} for r in s.scalars(q)]


@app.get("/api/operators", dependencies=[Depends(auth)])
def operators(s: Session = Depends(db)):
    counts = dict(s.execute(select(Finding.operator_id, func.count()).group_by(Finding.operator_id)).all())
    return [{"slug": o.slug, "name": o.name, "aliases": o.aliases, "is_licensed": o.is_licensed,
             "findings": counts.get(o.id, 0)} for o in s.scalars(select(Operator).order_by(Operator.name))]


# --- Settings: keywords & whitelist -------------------------------------------------------

class KeywordIn(BaseModel):
    term: str = Field(min_length=2, max_length=120)
    kind: str = "generic"
    lang: str | None = None


@app.get("/api/settings/keywords", dependencies=[Depends(auth)])
def keywords(s: Session = Depends(db)):
    return [{"id": k.id, "term": k.term, "kind": k.kind, "lang": k.lang, "active": k.active}
            for k in s.scalars(select(Keyword).order_by(Keyword.kind, Keyword.term))]


@app.post("/api/settings/keywords", dependencies=[Depends(auth)])
def add_keyword(body: KeywordIn, s: Session = Depends(db)):
    s.execute(pg_insert(Keyword).values(term=body.term.strip().lower(), kind=body.kind, lang=body.lang)
              .on_conflict_do_update(index_elements=["term"], set_={"active": True, "kind": body.kind}))
    return {"ok": True}


@app.delete("/api/settings/keywords/{keyword_id}", dependencies=[Depends(auth)])
def delete_keyword(keyword_id: int, s: Session = Depends(db)):
    k = s.get(Keyword, keyword_id)
    if k:
        s.delete(k)
    return {"ok": True}


class WhitelistIn(BaseModel):
    kind: str = Field(pattern="domain|handle|app|brand")
    value: str = Field(min_length=2)
    owner: str
    note: str | None = None


@app.get("/api/settings/whitelist", dependencies=[Depends(auth)])
def whitelist(s: Session = Depends(db)):
    return [{"id": w.id, "kind": w.kind, "value": w.value, "owner": w.owner, "note": w.note}
            for w in s.scalars(select(WhitelistEntry).order_by(WhitelistEntry.owner, WhitelistEntry.kind))]


@app.post("/api/settings/whitelist", dependencies=[Depends(auth)])
def add_whitelist(body: WhitelistIn, s: Session = Depends(db)):
    s.execute(pg_insert(WhitelistEntry).values(kind=body.kind, value=body.value.strip().lower(), owner=body.owner,
                                               note=body.note).on_conflict_do_nothing(constraint="uq_whitelist_kind_value"))
    return {"ok": True}


@app.delete("/api/settings/whitelist/{entry_id}", dependencies=[Depends(auth)])
def delete_whitelist(entry_id: int, s: Session = Depends(db)):
    w = s.get(WhitelistEntry, entry_id)
    if w:
        s.delete(w)
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return {"sources": SOURCES, "statuses": STATUSES}


# --- Collectors & tracked targets (Phase 2) -------------------------------------------------

def _crontab_text(c: dict) -> str:
    return f"{c.get('minute', '*')} {c.get('hour', '*')} * * *" if c else "—"


@app.get("/api/collectors", dependencies=[Depends(auth)])
def collectors_list(s: Session = Depends(db)):
    from radar.collectors import REGISTRY
    from radar.collectors.base import effective_params

    week = datetime.now(timezone.utc) - timedelta(days=7)
    totals = {c: (f, n, e) for c, f, n, e in s.execute(
        select(CollectorRun.collector, func.sum(CollectorRun.items_found), func.sum(CollectorRun.items_new),
               func.sum(CollectorRun.errors)).where(CollectorRun.started_at >= week).group_by(CollectorRun.collector))}
    last = {r.collector: r for r in s.execute(
        select(CollectorRun).ext(distinct_on(CollectorRun.collector))
        .order_by(CollectorRun.collector, CollectorRun.started_at.desc())).scalars()}
    out = []
    for name, c in REGISTRY.items():
        enabled, params = effective_params(s, c)
        r = last.get(name)
        f, n, e = totals.get(name, (0, 0, 0))
        out.append({
            "name": name, "title": c.title, "schedule": _crontab_text(c.schedule), "enabled": enabled,
            "params": params, "missing": c.missing_secrets(),
            "last_run": {"status": r.status, "started_at": r.started_at, "items_found": r.items_found,
                         "items_new": r.items_new, "errors": r.errors, "duration_ms": r.duration_ms} if r else None,
            "week": {"found": int(f or 0), "new": int(n or 0), "errors": int(e or 0)},
        })
    return out


class CollectorUpdate(BaseModel):
    enabled: bool | None = None
    params: dict | None = None


@app.put("/api/collectors/{name}", dependencies=[Depends(auth)])
def collector_update(name: str, body: CollectorUpdate, s: Session = Depends(db)):
    from radar.collectors import REGISTRY
    from radar.models import CollectorConfig

    c = REGISTRY.get(name)
    if not c:
        raise HTTPException(404)
    unknown = set(body.params or {}) - set(c.defaults)
    if unknown:
        raise HTTPException(422, f"unknown params: {', '.join(sorted(unknown))}")
    cfg = s.get(CollectorConfig, name) or CollectorConfig(name=name, enabled=True, params={})
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.params:
        cfg.params = {**(cfg.params or {}), **body.params}
    s.add(cfg)
    return {"ok": True}


@app.post("/api/collectors/{name}/run", dependencies=[Depends(auth)])
def collector_run_now(name: str):
    from radar.collectors import REGISTRY
    from radar.tasks import collect

    if name not in REGISTRY:
        raise HTTPException(404)
    task = collect.delay(name, force=True)
    return {"queued": True, "task_id": task.id}


class TargetIn(BaseModel):
    kind: str
    value: str = Field(min_length=2, max_length=200)
    note: str | None = None


@app.get("/api/settings/targets", dependencies=[Depends(auth)])
def targets(s: Session = Depends(db)):
    from radar.models import TrackedTarget

    return [{"id": t.id, "kind": t.kind, "value": t.value, "note": t.note, "active": t.active,
             "last_collected_at": t.last_collected_at}
            for t in s.scalars(select(TrackedTarget).order_by(TrackedTarget.kind, TrackedTarget.value))]


@app.post("/api/settings/targets", dependencies=[Depends(auth)])
def add_target(body: TargetIn, s: Session = Depends(db)):
    from radar.models import TARGET_KINDS, TrackedTarget

    if body.kind not in TARGET_KINDS:
        raise HTTPException(422, "bad kind")
    value = body.value.strip().lstrip("@#")
    for prefix in ("https://", "http://", "www.", "t.me/", "tiktok.com/@", "instagram.com/", "facebook.com/"):
        value = value.removeprefix(prefix)
    s.execute(pg_insert(TrackedTarget).values(kind=body.kind, value=value.strip("/"), note=body.note)
              .on_conflict_do_update(constraint="uq_tracked_kind_value", set_={"active": True}))
    return {"ok": True}


@app.delete("/api/settings/targets/{target_id}", dependencies=[Depends(auth)])
def delete_target(target_id: int, s: Session = Depends(db)):
    from radar.models import TrackedTarget

    t = s.get(TrackedTarget, target_id)
    if t:
        s.delete(t)
    return {"ok": True}
