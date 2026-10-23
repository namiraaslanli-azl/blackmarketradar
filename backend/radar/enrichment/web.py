"""HTTP side of enrichment: redirect chain, HTML snapshot, favicon hash, content signals."""

from __future__ import annotations

import base64
import hashlib
import html as htmllib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx
import mmh3

from radar.extract import extract_payment_methods, extract_promo_codes, match_keywords

MAX_HTML = 3 * 1024 * 1024
_META_REFRESH = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+content=["']?\s*\d+\s*;\s*url=([^"'>\s]+)""", re.I)
_JS_REDIRECT = re.compile(r"""(?:window\.|document\.|top\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']|location\.replace\(\s*["']([^"']+)["']\s*\)""", re.I)
_ICON_RE = re.compile(r"""<link[^>]+rel=["'][^"']*icon[^"']*["'][^>]*>""", re.I)
_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_LANG_RE = re.compile(r"""<html[^>]+lang=["']?([\w-]+)""", re.I)
_TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.I | re.S)


@dataclass
class Hop:
    url: str
    status: int | None
    location: str | None = None
    via: str = "http"  # http | meta | js


@dataclass
class PageResult:
    chain: list[Hop] = field(default_factory=list)
    final_url: str | None = None
    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    html: bytes = b""
    title: str | None = None
    lang: str | None = None
    error: str | None = None

    @property
    def loaded(self) -> bool:
        return self.status is not None and self.status < 400 and bool(self.html)


def visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG_RE.sub(" ", html))).strip()


def fetch_chain(client: httpx.Client, url: str, max_hops: int = 10) -> PageResult:
    res = PageResult()
    current = url
    seen = set()
    for _ in range(max_hops):
        if current in seen:
            res.error = "redirect_loop"
            break
        seen.add(current)
        try:
            r = client.get(current, follow_redirects=False)
        except httpx.HTTPError as exc:
            res.chain.append(Hop(current, None))
            res.error = type(exc).__name__
            break
        loc = r.headers.get("location")
        if r.is_redirect and loc:
            nxt = urljoin(current, loc)
            res.chain.append(Hop(current, r.status_code, nxt))
            current = nxt
            continue
        body = r.content[:MAX_HTML]
        text = body.decode(r.encoding or "utf-8", "replace")
        # client-side redirects: follow one level each, they are common on mirror domains
        m = _META_REFRESH.search(text)
        js = None if m else _JS_REDIRECT.search(text[:20000]) if len(visible_text(text)) < 400 else None
        target = (m.group(1) if m else None) or (js and (js.group(1) or js.group(2)))
        if target and not target.startswith(("#", "javascript:")):
            nxt = urljoin(current, target)
            if nxt not in seen:
                res.chain.append(Hop(current, r.status_code, nxt, via="meta" if m else "js"))
                current = nxt
                continue
        res.chain.append(Hop(current, r.status_code))
        res.final_url, res.status, res.html = str(r.url), r.status_code, body
        res.headers = {k.lower(): v for k, v in r.headers.items()}
        t = _TITLE_RE.search(text)
        res.title = visible_text(t.group(1))[:300] if t else None
        lang = _LANG_RE.search(text)
        res.lang = lang.group(1).lower() if lang else None
        break
    else:
        res.error = "too_many_redirects"
    if res.final_url is None and res.chain:
        res.final_url = res.chain[-1].url
    return res


def favicon_hash(content: bytes) -> int:
    """Shodan-compatible favicon hash (mmh3 of base64 with newlines every 76 chars)."""
    return mmh3.hash(base64.encodebytes(content))


def fetch_favicon(client: httpx.Client, page: PageResult) -> tuple[bytes, str] | None:
    if not page.final_url:
        return None
    text = page.html.decode("utf-8", "replace")
    candidates = []
    for tag in _ICON_RE.findall(text):
        href = _HREF_RE.search(tag)
        if href:
            candidates.append(urljoin(page.final_url, htmllib.unescape(href.group(1))))
    candidates.append(urljoin(page.final_url, "/favicon.ico"))
    for url in candidates[:3]:
        if url.startswith("data:"):
            continue
        try:
            r = client.get(url, follow_redirects=True)
        except httpx.HTTPError:
            continue
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and r.content and "html" not in ctype:
            return r.content, url
    return None


AZ_TARGETING = [
    (re.compile(r"\bAZN\b"), "azn"),
    (re.compile("₼"), "manat_sign"),
    (re.compile(r"\bmanat\b", re.I), "manat"),
    (re.compile(r"azərbaycan|azerbaycan|azerbaijan|азербайджан", re.I), "azerbaijan"),
    (re.compile(r"\+994"), "phone_994"),
    (re.compile(r"hreflang=[\"']az", re.I), "hreflang_az"),
]


def content_signals(page: PageResult, keywords: list[str]) -> dict:
    raw = page.html.decode("utf-8", "replace")
    text = visible_text(raw)
    targeting = sorted({name for rx, name in AZ_TARGETING if rx.search(raw)})
    if (page.lang or "").startswith("az"):
        targeting.append("lang_az")
    kw = match_keywords(text + " " + (page.title or ""), keywords)
    return {
        "keywords": kw,
        "is_gambling": len(kw) >= 2,
        "az_targeting": targeting,
        "payment_methods": extract_payment_methods(text),
        "promo_codes": extract_promo_codes(text),
        "text_sample": text[:1500],
        "html_sha256": hashlib.sha256(page.html).hexdigest() if page.html else None,
    }
