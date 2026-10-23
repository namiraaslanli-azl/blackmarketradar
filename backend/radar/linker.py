"""Offline analysis pass: runs after every import / collector batch, needs no network.

* assigns operators (brand aliases in host, handle, text)
* tags mirror patterns and look-alike impersonation domains
* matches keywords from Settings
* creates linked findings for ad landings (Play Store app, Instagram account, domain)
  and for links / invites mentioned in text, and records promo codes and payment rails
* clusters Meta ads by landing target and creative text (advertiser names are noise)
* suggests a category + action for domains that have none (marked category_suggested)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.extract import extract_payment_methods, extract_promo_codes, extract_urls, match_keywords
from radar.models import Finding, Keyword, Link, Operator, WhitelistEntry
from radar.normalize import NotAUrl, identify, registrable_domain
from radar.patterns import host_signals, impersonation_target, match_brands, match_host_brands
from radar.seeds import PROTECTED_BRANDS
from radar.store import FindingIn, add_link, operator_index, upsert_finding

GENERIC_LANDING_HOSTS = {"play.google.com", "instagram.com", "facebook.com", "apps.apple.com", "t.me", "wa.me",
                         "linktr.ee", "bit.ly", "tiktok.com", "youtube.com", "google.com"}
RATING_TOKENS = ("rating", "reyting", "top", "best", "review", "bonusesfinder", "casinos", "sites", "guide", "onlinecasino")


@dataclass
class LinkReport:
    processed: int = 0
    operators_assigned: int = 0
    impersonation: list[str] = field(default_factory=list)
    derived_created: Counter = field(default_factory=Counter)
    links_created: Counter = field(default_factory=Counter)
    categories_suggested: int = 0
    clusters: int = 0

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "operators_assigned": self.operators_assigned,
            "impersonation_flagged": self.impersonation,
            "derived_findings_created": dict(self.derived_created),
            "links_created": dict(self.links_created),
            "categories_suggested": self.categories_suggested,
            "ad_clusters": self.clusters,
        }


def suggest_category(f: Finding, patterns: list[str], has_brand: bool) -> tuple[str, str] | None:
    """Rule-based guess at the workbook's Kateqoriya / Təsir Mexanizmi columns (AI refines in Phase 3)."""
    host = f.host or ""
    reg = registrable_domain(host)
    path = re.sub(r"^https?://[^/]+", "", f.url or "").lower()
    path_gambling = any(t in path for t in ("casino", "kazino", "slot", "bet", "aviator", "pin-up", "mostbet", "1win"))
    if f.is_impersonation:
        return "Fake Mirror / Phishing", "Registrar Take-down + İKTA Bloklama"
    if "gambling_subdomain" in patterns and not has_brand:
        return "Sındırılmış Subdomen (Parasite)", "Hosting Abuse (Hacked Page Cleanup)"
    if "typosquat" in patterns:
        return "Fake Official Mirror", "Registrar Suspend + İKTA DNS Blocklist"
    if has_brand and ({"brand_digits", "brand_az", "mirror_numbered"} & set(patterns) or "cheap_tld" in patterns):
        return "Birbaşa Operativ Mirror", "İKTA DNS/IP Block + Cloudflare Abuse"
    if any(t in reg for t in RATING_TOKENS):
        return "SEO Affiliate / Aggregator", "Google AZ Search De-indexing"
    if path_gambling and "gambling_word" not in patterns and not has_brand:
        return "Sındırılmış Sayt (Hacked WP)", "Hosting Abuse Reporting"
    if has_brand or "gambling_word" in patterns:
        return "Birbaşa Mərc Saytı", "İKTA DNS Blocklist + Registrar Notice"
    return None


def _derive(session: Session, src: Finding, url: str, link_type: str, report: LinkReport, reason: str) -> Finding | None:
    try:
        ref = identify(url)
    except NotAUrl:
        return None
    if ref.key == src.canonical_key:
        return None
    res = upsert_finding(session, FindingIn(
        url=url, status="new", tags=["derived"], needs_review=True, review_reasons=[reason],
        operator_id=src.operator_id, brands=list(src.brands or []), origin=f"derived:{src.public_id}",
        raw={"derived_from": src.public_id, "via": link_type},
    ), status_policy="keep", actor="linker")
    if res.created:
        report.derived_created[res.finding.source] += 1
    add_link(session, src.id, link_type, dst_id=res.finding.id, value=url)
    report.links_created[link_type] += 1
    return res.finding


def _text_signature(text: str | None) -> frozenset[str]:
    words = re.findall(r"[\wəğıöşüç%]+", (text or "").lower())
    return frozenset(" ".join(words[i:i + 3]) for i in range(max(0, len(words) - 2)))


def _hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64


def _ocr_text(f: Finding) -> str:
    return " ".join(i.get("text", "") for i in (f.enrichment or {}).get("ocr", {}).get("images", []))


def cluster_ads(session: Session, ads: list[Finding], report: LinkReport, threshold: float = 0.6) -> None:
    """Union-find over ads sharing a landing target or near-identical creative text."""
    parent = {a.id: a.id for a in ads}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_target: dict[str, list[int]] = defaultdict(list)
    for a in ads:
        if a.landing_url:
            try:
                ref = identify(a.landing_url)
            except NotAUrl:
                continue
            target = ref.key if ref.source != "organic_domain" else f"domain:{registrable_domain(ref.host)}"
            if ref.host in GENERIC_LANDING_HOSTS and ref.source == "organic_domain":
                continue
            by_target[target].append(a.id)
    for ids in by_target.values():
        for other in ids[1:]:
            union(ids[0], other)
    # same creative image (perceptual hash, hamming distance <= 6) → same campaign
    ad_ids = [a.id for a in ads]
    hashes = session.execute(select(Link.src_id, Link.value).where(
        Link.link_type == "image_hash", Link.src_id.in_(ad_ids))).all() if ad_ids else []
    by_hash: dict[str, int] = {}
    for src, value in hashes:
        for seen_value, seen_src in by_hash.items():
            if _hamming(value, seen_value) <= 6:
                union(src, seen_src)
        by_hash.setdefault(value, src)
    sigs = [(a.id, _text_signature(a.text + " " + _ocr_text(a)) if a.text else _text_signature(_ocr_text(a)))
            for a in ads if a.text or _ocr_text(a)]
    for i, (ia, sa) in enumerate(sigs):
        if len(sa) < 3:
            continue
        for ib, sb in sigs[i + 1:]:
            if len(sb) >= 3 and len(sa & sb) / len(sa | sb) >= threshold:
                union(ia, ib)
    groups: dict[int, list[int]] = defaultdict(list)
    for a in ads:
        groups[find(a.id)].append(a.id)
    for root, members in groups.items():
        if len(members) < 2:
            continue
        report.clusters += 1
        label = f"AC{root}"
        for m in members:
            add_link(session, m, "ad_cluster", value=label)


def recluster_ads(session: Session, report: LinkReport | None = None) -> LinkReport:
    report = report or LinkReport()
    ads = list(session.scalars(select(Finding).where(Finding.source == "meta_ad")))
    session.execute(Link.__table__.delete().where(Link.link_type == "ad_cluster", Link.value.like("AC%")))
    cluster_ads(session, ads, report)
    return report


def run_linker(session: Session, findings: list[Finding] | None = None, *, cluster: bool = True) -> LinkReport:
    report = LinkReport()
    aliases, op_ids = operator_index(session)
    licensed_slugs = set(session.scalars(select(Operator.slug).where(Operator.is_licensed)))
    terms = [k.term for k in session.scalars(select(Keyword).where(Keyword.active)).all()]
    wl_domains = {w.value for w in session.scalars(select(WhitelistEntry).where(WhitelistEntry.kind == "domain"))}
    if findings is None:
        findings = list(session.scalars(select(Finding).order_by(Finding.id)))
    brand_name_to_slug = {}
    for slug, al in aliases.items():
        for a in al:
            brand_name_to_slug[re.sub(r"[^a-z0-9əı]", "", a.lower())] = slug

    for f in findings:
        report.processed += 1
        tags = list(f.tags or [])
        # OCR text counts: illegal ads often hide the gambling words inside the image
        text_blob = " ".join(filter(None, [f.title, f.text, f.handle, f.advertiser, _ocr_text(f)]))

        # operator from analyst-entered brands, then host, then text
        slug = None
        for b in f.brands or []:
            slug = brand_name_to_slug.get(re.sub(r"[^a-z0-9əı]", "", b.lower()))
            if slug:
                break
        patterns: list[str] = []
        if f.source == "organic_domain" and f.host:
            sig = host_signals(f.host, {k: v for k, v in aliases.items() if k not in licensed_slugs})
            patterns = sig.patterns
            best = sig.best_brand
            if best and best.how == "typo":
                tags.append(f"possible_operator:{best.slug}")
            elif not slug and best:
                slug = best.slug
            target = impersonation_target(f.host, PROTECTED_BRANDS, wl_domains)
            if target:
                if not f.is_impersonation:
                    report.impersonation.append(f.host)
                f.is_impersonation = True
                tags.append(f"impersonates:{target}")
            if f.host in wl_domains or registrable_domain(f.host) in wl_domains:
                tags.append("whitelisted")
        if not slug and f.handle and f.source != "organic_domain":
            hits = [h for h in match_host_brands(f.handle, aliases) if h.how != "typo"]
            slug = hits[0].slug if hits else None
        if not slug and text_blob:
            hits = match_brands(text_blob, aliases)
            slug = hits[0].slug if hits else None
        if slug in licensed_slugs:
            # a licensed brand name outside the whitelist is misuse, never the channel's operator
            if f.source != "organic_domain":
                tags.append("licensed_brand_misuse")
            slug = None
        if slug and f.operator_id is None:
            f.operator_id = op_ids[slug]
            report.operators_assigned += 1
        if f.operator_id:
            add_link(session, f.id, "operator", operator_id=f.operator_id, value=slug or "")

        tags += [f"pattern:{p}" for p in patterns]
        kw = match_keywords(" ".join(filter(None, [text_blob, f.host, f.url])), terms)
        if kw:
            f.matched_keywords = sorted(set(f.matched_keywords or []) | set(kw))

        # promo codes / payment rails / Telegram links
        for code in extract_promo_codes(text_blob):
            add_link(session, f.id, "promo_code", value=code)
            report.links_created["promo_code"] += 1
        pay_text = text_blob if ("kassa" in text_blob.lower() or "cashier_channel" in tags or f.source == "telegram_channel") else ""
        for method in extract_payment_methods(pay_text):
            add_link(session, f.id, "payment_method", value=method)
            report.links_created["payment_method"] += 1
        if f.source in ("telegram_channel", "telegram_post") and re.search(r"kassa|касса", text_blob, re.I):
            tags.append("cashier_channel")

        # linked findings
        if f.source == "meta_ad" and f.landing_url:
            reason = "derived_from_ad_landing"
            d = _derive(session, f, f.landing_url, "landing", report, reason)
            if d is not None and d.source == "play_store_app":
                tags.append("ad_to_play_store")
                add_link(session, f.id, "app_package", dst_id=d.id, value=d.handle or "")
            elif d is not None and d.source == "instagram_account":
                tags.append("ad_to_instagram")
        if f.source == "meta_ad" and not f.landing_url and f.landing_raw:
            tags.append("landing_not_url")
        for url in extract_urls(text_blob):
            try:
                ref = identify(url)
            except NotAUrl:
                continue
            if ref.host in ("telegra.ph",) or ref.key == f.canonical_key:
                continue
            if ref.host in GENERIC_LANDING_HOSTS and ref.source in ("organic_domain", "play_store_app") \
                    and ref.entity_type != "app":  # "play.google.com" in ad copy is not an entity
                continue
            lt = "telegram_link" if ref.source == "telegram_channel" else "mentions_domain"
            _derive(session, f, url, lt, report, "derived_from_text")

        if f.source == "organic_domain" and not f.category:
            guess = suggest_category(f, patterns, bool(slug or f.operator_id))
            if guess:
                f.category, f.suggested_action = guess
                f.category_suggested = True
                report.categories_suggested += 1
        f.tags = list(dict.fromkeys(tags))

    if cluster:
        recluster_ads(session, report)
    session.flush()
    return report
