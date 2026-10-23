"""Organic social collectors via Apify: TikTok, Instagram, Facebook.

Each collects by hashtag, keyword and tracked account. Posts are stored with their view /
like counts, and every post is linked to its author account (which carries followers), so
the influencer tracker and exposure index can aggregate reach per account and operator.
"""

from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import select

from radar.collectors.apify import Apify
from radar.collectors.base import Collector, Ctx
from radar.collectors.serp import rotate
from radar.db import session_scope
from radar.extract import match_keywords
from radar.importers.apify import _get, item_to_finding
from radar.models import Finding
from radar.store import FindingIn, add_link, upsert_finding

AZ_MARKERS = re.compile(r"[əƏ]|azərbaycan|azerbaycan|azerbaijan|\bazn\b|manat|bakı|baku|\baz\b|🇦🇿", re.I)
PROMO_SELLER = re.compile(r"kod\s*sat|resmi\s*kod|rəsmi\s*kod|promo\s*kod|promokod|промокод|\bkod\b", re.I)


def looks_az(text: str) -> bool:
    return bool(AZ_MARKERS.search(text or ""))


def hashtags_from_terms(terms: list[str]) -> list[str]:
    tags = {re.sub(r"[^0-9a-zəğıöşüç]", "", t.lower()) for t in terms}
    return sorted(t for t in tags if 4 <= len(t) <= 30)


def known_handles(source: str, limit: int) -> list[str]:
    """Accounts already confirmed or under review: re-check them every run."""
    with session_scope() as s:
        rows = s.scalars(select(Finding.handle).where(
            Finding.source == source, Finding.handle.is_not(None),
            Finding.status.in_(("new", "confirmed", "reported"))).order_by(Finding.last_seen.desc()).limit(limit))
        return [h for h in rows if h]


def keep_post(fin: FindingIn, terms: list[str], tracked: set[str]) -> bool:
    text = " ".join(filter(None, [fin.text, fin.title, fin.handle]))
    fin.matched_keywords = match_keywords(text, terms)
    if (fin.handle or "").lower() in tracked:
        return True
    return bool(fin.matched_keywords) and looks_az(text)


class _SocialCollector(Collector):
    account_source: str = ""
    account_url: str = ""

    def link_author(self, session, finding: Finding, item: FindingIn, followers: int | None) -> None:
        if not finding.handle or finding.source == self.account_source:
            return
        promo = bool(PROMO_SELLER.search(item.text or ""))
        acc = upsert_finding(session, FindingIn(
            url=self.account_url.format(h=finding.handle), followers=followers, operator_id=finding.operator_id,
            tags=["promo_code_seller"] if promo else [], origin=f"collector:{self.name}",
            raw={"collector": self.name, "via_post": finding.public_id},
        ), status_policy="keep", actor=self.name).finding
        add_link(session, finding.id, "linked_account", dst_id=acc.id, value=finding.handle)
        if promo:
            finding.tags = list(dict.fromkeys([*(finding.tags or []), "promo_code_seller"]))


class TikTokCollector(_SocialCollector):
    name = "tiktok"
    title = "TikTok (hashtag, axtarış, hesablar)"
    schedule = {"minute": 50, "hour": "8,20"}
    requires = ("apify_token",)
    account_source = "tiktok_account"
    account_url = "https://www.tiktok.com/@{h}"
    defaults = {
        "actor": "clockworks/tiktok-scraper",
        "hashtags": ["kazino", "kazinokod", "kodsatisi", "promokod", "aviator", "mostbet", "pinup", "1win", "pinco",
                     "melbet", "1xbet", "mərc", "slot", "kazinoazerbaycan", "bonuskod"],
        "max_search": 20, "max_profiles": 150, "results_per_page": 30,
    }

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        p = ctx.params
        tracked = {h.lower() for h in ctx.targets.get("tiktok_account", [])}
        profiles = sorted(tracked | {h.lower() for h in known_handles("tiktok_account", p["max_profiles"])})
        hashtags = sorted(set(p["hashtags"]) | set(ctx.targets.get("hashtag", [])))
        searches = rotate(sorted({t for t in ctx.terms("promo", "brand", "game") if len(t) >= 4}), p["max_search"])
        items = Apify().run_actor(p["actor"], {
            "hashtags": hashtags, "searchQueries": searches, "profiles": profiles,
            "resultsPerPage": p["results_per_page"], "shouldDownloadVideos": False, "shouldDownloadCovers": False,
            "shouldDownloadSubtitles": False, "proxyCountryCode": "AZ",
        })
        for h in tracked:
            ctx.mark_target("tiktok_account", h)
        terms = ctx.terms()
        for item in items:
            fin = item_to_finding(item, f"collector:{self.name}")
            if fin is None or not keep_post(fin, terms, set(profiles)):
                continue
            fin.raw = {"collector": self.name, "author_fans": _get(item, "authorMeta.fans"),
                       "hashtags": [h.get("name") for h in item.get("hashtags", []) if isinstance(h, dict)]}
            yield fin

    def after_upsert(self, session, finding, item, ctx):
        self.link_author(session, finding, item, (item.raw or {}).get("author_fans") or item.followers)


class InstagramCollector(_SocialCollector):
    name = "instagram"
    title = "Instagram (hashtag, axtarış, hesablar)"
    schedule = {"minute": 5, "hour": "9,21"}
    requires = ("apify_token",)
    account_source = "instagram_account"
    account_url = "https://www.instagram.com/{h}/"
    defaults = {
        "posts_actor": "apify/instagram-scraper",
        "search_actor": "apify/instagram-search-scraper",
        "hashtags": ["kazino", "kazinoazerbaycan", "promokod", "aviator", "pinup", "mostbet", "1win", "pinco", "mərc"],
        "max_search": 15, "max_profiles": 150, "results_limit": 30,
    }

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        p = ctx.params
        apify = Apify()
        tracked = {h.lower() for h in ctx.targets.get("instagram_account", [])}
        profiles = sorted(tracked | {h.lower() for h in known_handles("instagram_account", p["max_profiles"])})
        hashtags = sorted(set(p["hashtags"]) | set(ctx.targets.get("hashtag", [])))
        terms = ctx.terms()
        # 1) account search by keyword → profiles with bios (promo codes, links)
        for q in rotate(sorted({t for t in ctx.terms("promo", "brand", "generic") if len(t) >= 4}), p["max_search"]):
            try:
                users = apify.run_actor(p["search_actor"], {"search": q, "searchType": "user", "searchLimit": 30})
            except Exception as exc:  # noqa: BLE001
                ctx.error(f"instagram search {q}: {exc!r}"[:200])
                continue
            for u in users:
                fin = item_to_finding({**u, "followersCount": u.get("followersCount") or 0}, f"collector:{self.name}")
                if fin and keep_post(fin, terms, tracked):
                    fin.raw = {"collector": self.name, "search": q}
                    yield fin
        # 2) profile details (bio, followers) for tracked / known accounts
        urls = [f"https://www.instagram.com/{h}/" for h in profiles]
        if urls:
            for u in apify.run_actor(p["posts_actor"], {"directUrls": urls, "resultsType": "details", "resultsLimit": 1}):
                fin = item_to_finding(u, f"collector:{self.name}")
                if fin:
                    fin.raw = {"collector": self.name, "kind": "details"}
                    yield fin
        # 3) posts from hashtags and tracked accounts
        post_urls = urls + [f"https://www.instagram.com/explore/tags/{t}/" for t in hashtags]
        for item in apify.run_actor(p["posts_actor"], {"directUrls": post_urls, "resultsType": "posts",
                                                         "resultsLimit": p["results_limit"], "addParentData": True}):
            fin = item_to_finding(item, f"collector:{self.name}")
            if fin is None or not keep_post(fin, terms, set(profiles)):
                continue
            fin.raw = {"collector": self.name, "owner_followers": _get(item, "ownerFollowersCount")}
            yield fin
        for h in tracked:
            ctx.mark_target("instagram_account", h)

    def after_upsert(self, session, finding, item, ctx):
        self.link_author(session, finding, item, (item.raw or {}).get("owner_followers"))


class FacebookCollector(_SocialCollector):
    name = "facebook"
    title = "Facebook səhifələri"
    schedule = {"minute": 25, "hour": "10"}
    requires = ("apify_token",)
    account_source = "facebook_page"
    account_url = "https://www.facebook.com/{h}"
    defaults = {"actor": "apify/facebook-posts-scraper", "max_pages": 100, "results_limit": 20}

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        p = ctx.params
        tracked = list(ctx.targets.get("facebook_page", []))
        pages = sorted(set(tracked) | set(known_handles("facebook_page", p["max_pages"])))
        if not pages:
            return
        items = Apify().run_actor(p["actor"], {
            "startUrls": [{"url": f"https://www.facebook.com/{pg}"} for pg in pages], "resultsLimit": p["results_limit"]})
        terms = ctx.terms()
        for item in items:
            fin = item_to_finding(item, f"collector:{self.name}")
            if fin is None:
                continue
            fin.matched_keywords = match_keywords(fin.text, terms)
            if not fin.matched_keywords:
                continue
            fin.raw = {"collector": self.name, "page": _get(item, "pageName")}
            yield fin
        for pg in tracked:
            ctx.mark_target("facebook_page", pg)
