"""Collectors end to end against the test DB, with every external service mocked."""

import io
import json

import httpx
import sqlalchemy as sa
import pytest
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from radar.collectors import REGISTRY, run_collector
from radar.collectors import ct, serp, social, stores
from radar.collectors.base import Whitelist
from radar.models import CollectorRun, Finding, Link, TrackedTarget
from radar.seeds import OPERATORS

ALIASES = {slug: aliases for slug, _, aliases, _l in OPERATORS}
WL = Whitelist(domains={"azerlotereya.com", "misli.az", "topaz.az", "etopaz.az"})


def fake_response(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://x"))


def ad_image(text: str) -> bytes:
    img = Image.new("RGB", (900, 300), "white")
    ImageDraw.Draw(img).text((40, 100), text, fill="black", font=ImageFont.load_default(size=72))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def links(session, f, t):
    return session.scalars(select(Link).where(Link.src_id == f.id, Link.link_type == t)).all()


# --- certificate transparency -------------------------------------------------------

@pytest.mark.parametrize("host,expected", [
    ("azmostbet90.com", "brand:mostbet"),
    ("www.pinco08v.win", "brand:pinco"),
    ("casino-azerbaycan.win", "gambling+az"),
    ("az-kazino777.com", "gambling+az"),
    ("misli-az5.com", "impersonates:misli"),
    ("azerlotreya-bonus.com", "impersonates:azerlotereya"),
    ("azerlotereya.com", None),
    ("www.misli.az", None),
    ("mostbet.herokuapp.com", None),
    ("wikipedia.org", None),
    ("bakery-az.com", None),
])
def test_candidate_reason(host, expected):
    assert ct.candidate_reason(host, ALIASES, WL, licensed={"azerlotereya", "topaz", "tfc"}) == expected


def test_certstream_message_parsing():
    msg = {"message_type": "certificate_update",
           "data": {"leaf_cert": {"all_domains": ["*.azmostbet91.com", "azmostbet91.com", "WWW.X.COM"]}}}
    assert ct.hosts_from_certstream(msg) == ["azmostbet91.com", "www.x.com"]
    assert ct.hosts_from_certstream({"message_type": "heartbeat"}) == []


def test_crtsh_collector(app_db, monkeypatch):
    rows = [{"id": 1, "name_value": "azmostbet92.com\n*.azmostbet92.com", "not_before": "2099-01-01T00:00:00",
             "issuer_name": "R3"},
            {"id": 2, "name_value": "mostbet-old.com", "not_before": "2001-01-01T00:00:00"},
            {"id": 3, "name_value": "bakery-shop.com", "not_before": "2099-01-01T00:00:00"}]
    monkeypatch.setattr(ct, "request", lambda c, m, url, **kw: fake_response(rows if "mostbet" in kw["params"]["q"] else []))
    res = run_collector("ct_crtsh", {"max_aliases": 200})
    assert res["new"] == 1 and res["status"] == "ok"
    f = app_db.scalar(select(Finding).where(Finding.canonical_key == "domain:azmostbet92.com"))
    assert f.status == "new" and "ct:brand:mostbet" in f.tags and f.operator_id is not None
    run = app_db.scalar(select(CollectorRun).where(CollectorRun.collector == "ct_crtsh"))
    assert run.status == "ok" and run.items_new == 1 and run.duration_ms is not None


# --- SERP ---------------------------------------------------------------------------

def test_serp_rotation_covers_everything():
    from datetime import date, timedelta

    qs = list(range(25))
    covered = set()
    for d in range(3):
        covered |= set(serp.rotate(qs, 10, date(2026, 1, 1) + timedelta(days=d)))
    assert covered == set(qs)


def test_serp_collector(app_db, monkeypatch):
    monkeypatch.setenv("SERP_API_KEY", "k")
    from radar.config import get_settings
    get_settings.cache_clear()
    page = {"organic_results": [
        {"link": "https://azmostbet93.com/az/", "title": "Mostbet Azərbaycan giriş", "snippet": "bonus", "position": 1},
        {"link": "https://news-site.az/idman/casino-aviator", "title": "Aviator oyunu real pul", "snippet": "kazino", "position": 2},
        {"link": "https://az.wikipedia.org/wiki/Kazino", "title": "Kazino", "snippet": "kazino", "position": 3},
        {"link": "https://www.misli.az/", "title": "Misli", "snippet": "mərc", "position": 4},
        {"link": "https://cooking.az/plov", "title": "Plov", "snippet": "bonus", "position": 5},
    ]}
    calls = []
    monkeypatch.setattr(serp, "request", lambda c, m, url, **kw: calls.append(kw["params"]) or fake_response(page))
    res = run_collector("serp_google", {"max_queries": 2, "pages": 1})
    hosts = set(app_db.scalars(select(Finding.host).where(sa.literal("serp") == sa.any_(Finding.tags))))
    assert hosts == {"azmostbet93.com", "news-site.az"}
    assert all(c["gl"] == "az" and c["google_domain"] == "google.az" for c in calls)
    assert res["new"] == 2


# --- Meta ads -----------------------------------------------------------------------

def test_meta_ads_collector_ocr_clusters_and_tracks(app_db, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    from radar.config import get_settings
    get_settings.cache_clear()
    from radar.collectors import apify, meta_ads

    img = ad_image("KAZINO 250 FS")
    items = [
        {"adArchiveID": str(i), "pageID": "777", "pageName": name, "startDate": 1729987200,
         "snapshot": {"body": {"text": "Yeni oyun! Yüklə və qazan"}, "link_url": "http://play.google.com/store/apps/details?id=com.puzzle.x",
                      "images": [{"original_image_url": f"https://scontent/{i}.png"}]}}
        for i, name in ((1, "Lake Smith Farm"), (2, "Ojobob online shop"))
    ]
    captured = {}
    monkeypatch.setattr(apify.Apify, "run_actor", lambda self, actor, inp, **kw: captured.update(inp) or items)
    monkeypatch.setattr(meta_ads, "request", lambda c, m, url, **kw: httpx.Response(200, content=img, request=httpx.Request("GET", url)))
    res = run_collector("meta_ads", {"max_keywords": 3, "auto_track_min_keywords": 1})
    assert res["new"] == 2
    assert all("country=AZ" in u["url"] for u in captured["startUrls"])
    ads = app_db.scalars(select(Finding).where(Finding.source == "meta_ad")).all()
    for ad in ads:
        app_db.refresh(ad)
        assert "kazino" in ad.enrichment["ocr"]["images"][0]["text"].lower()
        assert "kazino" in ad.matched_keywords and "ocr_gambling_text" in ad.tags
        assert links(app_db, ad, "image_hash")
    clusters = {l.value for ad in ads for l in links(app_db, ad, "ad_cluster")}
    assert len(clusters) == 1  # same image + same landing → one campaign
    assert app_db.scalar(select(Finding).where(Finding.canonical_key == "play:com.puzzle.x")) is not None
    # gambling words only in the image are enough to auto-track the advertiser page
    page = app_db.scalar(select(TrackedTarget).where(TrackedTarget.kind == "meta_page"))
    assert page.value == "777" and page.note.startswith("auto:")


def test_ocr_reads_azerbaijani_ad_text():
    from radar.ocr import read_image

    res = read_image(ad_image("KAZINO BONUS 250"))
    assert "KAZINO" in res["text"].upper() and len(res["phash"]) == 16


# --- TikTok -------------------------------------------------------------------------

def test_tiktok_collector_keeps_az_posts_and_links_authors(app_db, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    from radar.config import get_settings
    get_settings.cache_clear()
    from radar.collectors import apify

    items = [
        {"webVideoUrl": "https://www.tiktok.com/@kod_satisi/video/7300000000000000001",
         "text": "Rəsmi kod satışı 🇦🇿 kazino kod PIN777", "playCount": 120000, "diggCount": 3000,
         "authorMeta": {"name": "kod_satisi", "fans": 9000}},
        {"webVideoUrl": "https://www.tiktok.com/@someone_br/video/7300000000000000002",
         "text": "casino bonus Brasil", "playCount": 5, "authorMeta": {"name": "someone_br", "fans": 1}},
    ]
    monkeypatch.setattr(apify.Apify, "run_actor", lambda self, actor, inp, **kw: items)
    run_collector("tiktok", {"max_profiles": 0})
    post = app_db.scalar(select(Finding).where(Finding.source == "tiktok_post"))
    assert post.views == 120000 and "promo_code_seller" in post.tags
    acc = app_db.scalar(select(Finding).where(Finding.canonical_key == "ttacc:kod_satisi"))
    assert acc.followers == 9000 and "promo_code_seller" in acc.tags
    assert links(app_db, post, "linked_account")[0].dst_id == acc.id
    assert app_db.scalar(select(Finding).where(Finding.handle == "someone_br")) is None
    assert [l.value for l in links(app_db, post, "promo_code")] == ["PIN777"]


# --- stores -------------------------------------------------------------------------

def test_app_signals():
    terms = ["kazino", "real pul", "slot", "bonus", "aviator"]
    assert stores.app_signals("Fruit Puzzle", "Aviator oyna, real pul qazan! Kazino bonus", "GAME_PUZZLE", terms)[1] == ["disguised_game"]
    assert stores.app_signals("Lucky Slots", "Kazino slot real pul AZN", "GAME_CASINO", terms)[1] == ["gambling_app"]
    assert stores.app_signals("Calculator", "simple calculator", "TOOLS", terms)[1] == []


def test_stores_collector(app_db, monkeypatch):
    import google_play_scraper as gps
    from google_play_scraper.exceptions import NotFoundError

    from radar.store import FindingIn, upsert_finding

    upsert_finding(app_db, FindingIn(url="https://play.google.com/store/apps/details?id=com.gone.app"))
    app_db.commit()
    monkeypatch.setattr(gps, "search", lambda q, **kw: [{"appId": "com.fruit.puzzle", "title": "Fruit Puzzle", "description": "kazino aviator real pul"}])

    def fake_app(app_id, **kw):
        if app_id == "com.gone.app":
            raise NotFoundError("gone")
        return {"appId": app_id, "title": "Fruit Puzzle", "description": "Aviator oyna, real pul qazan! Kazino",
                "genreId": "GAME_PUZZLE", "developer": "Lake Smith Farm", "realInstalls": 50000}

    monkeypatch.setattr(gps, "app", fake_app)
    monkeypatch.setattr(stores, "request", lambda c, m, url, **kw: fake_response({"results": [
        {"trackId": 6566176181, "trackName": "Lucky Spin", "description": "kazino real pul aviator",
         "primaryGenreName": "Casino", "sellerName": "X"}]}))
    run_collector("stores", {"max_queries": 1})
    app = app_db.scalar(select(Finding).where(Finding.canonical_key == "play:com.fruit.puzzle"))
    assert "disguised_game" in app.tags and app.raw["sources"][0]["installs"] == 50000
    gone = app_db.scalar(select(Finding).where(Finding.canonical_key == "play:com.gone.app"))
    app_db.refresh(gone)
    assert gone.is_live is False and "removed_from_store" in gone.tags
    ios = app_db.scalar(select(Finding).where(Finding.canonical_key == "appstore:6566176181"))
    assert "gambling_app" in ios.tags


# --- telegram mapping (network-free) -------------------------------------------------

def test_telegram_mapping():
    from datetime import datetime, timezone

    from radar.collectors.telegram import channel_to_finding, message_to_finding

    terms = ["kazino", "kassa", "bonus"]
    ch = channel_to_finding("melbetkassa", "Melbet Kassa", 12000, "Kassa: M10, USDT", terms, last_id=55)
    assert ch.subscribers == 12000 and "cashier_channel" in ch.tags and ch.enrichment == {"telegram": {"last_id": 55}}
    post = message_to_finding("melbetkassa", 56, "Yeni kanal: t.me/+AbCdEfGhIjKlMnOp12 bonus", 300,
                              datetime(2026, 10, 1, tzinfo=timezone.utc), terms)
    assert post.url == "https://t.me/melbetkassa/56" and post.views == 300
    assert "https://t.me/+AbCdEfGhIjKlMnOp12" in post.raw["links"]
    assert message_to_finding("x", 1, "salam", None, None, terms) is None
    inv = channel_to_finding(None, "PINCO qrup", 1677, None, terms, invite="+QL1-qIWYVMQwZjY0")
    assert inv.url == "https://t.me/+QL1-qIWYVMQwZjY0"


# --- framework ----------------------------------------------------------------------

def test_missing_secrets_logs_skipped_run(app_db, monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    res = run_collector("tiktok")
    assert res == {"status": "skipped", "missing": ["APIFY_TOKEN"]}
    run = app_db.scalar(select(CollectorRun).where(CollectorRun.collector == "tiktok"))
    assert run.status == "skipped" and "APIFY_TOKEN" in run.error_log
    assert "Telegram session" in " ".join(REGISTRY["telegram"].missing_secrets())


def test_whitelisted_items_are_never_stored(app_db, monkeypatch):
    from radar.collectors.base import load_context, ingest
    from radar.runs import RunStats
    from radar.store import FindingIn

    ctx = load_context(app_db, "test", {}, RunStats())
    res = ingest("test", [FindingIn(url="https://www.misli.az/"), FindingIn(url="https://misli-az7.com")], ctx)
    assert res["whitelisted"] == 1 and res["new"] == 1


def test_disabled_collector_does_not_run(app_db):
    from radar.models import CollectorConfig

    app_db.add(CollectorConfig(name="ct_crtsh", enabled=False))
    app_db.commit()
    assert run_collector("ct_crtsh") == {"status": "disabled"}
