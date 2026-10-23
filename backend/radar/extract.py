"""Pull links, promo codes and payment methods out of free text (posts, bios, ad copy)."""

from __future__ import annotations

import re

from radar.normalize import clean_raw_url
from radar.seeds import PAYMENT_TERMS

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'()\[\]{}|,]+|(?<![@\w])[a-z0-9-]{2,}(?:\.[a-z0-9-]{2,})*\.(?:com|net|org|az|ru|pro|win|life|casino|bet|top|icu|xyz|site|online|cc|me|io|app|vip|club|link|ly|gg|to|tr|info)(?:/[^\s<>\"'()]*)?", re.I)
_TG_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/)?\+?[\w-]{3,}(?:/\d+)?", re.I)
_TG_INVITE_BARE = re.compile(r"(?<![\w/])\+[A-Za-z0-9_-]{14,22}(?![\w])")
_PROMO_RE = re.compile(
    r"(?:promo\s*kod(?:u)?|promokod(?:u)?|promo\s*code|bonus\s*kod(?:u)?|промокод|(?<![\w])kod(?:u)?)\b"
    r"(?:\s*[:\-–—=]\s*|\s+)[«\"']?([A-Za-z0-9][A-Za-z0-9_-]{2,19})",
    re.I,
)
_PROMO_STOP = {"AZN", "USD", "BONUS", "FREE", "SPIN", "KOD", "PROMO", "VAR", "YOX", "BU", "ILE", "ÜÇÜN", "SATISI",
               "SATIŞI", "RESMI", "RƏSMI", "LEGAL", "ALMAQ", "ALMAK", "HESABI", "WORLD", "VERIRIK", "YAZ", "LINK"}


def extract_urls(text: str | None) -> list[str]:
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        raw = m.group(0).rstrip(".,;:!?…")
        url = clean_raw_url(raw)
        host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
        if host.split(".")[0] in ("com", "org", "net", "io", "ru", "az"):  # Android package ids
            continue
        if url and url not in out:
            out.append(url)
    for m in _TG_INVITE_BARE.finditer(text or ""):
        url = f"https://t.me/{m.group(0)}"
        if url not in out:
            out.append(url)
    return out


def extract_telegram_links(text: str | None) -> list[str]:
    out = []
    for m in _TG_RE.finditer(text or ""):
        url = clean_raw_url(m.group(0))
        if url and url not in out:
            out.append(url)
    return out


def extract_promo_codes(text: str | None) -> list[str]:
    codes: list[str] = []
    for m in _PROMO_RE.finditer(text or ""):
        token = m.group(1).strip("-_")
        code = token.upper()
        # real codes are written in caps or carry digits/underscores; "kod almaq" is prose
        if not (token.isupper() or re.search(r"[\d_]", token)):
            continue
        if code in _PROMO_STOP or (code.isdigit() and len(code) < 4):
            continue
        if code not in codes:
            codes.append(code)
    return codes


def extract_payment_methods(text: str | None) -> list[str]:
    low = (text or "").lower()
    found = []
    for method, terms in PAYMENT_TERMS.items():
        if any(re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", low) for t in terms):
            found.append(method)
    return found


def match_keywords(text: str | None, terms: list[str]) -> list[str]:
    low = (text or "").lower()
    hits = []
    for term in terms:
        t = term.lower()
        if len(t) <= 3:
            ok = re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", low)
        else:
            ok = t in low
        if ok:
            hits.append(term)
    return sorted(set(hits))
