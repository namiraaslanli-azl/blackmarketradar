import json

from sqlalchemy import select

from radar.importers.apify import detect_kind, import_apify, item_to_finding
from radar.models import Finding

META = {"adArchiveID": "984719936751494", "pageName": "Lake Smith Farm", "startDate": 1729987200,
        "isActive": True, "snapshot": {"body": {"text": "Mega qeydiyyat bonusu"},
                                       "link_url": "http://play.google.com/store/apps/details?id=com.unearby.sayh",
                                       "images": [{"original_image_url": "https://scontent/x.jpg"}]}}
TT = {"webVideoUrl": "https://www.tiktok.com/@kod_satisi/video/7300000000000000001", "text": "Resmi kod PIN777",
      "playCount": 120000, "diggCount": 5000, "authorMeta": {"name": "kod_satisi", "fans": 9000},
      "createTimeISO": "2026-10-20T10:00:00.000Z"}
IG = {"shortCode": "C51oP7wIpxa", "url": "https://www.instagram.com/p/C51oP7wIpxa/", "ownerUsername": "x",
      "likesCount": 10, "caption": "kazino"}
IGP = {"username": "1033kazino", "followersCount": 15000, "biography": "Promo kod: KAZINO1033", "url": "https://www.instagram.com/1033kazino"}


def test_detect_and_map():
    assert [detect_kind(x) for x in (META, TT, IG, IGP)] == ["meta_ad", "tiktok_post", "instagram_post", "instagram_account"]
    m = item_to_finding(META, "t")
    assert m.landing_url.startswith("http://play.google.com") and m.media_urls == ["https://scontent/x.jpg"]
    assert m.published_at.year == 2024
    t = item_to_finding(TT, "t")
    assert t.views == 120000 and t.handle == "kod_satisi"


def test_import_file_twice(session, tmp_path):
    p = tmp_path / "dataset.json"
    p.write_text(json.dumps([META, TT, IG, IGP, {"foo": 1}]))
    b1 = import_apify(session, p)
    assert b1.report["created"] == 4 and b1.report["unrecognized"] == 1
    TT2 = {**TT, "playCount": 150000}
    p.write_text(json.dumps([TT2]))
    b2 = import_apify(session, p)
    assert b2.report["merged_into_existing"] == 1
    f = session.scalar(select(Finding).where(Finding.source == "tiktok_post"))
    assert f.views == 150000


def test_import_csv_export(session, tmp_path):
    p = tmp_path / "dataset.csv"
    p.write_text("adArchiveID,pageName,snapshot/body/text,snapshot/link_url\n"
                 "555,Ojobob online shop,Kazino bonus,https://prizeplay.lat/?x=1\n", encoding="utf-8")
    b = import_apify(session, p)
    assert b.report["created"] == 1
    f = session.scalar(select(Finding))
    assert f.canonical_key == "metaad:555" and f.landing_url == "https://prizeplay.lat/?x=1"
