"""Domain enrichment: one function per finding, safe to run in parallel workers."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_, select

from radar.config import get_settings
from radar.db import session_scope
from radar.enrichment import netinfo, web
from radar.evidence import store_capture
from radar.models import Finding, FindingEvent, Keyword
from radar.normalize import NotAUrl, identify, registrable_domain
from radar.runs import track_run
from radar.store import FindingIn, add_link, upsert_finding

log = logging.getLogger(__name__)
CLOUDFLARE_ABUSE = "abuse@cloudflare.com"


def http_client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        timeout=s.http_timeout, verify=False,  # mirror sites often have broken TLS; we only read them
        headers={"User-Agent": s.http_user_agent, "Accept-Language": s.accept_language},
    )


def due_domain_ids(session, limit: int | None = None, force: bool = False) -> list[int]:
    s = get_settings()
    q = select(Finding.id).where(Finding.source == "organic_domain")
    if not force:
        cutoff = datetime.now(timezone.utc) - timedelta(days=s.enrichment_refresh_days)
        q = q.where(or_(Finding.enriched_at.is_(None), Finding.enriched_at < cutoff))
    q = q.order_by(Finding.enriched_at.asc().nulls_first(), Finding.id)
    if limit:
        q = q.limit(limit)
    return list(session.scalars(q))


def start_url(f: Finding) -> str:
    return f.url if f.url and f.url.startswith("http") else f"https://{f.host}/"


def collect(host: str, url: str, client: httpx.Client, keywords: list[str]) -> dict:
    """All network lookups for one domain. Pure data in, pure data out (easy to test)."""
    out: dict = {"at": datetime.now(timezone.utc).isoformat(), "errors": {}}
    dns_info = netinfo.resolve(host)
    out["dns"] = dns_info.as_dict()

    zone = registrable_domain(host)
    try:
        out["rdap"] = netinfo.rdap_domain(client, zone)
    except (httpx.HTTPError, ValueError) as exc:
        out["errors"]["rdap"] = repr(exc)[:200]
        out["rdap"] = None
    if not out["rdap"]:
        try:
            out["rdap"] = netinfo.whois_domain(zone)
            if out["rdap"]:
                out["rdap"]["via"] = "whois"
        except OSError as exc:
            out["errors"]["whois"] = repr(exc)[:200]

    page = web.fetch_chain(client, url)
    if not page.loaded and url.startswith("https://"):
        alt = web.fetch_chain(client, "http://" + url[len("https://"):])
        if alt.loaded:
            page = alt
    out["http"] = {
        "chain": [asdict(h) for h in page.chain], "final_url": page.final_url, "status": page.status,
        "title": page.title, "lang": page.lang, "error": page.error,
        "server": page.headers.get("server"),
    }
    cf = netinfo.cloudflare_evidence(dns_info, page.headers)
    out["cloudflare"] = {"is_cloudflare": bool(cf), "evidence": cf}

    hosting = None
    ip = (dns_info.a or dns_info.aaaa or [None])[0]
    if ip and not cf:
        try:
            hosting = netinfo.rdap_ip(client, ip)
        except (httpx.HTTPError, ValueError) as exc:
            out["errors"]["rdap_ip"] = repr(exc)[:200]
    out["hosting"] = {"ip": ip, **(hosting or {})} if ip else None
    rd = out.get("rdap") or {}
    out["abuse"] = {
        "hosting": CLOUDFLARE_ABUSE if cf else (hosting or {}).get("abuse_email"),
        "registrar": rd.get("registrar_abuse_email"),
        "registrar_name": rd.get("registrar"),
        "hosting_name": "Cloudflare Inc." if cf else (hosting or {}).get("org"),
    }
    out["content"] = web.content_signals(page, keywords) if page.html else None
    fav = web.fetch_favicon(client, page) if page.loaded else None
    out["_html"] = page.html if page.html else None
    out["_favicon"] = fav
    out["is_live"] = page.loaded or (dns_info.resolves and page.status is not None and page.status < 500)
    return out


def apply_result(session, f: Finding, data: dict) -> None:
    html, fav = data.pop("_html", None), data.pop("_favicon", None)
    if html:
        store_capture(session, f, "html", html, url=data["http"]["final_url"])
    if fav:
        content, fav_url = fav
        h = web.favicon_hash(content)
        data["favicon"] = {"url": fav_url, "mmh3": h}
        store_capture(session, f, "favicon", content, url=fav_url, meta={"mmh3": h})
        add_link(session, f.id, "favicon_hash", value=str(h))
    f.enrichment = {**(f.enrichment or {}), "network": data}
    f.enriched_at = datetime.now(timezone.utc)
    f.is_live = bool(data.get("is_live"))
    content = data.get("content") or {}
    if content.get("keywords"):
        f.matched_keywords = sorted(set(f.matched_keywords or []) | set(content["keywords"]))
    for m in content.get("payment_methods", []):
        add_link(session, f.id, "payment_method", value=m)
    for c in content.get("promo_codes", []):
        add_link(session, f.id, "promo_code", value=c)
    tags = list(f.tags or [])
    if data["cloudflare"]["is_cloudflare"]:
        tags.append("cloudflare")
    if content.get("az_targeting"):
        tags.append("az_targeting")
    if content.get("is_gambling"):
        tags.append("gambling_content")
    if f.category_suggested and data["cloudflare"]["is_cloudflare"] and "Cloudflare" not in (f.suggested_action or ""):
        f.suggested_action = f"{f.suggested_action} + Cloudflare Abuse" if f.suggested_action else "Cloudflare Abuse"

    # redirect to another host = mirror / rotation evidence → its own finding
    final = data["http"].get("final_url")
    if final:
        try:
            ref = identify(final)
        except NotAUrl:
            ref = None
        if ref and ref.key != f.canonical_key:
            res = upsert_finding(session, FindingIn(
                url=final, status="new", tags=["derived", "redirect_target"], needs_review=True,
                review_reasons=["derived_from_redirect"], operator_id=f.operator_id, brands=list(f.brands or []),
                origin=f"derived:{f.public_id}", raw={"derived_from": f.public_id, "via": "redirect"},
            ), status_policy="keep", actor="enrichment")
            add_link(session, f.id, "redirect", dst_id=res.finding.id, value=final)
            tags.append("redirects")
    f.tags = list(dict.fromkeys(tags))
    session.add(FindingEvent(finding_id=f.id, kind="enriched", actor="enrichment",
                             data={"live": f.is_live, "cloudflare": data["cloudflare"]["is_cloudflare"],
                                   "final_url": final, "errors": data.get("errors")}))


def enrich_one(finding_id: int, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or http_client()
    try:
        with session_scope() as s:
            f = s.get(Finding, finding_id)
            host, url = f.host, start_url(f)
            keywords = [k.term for k in s.scalars(select(Keyword).where(Keyword.active))]
        data = collect(host, url, client, keywords)
        with session_scope() as s:
            f = s.get(Finding, finding_id)
            apply_result(s, f, data)
            return {"id": finding_id, "host": host, "live": f.is_live, "cloudflare": data["cloudflare"]["is_cloudflare"]}
    finally:
        if own:
            client.close()


def screenshot_many(ids: list[int], stats=None) -> int:
    from radar.enrichment.screenshot import browser, capture

    done = 0
    with browser() as ctx:
        for fid in ids:
            with session_scope() as s:
                f = s.get(Finding, fid)
                if f.is_live is False:
                    continue
                url = (f.enrichment or {}).get("network", {}).get("http", {}).get("final_url") or start_url(f)
            try:
                cap = capture(ctx, url)
            except Exception as exc:  # noqa: BLE001 — one bad page must not stop the batch
                if stats:
                    stats.error(f"screenshot {fid} {url}: {exc!r}"[:300])
                continue
            with session_scope() as s:
                f = s.get(Finding, fid)
                store_capture(s, f, "screenshot", cap.png, url=cap.final_url, meta={"status": cap.status})
                store_capture(s, f, "rendered_html", cap.html, url=cap.final_url)
            done += 1
    return done


class NoNetwork(RuntimeError):
    pass


def preflight(client: httpx.Client) -> None:
    """Refuse to run without working DNS + HTTP: otherwise every domain would be recorded as dead."""
    if not netinfo.resolve("www.google.com").resolves:
        raise NoNetwork("DNS resolution failed for www.google.com")
    try:
        client.get("https://www.google.com/generate_204")
    except httpx.HTTPError as exc:
        raise NoNetwork(f"HTTP check failed: {exc!r}") from exc


def enrich_many(ids: list[int], screenshot: bool = True) -> dict:
    s = get_settings()
    results, failed = [], []
    with track_run("enrichment", {"count": len(ids), "screenshot": screenshot}) as stats:
        stats.found = len(ids)
        with http_client() as client:
            preflight(client)
        with http_client() as client, ThreadPoolExecutor(max_workers=s.enrichment_concurrency) as pool:
            futures = {pool.submit(enrich_one, i, client): i for i in ids}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                    stats.updated += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append(futures[fut])
                    stats.error(f"{futures[fut]}: {exc!r}")
        shots = screenshot_many([r["id"] for r in results], stats) if screenshot and s.screenshot_enabled and results else 0
    return {
        "enriched": len(results), "failed": len(failed),
        "live": sum(1 for r in results if r["live"]), "cloudflare": sum(1 for r in results if r["cloudflare"]),
        "screenshots": shots,
    }
