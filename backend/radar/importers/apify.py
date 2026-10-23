"""Import Apify dataset exports (JSON or CSV) from the actors we use.

Recognized item shapes (detected per item, so a mixed file is fine):
  * Facebook Ads Library  — adArchiveID / ad_archive_id, snapshot.body.text, snapshot.link_url
  * TikTok                — webVideoUrl, playCount, authorMeta
  * Instagram post        — shortCode / url, ownerUsername, likesCount, videoViewCount
  * Instagram profile     — username, followersCount, biography
  * Facebook post         — postId / url, text, likes
Collectors in Phase 2 reuse `item_to_finding` on live actor output.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from radar.importers.common import file_sha256, parse_date, parse_int
from radar.models import ImportBatch
from radar.normalize import NotAUrl, clean_raw_url, is_valid_url
from radar.store import FindingIn, upsert_finding


def _get(d: dict, *paths: str, default=None):
    for p in paths:
        cur: Any = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return default


def _unflatten(row: dict) -> dict:
    """Apify CSV exports flatten nested keys as 'a/b/0/c'."""
    out: dict = {}
    for k, v in row.items():
        if v in (None, ""):
            continue
        cur = out
        parts = k.split("/")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
            if not isinstance(cur, dict):
                break
        else:
            cur[parts[-1]] = v
    return out


def detect_kind(item: dict) -> str | None:
    if _get(item, "adArchiveID", "ad_archive_id", "adArchiveId") or "ads/library" in str(item.get("url", "")):
        return "meta_ad"
    if _get(item, "webVideoUrl") or _get(item, "authorMeta.name"):
        return "tiktok_post"
    if _get(item, "followersCount") is not None and _get(item, "username"):
        return "instagram_account"
    if _get(item, "shortCode", "ownerUsername"):
        return "instagram_post"
    if _get(item, "postId", "facebookUrl", "pageName") and "facebook.com" in str(_get(item, "url", "facebookUrl", default="")):
        return "facebook_post"
    return None


def item_to_finding(item: dict, origin: str) -> FindingIn | None:
    kind = detect_kind(item)
    if kind == "meta_ad":
        ad_id = str(_get(item, "adArchiveID", "ad_archive_id", "adArchiveId", default="")).strip()
        url = f"https://www.facebook.com/ads/library/?id={ad_id}" if ad_id else item.get("url")
        body = _get(item, "snapshot.body.text", "snapshot.body.markup.__html", "snapshot.cards.0.body", "body")
        title = _get(item, "snapshot.title", "snapshot.cards.0.title", "title")
        landing = _get(item, "snapshot.link_url", "snapshot.cards.0.link_url", "linkUrl", "link_url")
        images = [
            _get(i, "original_image_url", "resized_image_url")
            for i in (_get(item, "snapshot.images", default=[]) or []) + (_get(item, "snapshot.cards", default=[]) or [])
            if isinstance(i, dict)
        ]
        images += [_get(v, "video_preview_image_url") for v in _get(item, "snapshot.videos", default=[]) or [] if isinstance(v, dict)]
        return FindingIn(
            url=url, title=title, text=body,
            advertiser=_get(item, "pageName", "page_name", "snapshot.page_name"),
            landing_url=clean_raw_url(landing) if is_valid_url(landing) else None, landing_raw=landing,
            published_at=parse_date(_get(item, "startDate", "start_date", "startDateFormatted")),
            media_urls=[i for i in images if i],
            is_live=bool(_get(item, "isActive", "is_active", default=True)),
            raw=item, origin=origin,
        )
    if kind == "tiktok_post":
        author = _get(item, "authorMeta.name", "author.uniqueId")
        return FindingIn(
            url=_get(item, "webVideoUrl", "url"), text=_get(item, "text", "desc"), handle=author,
            title=_get(item, "authorMeta.nickName"),
            published_at=parse_date(_get(item, "createTimeISO", "createTime")),
            views=parse_int(_get(item, "playCount")), likes=parse_int(_get(item, "diggCount")),
            followers=parse_int(_get(item, "authorMeta.fans")),
            media_urls=[u for u in [_get(item, "videoMeta.coverUrl", "covers.0")] if u],
            raw=item, origin=origin,
        )
    if kind == "instagram_account":
        user = _get(item, "username")
        return FindingIn(
            url=_get(item, "url", default=f"https://www.instagram.com/{user}/"), handle=user,
            title=_get(item, "fullName"), text="\n".join(filter(None, [_get(item, "biography"), _get(item, "externalUrl")])),
            followers=parse_int(_get(item, "followersCount")),
            media_urls=[u for u in [_get(item, "profilePicUrlHD", "profilePicUrl")] if u],
            raw=item, origin=origin,
        )
    if kind == "instagram_post":
        code = _get(item, "shortCode")
        return FindingIn(
            url=_get(item, "url", default=f"https://www.instagram.com/p/{code}/"), handle=_get(item, "ownerUsername"),
            text=_get(item, "caption"), published_at=parse_date(_get(item, "timestamp")),
            views=parse_int(_get(item, "videoViewCount", "videoPlayCount")), likes=parse_int(_get(item, "likesCount")),
            media_urls=[u for u in [_get(item, "displayUrl")] if u], raw=item, origin=origin,
        )
    if kind == "facebook_post":
        return FindingIn(
            url=_get(item, "url", "facebookUrl"), text=_get(item, "text", "postText"),
            title=_get(item, "pageName"), published_at=parse_date(_get(item, "time", "timestamp")),
            likes=parse_int(_get(item, "likes", "reactionsCount")), views=parse_int(_get(item, "viewsCount")),
            media_urls=[u for u in [_get(item, "media.0.thumbnail", "media.0.photo_image.uri")] if u],
            raw=item, origin=origin,
        )
    return None


def load_items(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return [_unflatten(r) for r in csv.DictReader(fh)]
    text = path.read_text(encoding="utf-8-sig").strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]  # JSONL


def import_apify(session: Session, path: Path) -> ImportBatch:
    batch = ImportBatch(kind="apify", filename=path.name, sha256=file_sha256(path))
    session.add(batch)
    session.flush()
    origin = f"import:apify:{batch.id}"
    stats, by_kind = Counter(), Counter()
    unknown: list[str] = []
    for item in load_items(path):
        stats["rows_read"] += 1
        fin = item_to_finding(item, origin)
        if fin is None or not fin.url:
            stats["unrecognized"] += 1
            if len(unknown) < 5:
                unknown.append(", ".join(list(item)[:12]))
            continue
        try:
            res = upsert_finding(session, fin, status_policy="keep")
        except NotAUrl:
            stats["skipped_invalid_url"] += 1
            continue
        by_kind[res.finding.source] += 1
        stats["created" if res.created else "merged_into_existing"] += 1
    batch.report = {**stats, "by_source": dict(by_kind), "unrecognized_samples": unknown}
    session.flush()
    return batch
