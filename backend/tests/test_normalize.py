import pytest

from radar.normalize import NotAUrl, canonical_url, clean_raw_url, identify, is_valid_url, normalize_host


@pytest.mark.parametrize("raw,expected", [
    ("=+TgTtogD6uk8xMjQ0", "https://t.me/+TgTtogD6uk8xMjQ0"),
    ("/https://www.cyberbingo.com/", "https://www.cyberbingo.com/"),
    ("Fragaplay.com/app", "https://Fragaplay.com/app"),
    ("aze.1xbet.com", "https://aze.1xbet.com"),
    ("https://bookmaker-expert.com%2Fvisit%2Fvbet", "https://bookmaker-expert.com/visit/vbet"),
    ("hxxps://mostbet[.]com", "https://mostbet.com"),
    ("  <https://pinco.com>  ", "https://pinco.com"),
])
def test_clean_raw_url_repairs(raw, expected):
    assert clean_raw_url(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "facebook, instagram", "Instagram", "URL", "@handle", "just text"])
def test_clean_raw_url_rejects_non_urls(raw):
    assert clean_raw_url(raw) is None
    assert not is_valid_url(raw)


def test_host_normalization():
    assert normalize_host("WWW.Mostbet-AZ90.com.") == "mostbet-az90.com"
    assert normalize_host("m.facebook.com") == "facebook.com"
    assert normalize_host("www.co.uk") == "www.co.uk"  # never strip down to a bare suffix
    assert normalize_host("пинап.рф") == "xn--80appgd.xn--p1ai"
    with pytest.raises(NotAUrl):
        normalize_host("bad host!.com")


@pytest.mark.parametrize("a,b", [
    ("https://www.azmostbet90.com/", "http://azmostbet90.com/az/registration?utm_source=fb"),
    ("aze.1xbet.com", "https://AZE.1xbet.com/en"),
    ("https://t.me/PinUpAz", "t.me/s/pinupaz"),
    ("https://telegram.me/pinupaz", "https://t.me/@pinupaz"),
    ("https://www.tiktok.com/@.1winaze", "https://tiktok.com/@.1WinAze?lang=az"),
    ("https://www.instagram.com/p/B32AIfSJXjy/", "https://instagram.com/p/B32AIfSJXjy?igsh=abc"),
    ("https://www.instagram.com/reel/DOVXe6VDB0W/", "https://www.instagram.com/reels/DOVXe6VDB0W"),
    ("https://www.facebook.com/ads/library/?id=984719936751494", "https://facebook.com/ads/library/?active_status=all&id=984719936751494"),
    ("http://play.google.com/store/apps/details?id=com.unearby.sayh", "https://play.google.com/store/apps/details?id=com.unearby.sayh&hl=az"),
    ("https://apps.apple.com/az/app/x/id6566176181", "http://itunes.apple.com/app/id6566176181"),
])
def test_same_entity_same_key(a, b):
    assert identify(a).key == identify(b).key


@pytest.mark.parametrize("a,b", [
    ("https://t.me/+QL1-qIWYVMQwZjY0", "https://t.me/+ql1-qiwyvmqwzjy0"),  # invite hashes are case-sensitive
    ("https://www.instagram.com/p/AbC/", "https://www.instagram.com/p/abc/"),
    ("https://sub.example.com", "https://example.com"),  # parasite subdomains are separate entities
    ("https://t.me/pinupaz/15", "https://t.me/pinupaz/16"),
])
def test_different_entities_different_keys(a, b):
    assert identify(a).key != identify(b).key


def test_identify_sources():
    assert identify("https://t.me/+8MdzdgyMe8w1ODQ0").source == "telegram_channel"
    assert identify("https://t.me/Betpriz_bot").entity_type == "telegram_bot"
    assert identify("https://t.me/pinupaz/15").source == "telegram_post"
    assert identify("https://www.tiktok.com/@kod_satisi/video/7300000000000000000").source == "tiktok_post"
    assert identify("https://www.instagram.com/1033kazino/").source == "instagram_account"
    assert identify("https://www.facebook.com/61590442454489").source == "facebook_page"
    assert identify("https://www.facebook.com/ads/library/?id=1").source == "meta_ad"
    assert identify("https://play.google.com/store/apps/details?id=a.b").source == "play_store_app"
    assert identify("https://wepari-46775.pro/az/registration?tag=x").key == "domain:wepari-46775.pro"


def test_canonical_url_drops_tracking():
    assert canonical_url("https://X.com/a//b?utm_source=1&b=2&fbclid=z&a=1#frag") == "https://x.com/a/b?a=1&b=2"
