"""Google search (SerpAPI), geo = Azerbaijan, in Azerbaijani, Russian, Turkish and English.

Queries are generated from the keyword list in Settings and rotated: each run takes the next
`max_queries` slice, so the whole list is covered every few days within the API quota.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

from radar.collectors.base import Collector, Ctx
from radar.collectors.ct import candidate_reason
from radar.collectors.http import client, request
from radar.config import get_settings
from radar.extract import match_keywords
from radar.normalize import NotAUrl, identify, registrable_domain
from radar.store import FindingIn

SKIP_DOMAINS = {"wikipedia.org", "google.com", "google.az", "youtube.com", "apple.com", "microsoft.com",
                "linkedin.com", "reddit.com", "x.com", "twitter.com", "trustpilot.com", "gov.az", "azertag.az"}

TEMPLATES = {
    "az": ["{t}", "{t} azerbaycan", "{t} onlayn"],
    "ru": ["{t} азербайджан", "{t} баку"],
    "tr": ["{t} azerbaycan"],
    "en": ["{t} azerbaijan"],
}
BRAND_TEMPLATES = {
    "az": ["{t} azerbaycan", "{t} giriş", "{t} yüklə", "{t} promo kod"],
    "ru": ["{t} зеркало азербайджан", "{t} азербайджан вход"],
    "tr": ["{t} giriş azerbaycan"],
    "en": ["{t} azerbaijan mirror"],
}


def build_queries(ctx: Ctx) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for hl, templates in TEMPLATES.items():
        for term in ctx.terms("generic", "promo", "game", lang=hl):
            out += [(tpl.format(t=term), hl) for tpl in templates]
    brands = ctx.terms("brand")
    for hl, templates in BRAND_TEMPLATES.items():
        out += [(tpl.format(t=b), hl) for b in brands for tpl in templates]
    return sorted(set(out))


def rotate(queries: list, n: int, day: date | None = None) -> list:
    if len(queries) <= n:
        return queries
    start = ((day or date.today()).toordinal() * n) % len(queries)
    return (queries + queries)[start:start + n]


def keep_result(url: str, title: str, snippet: str, ctx: Ctx, terms: list[str]) -> tuple[bool, list[str], str | None]:
    try:
        ref = identify(url)
    except NotAUrl:
        return False, [], None
    if registrable_domain(ref.host) in SKIP_DOMAINS and ref.source == "organic_domain":
        return False, [], None
    kws = match_keywords(f"{title} {snippet} {ref.host}", terms)
    reason = candidate_reason(ref.host, ctx.aliases, ctx.whitelist) if ref.source == "organic_domain" else None
    strong = [k for k in kws if k not in ("bonus", "depozit", "bet", "slot", "poker")]
    return bool(reason or strong), kws, reason


class SerpCollector(Collector):
    name = "serp_google"
    title = "Google axtarışı (SerpAPI)"
    schedule = {"minute": 10, "hour": "6,14"}
    defaults = {"max_queries": 120, "pages": 2, "pause_seconds": 1.0}
    requires = ("serp_api_key",)

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        key = get_settings().serp_api_key
        terms = ctx.terms()
        queries = rotate(build_queries(ctx), ctx.params["max_queries"])
        with client(timeout=60) as c:
            for q, hl in queries:
                for page in range(ctx.params["pages"]):
                    try:
                        data = request(c, "GET", "https://serpapi.com/search.json", min_interval=ctx.params["pause_seconds"], params={
                            "engine": "google", "q": q, "gl": "az", "hl": hl, "google_domain": "google.az",
                            "start": page * 10, "api_key": key,
                        }).json()
                    except Exception as exc:  # noqa: BLE001
                        ctx.error(f"serp {q!r}: {exc!r}"[:200])
                        break
                    results = data.get("organic_results", [])
                    for r in results:
                        url, title, snippet = r.get("link", ""), r.get("title", ""), r.get("snippet", "")
                        ok, kws, reason = keep_result(url, title, snippet, ctx, terms)
                        if not ok:
                            continue
                        yield FindingIn(
                            url=url, title=title or None, text=snippet or None, matched_keywords=kws,
                            tags=["serp", f"serp:{hl}"] + ([f"signal:{reason}"] if reason else []),
                            raw={"collector": self.name, "query": q, "hl": hl, "position": r.get("position")},
                        )
                    if len(results) < 10:
                        break
