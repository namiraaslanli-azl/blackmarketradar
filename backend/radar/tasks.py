"""Celery app, tasks and the beat schedule.

Collectors (Phase 2) register here as tasks with retry/backoff and a schedule entry.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from radar.config import get_settings

settings = get_settings()
celery = Celery("radar", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    timezone="Asia/Baku",
    task_routes={"radar.tasks.enrich_*": {"queue": "enrich"}},
    beat_schedule={
        "enrich-due-domains": {"task": "radar.tasks.enrich_due", "schedule": crontab(minute=15, hour="*/3")},
        "relink": {"task": "radar.tasks.relink", "schedule": crontab(minute=40, hour="*/6")},
    },
)

RETRY = dict(autoretry_for=(Exception,), retry_backoff=30, retry_backoff_max=1800, retry_jitter=True, max_retries=5)


@celery.task(name="radar.tasks.enrich_finding", **RETRY, rate_limit="30/m")
def enrich_finding_task(finding_id: int, screenshot: bool = True) -> dict:
    from radar.enrichment.worker import enrich_one, http_client, preflight, screenshot_many

    with http_client() as client:
        preflight(client)  # raises → Celery retries later instead of storing false "dead" results
        res = enrich_one(finding_id, client)
    if screenshot and settings.screenshot_enabled and res["live"]:
        screenshot_many([finding_id])
    return res


@celery.task(name="radar.tasks.enrich_due")
def enrich_due(limit: int = 300) -> int:
    from radar.db import session_scope
    from radar.enrichment.worker import due_domain_ids

    with session_scope() as s:
        ids = due_domain_ids(s, limit=limit)
    for i in ids:
        enrich_finding_task.delay(i)
    return len(ids)


@celery.task(name="radar.tasks.relink", **RETRY)
def relink() -> dict:
    from radar.db import session_scope
    from radar.linker import run_linker
    from radar.runs import track_run

    with track_run("linker") as stats, session_scope() as s:
        rep = run_linker(s)
        stats.found = rep.processed
        stats.new = sum(rep.derived_created.values())
        return rep.as_dict()
