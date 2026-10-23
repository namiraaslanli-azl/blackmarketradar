"""Meta Ads Library (country = AZ) via Apify: keyword searches + tracked advertiser pages.

Advertiser names are random ("Lake Smith Farm"), so nothing relies on them: every image is
OCR'd and perceptually hashed, and ads are clustered by landing target, creative text and
image hash. Landing URLs become linked findings (Play Store app, Instagram account, domain)
through the linker, and the enrichment worker then follows the domains.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote_plus

from sqlalchemy.dialects.postgresql import insert as pg_insert

from radar.collectors.apify import Apify
from radar.collectors.base import Collector, Ctx
from radar.collectors.http import client, request
from radar.collectors.serp import rotate
from radar.evidence import store_capture
from radar.extract import match_keywords
from radar.importers.apify import _get, item_to_finding
from radar.models import TrackedTarget
from radar.store import add_link

LIBRARY = "https://www.facebook.com/ads/library/"


def keyword_url(q: str, country: str = "AZ") -> str:
    return (f"{LIBRARY}?active_status=active&ad_type=all&country={country}&q={quote_plus(q)}"
            "&search_type=keyword_unordered&media_type=all")


def page_url(page_id: str, country: str = "AZ") -> str:
    return f"{LIBRARY}?active_status=all&ad_type=all&country={country}&view_all_page_id={page_id}&search_type=page"


class MetaAdsCollector(Collector):
    name = "meta_ads"
    title = "Meta reklam kitabxanası (AZ)"
    schedule = {"minute": 35, "hour": "7,19"}
    requires = ("apify_token",)
    defaults = {
        "actor": "apify/facebook-ads-scraper",
        "max_keywords": 40,
        "results_per_url": 100,
        "max_images_per_ad": 3,
        "auto_track_pages": True,
        "auto_track_min_keywords": 2,
    }

    def build_urls(self, ctx: Ctx) -> list[str]:
        terms = [t for t in ctx.terms("generic", "promo", "game", "brand") if len(t) >= 4]
        urls = [keyword_url(t) for t in rotate(sorted(set(terms)), ctx.params["max_keywords"])]
        urls += [page_url(p) for p in ctx.targets.get("meta_page", [])]
        return urls

    def collect(self, ctx: Ctx) -> Iterable:
        urls = self.build_urls(ctx)
        items = Apify().run_actor(ctx.params["actor"], {
            "startUrls": [{"url": u} for u in urls],
            "resultsLimit": ctx.params["results_per_url"],
            "isDetailsPerAd": False,
        }, max_items=ctx.params["results_per_url"] * len(urls))
        terms = ctx.terms()
        for p in ctx.targets.get("meta_page", []):
            ctx.mark_target("meta_page", p)
        for item in items:
            fin = item_to_finding(item, f"collector:{self.name}")
            if fin is None:
                continue
            page_id = str(_get(item, "pageID", "pageId", "page_id", "snapshot.page_id", default="") or "")
            fin.raw = {"collector": self.name, "page_id": page_id or None, "item": item}
            fin.matched_keywords = match_keywords(" ".join(filter(None, [fin.title, fin.text])), terms)
            fin.tags = ["meta_ads_library"]
            yield fin

    def after_upsert(self, session, finding, item, ctx: Ctx) -> None:
        done = {i["url"] for i in (finding.enrichment or {}).get("ocr", {}).get("images", [])}
        todo = [u for u in (item.media_urls or []) if u not in done][: ctx.params["max_images_per_ad"]]
        if not todo:
            return
        from radar.ocr import read_image

        images = list((finding.enrichment or {}).get("ocr", {}).get("images", []))
        with client(timeout=30) as c:
            for url in todo:
                try:
                    content = request(c, "GET", url, retries=2).content
                    res = read_image(content)
                except Exception as exc:  # noqa: BLE001 — expired CDN links are common
                    ctx.error(f"ocr {finding.public_id}: {exc!r}"[:200])
                    continue
                store_capture(session, finding, "ad_image", content, url=url, meta={"phash": res["phash"]})
                add_link(session, finding.id, "image_hash", value=res["phash"])
                images.append({"url": url, **res, "at": datetime.now(timezone.utc).isoformat()})
        if images:
            finding.enrichment = {**(finding.enrichment or {}), "ocr": {"images": images}}
            ocr_kw = match_keywords(" ".join(i["text"] for i in images), ctx.terms())
            if ocr_kw:
                finding.matched_keywords = sorted(set(finding.matched_keywords or []) | set(ocr_kw))
                finding.tags = list(dict.fromkeys([*(finding.tags or []), "ocr_gambling_text"]))
        page_id = (item.raw or {}).get("page_id")
        if (ctx.params["auto_track_pages"] and page_id
                and len(finding.matched_keywords or []) >= ctx.params["auto_track_min_keywords"]):
            session.execute(pg_insert(TrackedTarget).values(
                kind="meta_page", value=page_id, note=f"auto: {finding.advertiser or ''}"[:200],
                source_finding_id=finding.id).on_conflict_do_nothing(constraint="uq_tracked_kind_value"))

    def after_run(self, ctx: Ctx, touched: list[int]) -> None:
        from radar.db import session_scope
        from radar.linker import recluster_ads

        with session_scope() as s:
            recluster_ads(s)
