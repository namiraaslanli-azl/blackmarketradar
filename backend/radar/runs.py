"""collector_runs logging. Wrap every collector / worker batch in `track_run`."""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone

from radar.db import session_scope
from radar.models import CollectorRun


class RunStats:
    def __init__(self) -> None:
        self.found = self.new = self.updated = self.errors = 0
        self.error_lines: list[str] = []

    def error(self, msg: str) -> None:
        self.errors += 1
        if len(self.error_lines) < 50:
            self.error_lines.append(msg[:500])


@contextmanager
def track_run(collector: str, params: dict | None = None):
    with session_scope() as s:
        run = CollectorRun(collector=collector, params=params or {}, status="running")
        s.add(run)
        s.flush()
        run_id = run.id
    stats = RunStats()
    t0 = time.monotonic()
    status = "ok"
    try:
        yield stats
    except Exception:
        status = "failed"
        stats.error(traceback.format_exc())
        raise
    finally:
        if status == "ok" and stats.errors:
            status = "partial"
        with session_scope() as s:
            run = s.get(CollectorRun, run_id)
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.monotonic() - t0) * 1000)
            run.status = status
            run.items_found, run.items_new, run.items_updated = stats.found, stats.new, stats.updated
            run.errors = stats.errors
            run.error_log = "\n".join(stats.error_lines) or None
