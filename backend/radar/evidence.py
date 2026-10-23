"""Evidence storage: every capture is written once, hashed (SHA-256) and timestamped."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from radar.config import get_settings
from radar.models import Evidence, Finding

EXT = {"screenshot": "png", "html": "html", "favicon": "ico", "rendered_html": "html", "ad_image": "jpg", "thumbnail": "jpg"}


def store_capture(session: Session, finding: Finding, kind: str, content: bytes, *, url: str | None = None,
                  meta: dict | None = None, root: Path | None = None) -> Evidence:
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(content).hexdigest()
    root = root or get_settings().evidence_dir
    rel = Path(f"{now:%Y/%m}") / finding.public_id / f"{now:%Y%m%dT%H%M%SZ}-{kind}-{digest[:12]}.{EXT.get(kind, 'bin')}"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    ev = Evidence(finding_id=finding.id, kind=kind, url=url, path=str(rel), sha256=digest, bytes=len(content),
                  captured_at=now, meta=meta or {})
    session.add(ev)
    return ev
