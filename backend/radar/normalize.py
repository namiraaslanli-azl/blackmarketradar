"""URL / host normalization and entity identification.

Everything that decides "is this the same thing we already have?" lives here, so that
importers and collectors agree on one canonical key per entity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import idna
import tldextract

# offline: use the snapshot of the public suffix list bundled with tldextract
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|yclid|igshid|igsh|si|mibextid|_r|ref_src|share_id)$", re.I)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOSTLIKE_RE = re.compile(r"^[\w.-]+\.[a-z¡-￿]{2,}(:\d+)?(/|$|\?)", re.I)


class NotAUrl(ValueError):
    pass


def clean_raw_url(value: str | None) -> str | None:
    """Repair what spreadsheets and humans do to links. Returns None if nothing URL-like remains."""
    if value is None:
        return None
    s = str(value).strip().strip("​﻿").strip()
    if not s:
        return None
    s = s.strip("<>\"' ")
    # "=+TgTtogD6uk8xMjQ0" — Excel turned a Telegram invite into a formula
    if s.startswith("=+") and re.fullmatch(r"=\+[\w-]{10,}", s):
        return f"https://t.me/{s[1:]}"
    s = s.lstrip("=")
    # "/https://www.cyberbingo.com/"
    m = re.search(r"https?://", s, re.I)
    if m and m.start() > 0 and m.start() <= 3:
        s = s[m.start():]
    if re.match(r"^(https?://)?[^/?#]*%2f", s, re.I):  # "site.com%2Fvisit%2Fx"
        s = unquote(s)
    s = re.sub(r"^hxxps?", lambda x: x.group(0).replace("xx", "tt"), s, flags=re.I)
    s = s.replace("[.]", ".").replace("(.)", ".")
    if " " in s.strip():
        return None
    if s.startswith("//"):
        s = "https:" + s
    if not _SCHEME_RE.match(s):
        if s.startswith("@"):
            return None
        if not _HOSTLIKE_RE.match(s):
            return None
        s = "https://" + s
    if not s.lower().startswith(("http://", "https://")):
        return None
    return s


def is_valid_url(value: str | None) -> bool:
    cleaned = clean_raw_url(value)
    if not cleaned:
        return False
    try:
        host = normalize_host(urlsplit(cleaned).hostname or "")
    except NotAUrl:
        return False
    return "." in host


def normalize_host(host: str, *, strip_www: bool = True) -> str:
    h = (host or "").strip().strip(".").lower()
    if not h:
        raise NotAUrl("empty host")
    if "@" in h:
        h = h.rsplit("@", 1)[1]
    if h.startswith("[") or re.fullmatch(r"[\d.]+", h):
        return h.split(":")[0] if not h.startswith("[") else h
    h = h.split(":")[0]
    try:
        h = idna.encode(h, uts46=True).decode("ascii")
    except idna.IDNAError:
        try:
            h = h.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise NotAUrl(f"bad host: {host!r}") from exc
    if strip_www:
        stripped = re.sub(r"^(www\d*|m)\.", "", h)
        if stripped != h and _tld(stripped).domain and _tld(stripped).suffix:
            h = stripped
    if not re.fullmatch(r"[a-z0-9.-]+", h) or ".." in h:
        raise NotAUrl(f"bad host: {host!r}")
    return h


def registrable_domain(host: str) -> str:
    ext = _tld(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return host


def host_label(host: str) -> str:
    """The brand-bearing label: 'azmostbet90' for 'www.azmostbet90.com'."""
    return _tld(host).domain or host.split(".")[0]


def canonical_url(url: str) -> str:
    """Stable form of a URL for display/comparison (not the dedup key)."""
    cleaned = clean_raw_url(url)
    if not cleaned:
        raise NotAUrl(url)
    parts = urlsplit(cleaned)
    host = normalize_host(parts.hostname or "", strip_www=False)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    query.sort()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    return urlunsplit((parts.scheme.lower(), host + port, path, urlencode(query, doseq=True), ""))


@dataclass(frozen=True)
class EntityRef:
    source: str
    entity_type: str
    key: str  # canonical_key, unique across the findings table
    url: str
    host: str
    handle: str | None = None


_TG_HOSTS = {"t.me", "telegram.me", "telegram.dog"}
_IG_RESERVED = {"p", "reel", "reels", "tv", "explore", "stories", "accounts", "about", "developer", "direct"}
_FB_RESERVED = {"ads", "watch", "groups", "events", "profile.php", "permalink.php", "story.php", "sharer", "photo", "reel", "share"}


def identify(url: str) -> EntityRef:
    """Map any URL to (source, canonical key). Raises NotAUrl."""
    cleaned = clean_raw_url(url)
    if not cleaned:
        raise NotAUrl(url)
    parts = urlsplit(cleaned)
    host = normalize_host(parts.hostname or "")
    path = unquote(parts.path or "")
    segs = [s for s in path.split("/") if s]
    q = dict(parse_qsl(parts.query))
    pretty = canonical_url(cleaned)

    if host in _TG_HOSTS:
        if segs and segs[0] == "s":
            segs = segs[1:]
        if not segs:
            raise NotAUrl(url)
        first = segs[0]
        if first == "joinchat" and len(segs) > 1:
            code = "+" + segs[1]
            return EntityRef("telegram_channel", "telegram_invite", f"tg:{code}", f"https://t.me/{code}", "t.me", code)
        if first.startswith("+"):
            return EntityRef("telegram_channel", "telegram_invite", f"tg:{first}", f"https://t.me/{first}", "t.me", first)
        name = first.lstrip("@")
        lname = name.lower()
        if len(segs) > 1 and segs[1].isdigit():
            return EntityRef("telegram_post", "telegram_post", f"tgpost:{lname}/{segs[1]}",
                             f"https://t.me/{name}/{segs[1]}", "t.me", name)
        etype = "telegram_bot" if lname.endswith("bot") else "telegram_channel"
        return EntityRef("telegram_channel", etype, f"tg:{lname}", f"https://t.me/{name}", "t.me", name)

    if host == "facebook.com" and segs[:2] == ["ads", "library"] and q.get("id"):
        ad_id = q["id"].strip()
        return EntityRef("meta_ad", "ad", f"metaad:{ad_id}",
                         f"https://www.facebook.com/ads/library/?id={ad_id}", host)

    if host == "play.google.com":
        if "apps" in segs and "details" in segs and q.get("id"):
            pkg = q["id"].strip()
            return EntityRef("play_store_app", "app", f"play:{pkg.lower()}",
                             f"https://play.google.com/store/apps/details?id={pkg}", host, pkg)
        return EntityRef("play_store_app", "play_listing", f"playurl:{pretty}", pretty, host)

    if host in ("apps.apple.com", "itunes.apple.com"):
        app_id = next((s[2:] for s in reversed(segs) if re.fullmatch(r"id\d+", s)), None)
        if app_id:
            return EntityRef("app_store_app", "app", f"appstore:{app_id}", pretty, host, app_id)
        return EntityRef("app_store_app", "app_listing", f"appstoreurl:{pretty}", pretty, host)

    if host.endswith("tiktok.com"):
        if host != "tiktok.com" or not segs:  # vm./vt. short links: unresolved, keep full URL
            return EntityRef("tiktok_post", "tiktok_short", f"ttshort:{pretty}", pretty, host)
        if segs[0].startswith("@"):
            user = segs[0][1:]
            if len(segs) >= 3 and segs[1] in ("video", "photo") and segs[2].isdigit():
                return EntityRef("tiktok_post", "tiktok_post", f"ttpost:{segs[2]}",
                                 f"https://www.tiktok.com/@{user}/video/{segs[2]}", host, user)
            return EntityRef("tiktok_account", "tiktok_account", f"ttacc:{user.lower()}",
                             f"https://www.tiktok.com/@{user}", host, user)
        if segs[0] in ("tag", "discover"):
            return EntityRef("tiktok_post", "tiktok_listing", f"tturl:{pretty}", pretty, host)

    if host == "instagram.com" and segs:
        if segs[0] in ("p", "reel", "reels", "tv") and len(segs) > 1:
            code = segs[1]
            etype = "instagram_post" if segs[0] == "p" else "instagram_reel"
            kind = "p" if segs[0] == "p" else "reel"
            return EntityRef("instagram_post", etype, f"igpost:{code}",
                             f"https://www.instagram.com/{kind}/{code}/", host)
        if segs[0] not in _IG_RESERVED:
            user = segs[0].lstrip("@")
            if len(segs) > 2 and segs[1] in ("p", "reel"):
                return EntityRef("instagram_post", "instagram_post", f"igpost:{segs[2]}",
                                 f"https://www.instagram.com/p/{segs[2]}/", host, user)
            return EntityRef("instagram_account", "instagram_account", f"igacc:{user.lower()}",
                             f"https://www.instagram.com/{user}/", host, user)

    if host in ("facebook.com", "fb.com", "fb.watch") and segs:
        if segs[0] not in _FB_RESERVED and len(segs) == 1:
            page = segs[0]
            return EntityRef("facebook_page", "facebook_page", f"fbpage:{page.lower()}",
                             f"https://www.facebook.com/{page}", "facebook.com", page)
        return EntityRef("facebook_post", "facebook_post", f"fbpost:{pretty}", pretty, "facebook.com")

    return EntityRef("organic_domain", "domain", f"domain:{host}", pretty, host)


def domain_key(host: str) -> str:
    return f"domain:{normalize_host(host)}"
