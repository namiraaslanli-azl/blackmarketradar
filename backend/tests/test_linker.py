from sqlalchemy import select

from radar.linker import run_linker
from radar.models import Finding, Link, Operator
from radar.store import FindingIn, upsert_finding


def links(session, f, link_type):
    return session.scalars(select(Link).where(Link.src_id == f.id, Link.link_type == link_type)).all()


def test_ad_landing_creates_linked_play_store_finding(session):
    ad = upsert_finding(session, FindingIn(
        url="https://www.facebook.com/ads/library/?id=1", advertiser="Lake Smith Farm",
        text="Yalnız Azərbaycan üçün Mega qeydiyyat bonusu 125% depozit + 250 pulsuz fırlanma",
        landing_url="http://play.google.com/store/apps/details?id=com.unearby.sayh", status="confirmed")).finding
    ig_ad = upsert_finding(session, FindingIn(
        url="https://www.facebook.com/ads/library/?id=2", text="Kazino bonus",
        landing_url="https://www.instagram.com/ozan_kazino/")).finding
    rep = run_linker(session)
    app = session.scalar(select(Finding).where(Finding.canonical_key == "play:com.unearby.sayh"))
    assert app is not None and app.status == "new" and app.needs_review
    assert "ad_to_play_store" in ad.tags
    assert links(session, ad, "app_package")[0].dst_id == app.id
    assert "mega qeydiyyat bonusu" in ad.matched_keywords
    assert session.scalar(select(Finding).where(Finding.canonical_key == "igacc:ozan_kazino")) is not None
    assert "ad_to_instagram" in ig_ad.tags
    assert rep.derived_created["play_store_app"] == 1


def test_ads_cluster_by_landing_and_text_not_advertiser(session):
    texts = ["Mega qeydiyyat bonusu 125% depozit + 250 pulsuz fırlanma yalnız Azərbaycan üçün",
             "Mega qeydiyyat bonusu 125% depozit + 250 pulsuz fırlanma yalnız Azərbaycan üçün!",
             "Tamamilə fərqli mətn burada var və heç nə ortaq deyil"]
    for i, (adv, t) in enumerate(zip(["Lake Smith Farm", "Ojobob online shop", "Lake Smith Farm"], texts)):
        upsert_finding(session, FindingIn(url=f"https://www.facebook.com/ads/library/?id={i}", advertiser=adv, text=t))
    # different text, same landing domain → same campaign
    upsert_finding(session, FindingIn(url="https://www.facebook.com/ads/library/?id=9", text="Başqa",
                                      landing_url="https://prizeplay.lat/?sub1=a"))
    upsert_finding(session, FindingIn(url="https://www.facebook.com/ads/library/?id=10", text="Yenə başqa",
                                      landing_url="https://www.prizeplay.lat/?sub1=b"))
    run_linker(session)
    cl = {f.canonical_key: [l.value for l in links(session, f, "ad_cluster")]
          for f in session.scalars(select(Finding).where(Finding.source == "meta_ad"))}
    assert cl["metaad:0"] and cl["metaad:0"] == cl["metaad:1"]
    assert cl["metaad:2"] == []
    assert cl["metaad:9"] and cl["metaad:9"] == cl["metaad:10"]


def test_operator_impersonation_and_cashier(session):
    d = upsert_finding(session, FindingIn(url="https://azmostbet90.com")).finding
    imp = upsert_finding(session, FindingIn(url="https://azerlotereya.org/")).finding
    legit = upsert_finding(session, FindingIn(url="https://www.azerlotereya.com/")).finding
    tg = upsert_finding(session, FindingIn(url="https://t.me/melbetkassa", title="Kassa",
                                           text="Kassa: M10, Kapital Bank, USDT. Promo kod: MEL777")).finding
    misuse = upsert_finding(session, FindingIn(url="https://t.me/topaz_bonus_az", title="Topaz bonus kanalı")).finding
    run_linker(session)
    mostbet = session.scalar(select(Operator).where(Operator.slug == "mostbet"))
    assert d.operator_id == mostbet.id and "pattern:brand_digits" in d.tags
    assert d.category == "Birbaşa Operativ Mirror" and d.category_suggested
    assert imp.is_impersonation and not legit.is_impersonation and "whitelisted" in legit.tags
    assert {l.value for l in links(session, tg, "payment_method")} == {"card:m10", "card:kapital", "crypto:usdt"}
    assert [l.value for l in links(session, tg, "promo_code")] == ["MEL777"]
    assert "cashier_channel" in tg.tags and tg.operator_id is not None
    assert "licensed_brand_misuse" in misuse.tags and misuse.operator_id is None
