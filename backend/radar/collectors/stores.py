"""Play Store and App Store, country = AZ.

Keyword search finds gambling apps; apps already known (mostly Meta ad landings) are
re-checked for details or removal. Apps whose store category is not casino but whose
title / description talk about real-money play are tagged `disguised_game` — the common
pattern of "puzzle" apps that switch to a casino after install.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select

from radar.collectors.base import Collector, Ctx
from radar.collectors.http import client, request
from radar.collectors.serp import rotate
from radar.db import session_scope
from radar.extract import match_keywords
from radar.models import Finding
from radar.store import FindingIn

WEAK = {"bonus", "slot", "bet", "poker", "jackpot", "depozit", "spin"}
REAL_MONEY = ("real pul", "pul qazan", "реальные деньги", "gerçek para", "real money", "azn", "manat", "çıxarış",
              "вывод", "depozit", "promo kod", "promokod")


def app_signals(title: str, description: str, genre: str | None, terms: list[str]) -> tuple[list[str], list[str]]:
    text = f"{title}\n{description}"
    kws = match_keywords(text, terms)
    strong = [k for k in kws if k not in WEAK]
    tags: list[str] = []
    is_casino_genre = (genre or "").upper() in ("GAME_CASINO", "CASINO") or "casino" in (genre or "").lower()
    money = any(m in text.lower() for m in REAL_MONEY)
    if is_casino_genre and (strong or money):
        tags.append("gambling_app")
    elif not is_casino_genre and strong and (money or len(strong) >= 2):
        tags.append("disguised_game")
    return kws, tags


def play_finding(d: dict, terms: list[str], query: str | None = None) -> FindingIn:
    kws, tags = app_signals(d.get("title") or "", d.get("description") or "", d.get("genreId"), terms)
    released = d.get("released")
    return FindingIn(
        url=f"https://play.google.com/store/apps/details?id={d['appId']}", title=d.get("title"),
        text=(d.get("description") or "")[:4000] or None, matched_keywords=kws, tags=["play_store", *tags],
        is_live=True, media_urls=[u for u in [d.get("icon")] if u],
        raw={"collector": "stores", "query": query, "developer": d.get("developer"),
             "developer_email": d.get("developerEmail"), "developer_website": d.get("developerWebsite"),
             "genre": d.get("genreId"), "installs": d.get("realInstalls") or d.get("installs"),
             "released": released, "updated": d.get("updated"), "score": d.get("score")},
    )


def appstore_finding(d: dict, terms: list[str], query: str | None = None) -> FindingIn:
    kws, tags = app_signals(d.get("trackName") or "", d.get("description") or "", d.get("primaryGenreName"), terms)
    return FindingIn(
        url=f"https://apps.apple.com/az/app/id{d['trackId']}", title=d.get("trackName"),
        text=(d.get("description") or "")[:4000] or None, matched_keywords=kws, tags=["app_store", *tags],
        is_live=True, likes=d.get("userRatingCount"), media_urls=[u for u in [d.get("artworkUrl512")] if u],
        raw={"collector": "stores", "query": query, "developer": d.get("sellerName"),
             "genre": d.get("primaryGenreName"), "released": d.get("releaseDate")},
    )


def known_apps(source: str, limit: int) -> list[str]:
    with session_scope() as s:
        return [h for h in s.scalars(select(Finding.handle).where(
            Finding.source == source, Finding.handle.is_not(None), Finding.status != "false_positive")
            .order_by(Finding.last_seen.asc()).limit(limit)) if h]


class StoresCollector(Collector):
    name = "stores"
    title = "Play Store və App Store (AZ)"
    schedule = {"minute": 15, "hour": "11"}
    defaults = {"max_queries": 30, "hits_per_query": 30, "recheck_known": 200, "pause_seconds": 1.5}

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        import google_play_scraper as gps
        from google_play_scraper.exceptions import NotFoundError

        p, terms = ctx.params, ctx.terms()
        queries = rotate(sorted({t for t in ctx.terms("generic", "promo", "game", "brand") if len(t) >= 4}), p["max_queries"])
        now = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        # Play Store search → details
        for q in queries:
            try:
                hits = gps.search(q, lang="az", country="az", n_hits=p["hits_per_query"])
            except Exception as exc:  # noqa: BLE001
                ctx.error(f"play search {q}: {exc!r}"[:200])
                continue
            for h in hits:
                app_id = h.get("appId")
                if not app_id or app_id in seen:
                    continue
                seen.add(app_id)
                if not match_keywords(f"{h.get('title')} {h.get('description') or ''}", terms):
                    continue
                try:
                    d = gps.app(app_id, lang="az", country="az")
                except Exception:  # noqa: BLE001 — fall back to the search hit
                    d = h
                fin = play_finding(d, terms, q)
                if fin.matched_keywords:
                    yield fin
        # re-check known Play apps (from ad landings, history)
        for app_id in known_apps("play_store_app", p["recheck_known"]):
            if app_id in seen:
                continue
            try:
                d = gps.app(app_id, lang="az", country="az")
                fin = play_finding(d, terms)
            except NotFoundError:
                fin = FindingIn(url=f"https://play.google.com/store/apps/details?id={app_id}", is_live=False,
                                tags=["removed_from_store"], raw={"collector": "stores", "removed_check": now})
            except Exception as exc:  # noqa: BLE001
                ctx.error(f"play app {app_id}: {exc!r}"[:200])
                continue
            fin.enrichment = {"store": {"checked_at": now}}
            yield fin
        # App Store (iTunes Search / Lookup API)
        with client(timeout=30) as c:
            for q in queries:
                try:
                    res = request(c, "GET", "https://itunes.apple.com/search", min_interval=p["pause_seconds"], params={
                        "term": q, "country": "az", "entity": "software", "limit": 50}).json().get("results", [])
                except Exception as exc:  # noqa: BLE001
                    ctx.error(f"appstore {q}: {exc!r}"[:200])
                    continue
                for d in res:
                    fin = appstore_finding(d, terms, q)
                    if [k for k in fin.matched_keywords if k not in WEAK]:
                        yield fin
            ids = known_apps("app_store_app", p["recheck_known"])
            for i in range(0, len(ids), 100):
                chunk = ids[i:i + 100]
                try:
                    found = request(c, "GET", "https://itunes.apple.com/lookup", params={
                        "id": ",".join(chunk), "country": "az"}).json().get("results", [])
                except Exception as exc:  # noqa: BLE001
                    ctx.error(f"appstore lookup: {exc!r}"[:200])
                    continue
                alive = {str(d["trackId"]) for d in found}
                for d in found:
                    yield appstore_finding(d, terms)
                for missing in set(chunk) - alive:
                    yield FindingIn(url=f"https://apps.apple.com/az/app/id{missing}", is_live=False,
                                    tags=["removed_from_store"], raw={"collector": "stores", "removed_check": now})
