"""Rule-based signals used by importers, collectors and (Phase 3) the classifier."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from radar.normalize import host_label, registrable_domain

CHEAP_TLDS = {
    "win", "life", "pro", "casino", "bet", "top", "icu", "xyz", "site", "online", "fun", "vip", "cc",
    "club", "live", "space", "website", "shop", "click", "buzz", "monster", "lol", "games", "today", "world",
}
GAMBLING_TOKENS = ("casino", "kazino", "kasino", "bet", "slot", "merc", "bahis", "poker", "spin", "jackpot",
                   "bingo", "loto", "lotto", "aviator", "ruletka", "bukmeker", "stavka", "win")
AZ_TOKENS = ("az", "aze", "azer", "azerbaycan", "azerbaijan", "baku", "baki")


def _squash(s: str) -> str:
    return re.sub(r"[^0-9a-zа-яəğıöşüç]", "", s.lower())


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


@dataclass
class BrandHit:
    slug: str
    alias: str
    how: str  # exact | contains | typo
    confidence: float


@dataclass
class HostSignals:
    host: str
    label: str
    brands: list[BrandHit] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)

    @property
    def best_brand(self) -> BrandHit | None:
        return max(self.brands, key=lambda b: b.confidence, default=None)


def match_brands(text: str, operators: dict[str, list[str]]) -> list[BrandHit]:
    """Find operator aliases in free text (word-ish boundaries)."""
    low = (text or "").lower()
    hits: dict[str, BrandHit] = {}
    for slug, aliases in operators.items():
        for alias in aliases:
            a = alias.lower()
            if len(a) < 3:
                continue
            pat = r"(?<![\w])" + re.escape(a).replace(r"\ ", r"[\s\-_.]?") + r"(?![a-zа-я])"
            if re.search(pat, low):
                hits.setdefault(slug, BrandHit(slug, alias, "exact", 0.9))
                break
    return list(hits.values())


def match_host_brands(label: str, operators: dict[str, list[str]]) -> list[BrandHit]:
    """Exact / contains matches first; edit-distance typos only when nothing matched directly.

    Typo hits are a review signal (confidence 0.6) — callers should not assign an operator from them.
    """
    sq = _squash(label)
    low = label.lower()
    hits: dict[str, BrandHit] = {}
    for slug, aliases in operators.items():
        for alias in aliases:
            a = _squash(alias)
            if len(a) < 3:
                continue
            if sq == a:
                hits[slug] = BrandHit(slug, alias, "exact", 1.0)
                break
            # short aliases (tfc, 1win) only as a standalone-ish token to avoid noise
            if (len(a) >= 5 and a in sq) or (len(a) < 5 and re.search(rf"(^|\d|-){re.escape(a)}($|\d|-|az)", low)):
                hits.setdefault(slug, BrandHit(slug, alias, "contains", 0.85))
    if hits:
        return list(hits.values())
    # typo windows must start at a token boundary: "vadadacc", not "ramenbet"
    starts = [0] + [m.end() for m in re.finditer(r"[\d-]+", low)]
    tokens = [_squash(low[i:]) for i in starts]
    for slug, aliases in operators.items():
        for alias in aliases:
            a = _squash(alias)
            if len(a) < 6:
                continue
            tol = 1 if len(a) < 9 else 2
            if any(levenshtein(t[:w], a, tol) <= tol for t in tokens for w in (len(a) - 1, len(a), len(a) + 1) if len(t) >= w):
                hits[slug] = BrandHit(slug, alias, "typo", 0.6)
                break
    return list(hits.values())


def host_signals(host: str, operators: dict[str, list[str]]) -> HostSignals:
    label = host_label(host)
    reg = registrable_domain(host)
    tld = reg.rsplit(".", 1)[-1] if "." in reg else ""
    sig = HostSignals(host=host, label=label, brands=match_host_brands(label, operators))
    # subdomain brand use (parasite pages: casino.some-college.edu.az)
    sub = host[: -len(reg)].rstrip(".") if host != reg else ""
    if sub:
        for hit in match_host_brands(sub.replace(".", "-"), operators):
            if hit.slug not in {b.slug for b in sig.brands}:
                sig.brands.append(hit)
        if any(t in sub for t in GAMBLING_TOKENS):
            sig.patterns.append("gambling_subdomain")
    low = label.lower()
    if sig.brands and re.search(r"\d{2,}", low):
        sig.patterns.append("brand_digits")
    if sig.brands and any(re.search(rf"(^|[\d-]){t}([\d-]|$)|{t}$|^{t}", low) for t in AZ_TOKENS):
        sig.patterns.append("brand_az")
    if any(b.how == "typo" for b in sig.brands):
        sig.patterns.append("typosquat")
    if tld in CHEAP_TLDS:
        sig.patterns.append("cheap_tld")
    if any(t in low for t in GAMBLING_TOKENS):
        sig.patterns.append("gambling_word")
    alnum = re.sub(r"[^a-z0-9]", "", low)
    if len(alnum) >= 10 and not sig.brands and (shannon_entropy(alnum) > 3.3 or re.search(r"[bcdfghjklmnpqrstvwxz]{5,}", alnum)):
        sig.patterns.append("random_string")
    if re.fullmatch(r"[a-z]+-\d{4,6}", low):
        sig.patterns.append("mirror_numbered")
    return sig


def impersonation_target(host: str, protected: list[str], whitelisted_domains: set[str]) -> str | None:
    """Return the protected brand a host imitates, or None (whitelisted hosts never match).

    Short brand names (misli, topaz, tfc) must appear literally; long ones (azerlotereya)
    also match with small typos (azerlotreya, azerloterya).
    """
    reg = registrable_domain(host)
    if host in whitelisted_domains or reg in whitelisted_domains:
        return None
    full = host.lower()
    label = _squash(host_label(host))
    for brand in protected:
        b = _squash(brand)
        if len(b) <= 3:
            if re.search(rf"(^|[.\d-]){re.escape(b)}([.\d-]|az|$)", full):
                return brand
            continue
        if b in label or b in _squash(full[: -len(reg)] if full != reg else ""):
            return brand
        if len(b) >= 8:
            tol = 2 if len(b) >= 10 else 1
            if any(levenshtein(label[i:i + w], b, tol) <= tol
                   for w in (len(b) - 1, len(b), len(b) + 1) for i in range(0, max(1, len(label) - w + 1))):
                return brand
    return None
