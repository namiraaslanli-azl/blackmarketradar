"""Certificate Transparency: new TLS certificates reveal mirror domains the day they go live.

* `CrtShCollector` (scheduled) queries crt.sh for every operator alias.
* `certstream_loop` (separate long-running service) filters the live CertStream feed.
Both use `candidate_reason`, so a host is kept only when it carries a brand, a gambling
word plus Azerbaijan targeting, or imitates a protected brand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from radar.collectors.base import Collector, Ctx, Whitelist
from radar.collectors.http import client, request
from radar.normalize import NotAUrl, normalize_host, registrable_domain
from radar.patterns import AZ_TOKENS, GAMBLING_TOKENS, host_signals, impersonation_target
from radar.seeds import PROTECTED_BRANDS
from radar.store import FindingIn

log = logging.getLogger(__name__)
# hosting / CDN / SaaS hostnames that match brand words by accident
NOISE_SUFFIXES = (".cloudflaressl.com", ".herokuapp.com", ".azurewebsites.net", ".amazonaws.com", ".vercel.app",
                  ".netlify.app", ".github.io", ".googleusercontent.com", ".myshopify.com")


def candidate_reason(host: str, aliases: dict[str, list[str]], whitelist: Whitelist,
                     licensed: set[str] = frozenset()) -> str | None:
    """Why this hostname is worth a finding, or None."""
    host = host.lower().lstrip("*.").rstrip(".")
    if not host or host.endswith(NOISE_SUFFIXES) or "." not in host:
        return None
    if host in whitelist.domains or registrable_domain(host) in whitelist.domains:
        return None
    target = impersonation_target(host, PROTECTED_BRANDS, whitelist.domains)
    if target:
        return f"impersonates:{target}"
    sig = host_signals(host, {k: v for k, v in aliases.items() if k not in licensed})
    best = sig.best_brand
    if best and best.how != "typo":
        return f"brand:{best.slug}"
    low = host.lower()
    tokens = re.split(r"[.\-\d]+", low)
    has_gambling = any(t in low for t in GAMBLING_TOKENS if len(t) >= 4) or "bet" in tokens
    has_az = any(t in AZ_TOKENS for t in tokens) or any(low.startswith(t) or f"-{t}" in low for t in ("azerbaycan", "azerbaijan", "baku"))
    if has_gambling and has_az:
        return "gambling+az"
    if best and best.how == "typo" and ("cheap_tld" in sig.patterns or has_gambling):
        return f"typo:{best.slug}"
    return None


def names_from_crtsh(rows: list[dict]) -> Iterable[tuple[str, dict]]:
    for row in rows:
        for name in str(row.get("name_value", "")).split("\n"):
            yield name.strip().lower().lstrip("*."), row


class CrtShCollector(Collector):
    name = "ct_crtsh"
    title = "Sertifikat şəffaflığı (crt.sh)"
    schedule = {"minute": 20, "hour": "*/6"}
    defaults = {"days": 3, "pause_seconds": 4, "max_aliases": 80}

    def collect(self, ctx: Ctx) -> Iterable[FindingIn]:
        since = datetime.now(timezone.utc) - timedelta(days=ctx.params["days"])
        seen: set[str] = set()
        aliases = sorted({a for slug, al in ctx.aliases.items() if slug not in ("azerlotereya", "topaz", "tfc")
                          for a in al if re.fullmatch(r"[a-z0-9-]{4,}", a)})[: ctx.params["max_aliases"]]
        queries = aliases + PROTECTED_BRANDS
        with client(timeout=90) as c:
            for term in queries:
                try:
                    r = request(c, "GET", "https://crt.sh/", params={"q": f"%{term}%", "output": "json", "exclude": "expired"},
                                min_interval=ctx.params["pause_seconds"], retries=3, backoff=10)
                    rows = r.json() if r.content else []
                except Exception as exc:  # noqa: BLE001 — crt.sh is often overloaded; keep going
                    ctx.error(f"crt.sh {term}: {exc!r}"[:200])
                    continue
                for host, row in names_from_crtsh(rows):
                    if host in seen:
                        continue
                    issued = row.get("not_before") or row.get("entry_timestamp")
                    try:
                        when = datetime.fromisoformat(issued).replace(tzinfo=timezone.utc) if issued else None
                    except ValueError:
                        when = None
                    if when and when < since:
                        continue
                    reason = candidate_reason(host, ctx.aliases, ctx.whitelist)
                    if not reason:
                        continue
                    seen.add(host)
                    try:
                        normalize_host(host)
                    except NotAUrl:
                        continue
                    yield FindingIn(
                        url=f"https://{host}/", seen_at=datetime.now(timezone.utc), tags=["ct", f"ct:{reason}"],
                        needs_review=True, review_reasons=["new_certificate"],
                        raw={"collector": "ct_crtsh", "query": term, "issuer": row.get("issuer_name"),
                             "not_before": row.get("not_before"), "crtsh_id": row.get("id"), "reason": reason},
                    )


# --- CertStream (long-running) ---------------------------------------------------------

def hosts_from_certstream(message: dict) -> list[str]:
    if message.get("message_type") != "certificate_update":
        return []
    domains = message.get("data", {}).get("leaf_cert", {}).get("all_domains", []) or []
    return sorted({d.lower().lstrip("*.") for d in domains})


def certstream_loop(flush_seconds: int = 60, max_runtime: float | None = None) -> None:
    """Consume CertStream forever; write candidates in batches as `certstream` collector runs."""
    import websockets

    from radar.collectors.base import load_context, run_items
    from radar.config import get_settings
    from radar.db import session_scope
    from radar.runs import RunStats

    url = get_settings().certstream_url
    started = time.monotonic()

    async def consume():
        with session_scope() as s:
            ctx = load_context(s, "certstream", {}, RunStats())
        refreshed = time.monotonic()
        pending: dict[str, str] = {}
        last_flush = time.monotonic()
        backoff = 5
        while max_runtime is None or time.monotonic() - started < max_runtime:
            try:
                async with websockets.connect(url, ping_interval=30, max_size=2**22) as ws:
                    backoff = 5
                    async for raw in ws:
                        for host in hosts_from_certstream(json.loads(raw)):
                            reason = candidate_reason(host, ctx.aliases, ctx.whitelist)
                            if reason:
                                pending[host] = reason
                        if time.monotonic() - last_flush >= flush_seconds and pending:
                            batch, pending = pending, {}
                            await asyncio.to_thread(run_items, "certstream", [
                                FindingIn(url=f"https://{h}/", tags=["ct", f"ct:{r}"], needs_review=True,
                                          review_reasons=["new_certificate"], raw={"collector": "certstream", "reason": r})
                                for h, r in batch.items()])
                            last_flush = time.monotonic()
                        if time.monotonic() - refreshed > 3600:  # pick up new keywords / operators hourly
                            with session_scope() as s:
                                ctx = load_context(s, "certstream", {}, RunStats())
                            refreshed = time.monotonic()
            except Exception as exc:  # noqa: BLE001 — reconnect with backoff on any stream failure
                log.warning("certstream: %r; reconnecting in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    asyncio.run(consume())
