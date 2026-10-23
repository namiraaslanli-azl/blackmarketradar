from radar.extract import extract_payment_methods, extract_promo_codes, extract_urls
from radar.patterns import host_signals, impersonation_target
from radar.seeds import OPERATORS, PROTECTED_BRANDS

ALIASES = {slug: aliases for slug, _, aliases, licensed in OPERATORS if not licensed}
WL = {"azerlotereya.com", "misli.az", "topaz.az", "etopaz.az"}


def brand(host):
    b = host_signals(host, ALIASES).best_brand
    return (b.slug, b.how) if b else None


def test_mirror_patterns():
    assert brand("azmostbet90.com") == ("mostbet", "contains")
    assert "brand_digits" in host_signals("azmostbet90.com", ALIASES).patterns
    assert "brand_az" in host_signals("mostbet-az91.com", ALIASES).patterns
    assert brand("pinco08v.com")[0] == "pinco"
    assert brand("vadadacc.com")[0] == "vavada"
    assert brand("vaadavaka.com")[0] == "vavada"
    assert "mirror_numbered" in host_signals("wepari-46775.pro", ALIASES).patterns
    assert "cheap_tld" in host_signals("wepari-46775.pro", ALIASES).patterns
    assert "random_string" in host_signals("2spb2wn41xoimst.com", ALIASES).patterns
    assert "gambling_subdomain" in host_signals("casino.some-college.edu.az", ALIASES).patterns


def test_no_brand_noise():
    assert brand("361ramenbet.com") is None
    assert brand("10linelotoazerbaycan.com") is None
    assert brand("wikipedia.org") is None


def test_impersonation():
    assert impersonation_target("azerlotereya.org", PROTECTED_BRANDS, WL) == "azerlotereya"
    assert impersonation_target("azerlotreya-bonus.com", PROTECTED_BRANDS, WL) == "azerlotereya"
    assert impersonation_target("misli-az1.com", PROTECTED_BRANDS, WL) == "misli"
    assert impersonation_target("etopaz-az.win", PROTECTED_BRANDS, WL) in ("topaz", "etopaz")
    assert impersonation_target("tfc-bet.com", PROTECTED_BRANDS, WL) == "tfc"
    assert impersonation_target("azerlotereya.com", PROTECTED_BRANDS, WL) is None
    assert impersonation_target("www.misli.az", PROTECTED_BRANDS, WL) is None
    assert impersonation_target("lottopark.com", PROTECTED_BRANDS, WL) is None
    assert impersonation_target("slotsmillion.com", PROTECTED_BRANDS, WL) is None


def test_promo_codes():
    assert extract_promo_codes("Promo kod: PINUP777 ilə 125% bonus") == ["PINUP777"]
    assert extract_promo_codes("промокод AZBET2024") == ["AZBET2024"]
    assert extract_promo_codes("kod satışı, resmi kod almaq üçün yazın") == []
    assert extract_promo_codes("KOD: KAZINO_1 və kodlar haqqında") == ["KAZINO_1"]


def test_payment_and_urls():
    assert set(extract_payment_methods("Kassa: M10, Kapital Bank, USDT TRC20")) == {"card:m10", "card:kapital", "crypto:usdt"}
    urls = extract_urls("pin-co.cc/vMwTt, qayda telegra.ph, əlavə kanal +v4bKeObN8DdhMWRk, com.tennistimerbet8579.app")
    assert "https://pin-co.cc/vMwTt" in urls
    assert "https://t.me/+v4bKeObN8DdhMWRk" in urls
    assert not any("com.tennis" in u for u in urls)
