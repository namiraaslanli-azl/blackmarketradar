"""Initial reference data. Loaded once by `radar seed`; afterwards edited in Settings."""

# (slug, display name, aliases used for matching in hosts / handles / text, licensed?)
OPERATORS: list[tuple[str, str, list[str], bool]] = [
    ("azerlotereya", "Azerlotereya", ["azerlotereya", "azərlotereya", "azerlottery", "misli"], True),
    ("topaz", "Topaz / Etopaz", ["topaz", "etopaz"], True),
    ("tfc", "TFC", ["tfc"], True),  # no official domains (confirmed); matched by brand name only
    ("pin-up", "Pin-Up", ["pinup", "pin-up", "pin up", "pinupcasino", "pin-up.az", "пинап"], False),
    ("mostbet", "Mostbet", ["mostbet", "mosbet", "mostbett", "мостбет"], False),
    ("1win", "1win", ["1win", "1вин", "1wn"], False),
    ("1xbet", "1xBet", ["1xbet", "1x-bet", "1xlite", "1xstavka", "1хбет"], False),
    ("melbet", "Melbet", ["melbet", "мелбет"], False),
    ("pinco", "Pinco", ["pinco", "pin-co", "пинко"], False),
    ("vavada", "Vavada", ["vavada", "vadada", "vaadavaka", "vadadaapb", "vadadacc", "vadava", "вавада"], False),
    ("betandreas", "BetAndreas", ["betandreas", "bet-andreas", "bet andreas"], False),
    ("betbuta", "Betbuta", ["betbuta"], False),
    ("betwinner", "Betwinner", ["betwinner"], False),
    ("fraga", "Fraga", ["fraga", "fragaplay"], False),
    ("bet365", "Bet365", ["bet365"], False),
    ("betpriz", "Betpriz", ["betpriz"], False),
    ("betfero", "BetFero", ["betfero"], False),
    ("azbigwin", "Azbigwin", ["azbigwin"], False),
    ("merc777", "Mərc777", ["merc777", "mərc777"], False),
    ("wepari", "Wepari", ["wepari"], False),
    ("aslan-kazino", "Aslan Kazino", ["aslan kazino", "aslankazino", "aslancasino"], False),
    ("neon-club", "Neon Club", ["neon club", "neonclub"], False),
    # black-market lottery product, not Azerlotereya's (confirmed by the monitoring team)
    ("10-line-loto", "10 Line Loto", ["10lineloto", "10 line loto", "10-line-loto", "10line-loto", "10-lineloto"],
     False),
    ("jetwin", "Jetwin", ["jetwin"], False),
    ("22bet", "22Bet", ["22bet"], False),
]

# Licensed whitelist (kind, value, owner). Verify / extend in Settings → Whitelist.
WHITELIST: list[tuple[str, str, str]] = [
    ("domain", "azerlotereya.com", "Azerlotereya"),
    ("domain", "misli.az", "Azerlotereya"),
    ("domain", "topaz.az", "Topaz"),
    ("domain", "etopaz.az", "Topaz"),
    ("brand", "azerlotereya", "Azerlotereya"),
    ("brand", "misli", "Azerlotereya"),
    ("brand", "topaz", "Topaz"),
    ("brand", "etopaz", "Topaz"),
    ("brand", "tfc", "TFC"),
]

# Brands whose look-alikes go to the impersonation list.
PROTECTED_BRANDS = ["azerlotereya", "azerlottery", "misli", "topaz", "etopaz", "tfc"]

# (term, kind, lang)
KEYWORDS: list[tuple[str, str, str]] = [
    # seed list from the brief
    ("kazino", "generic", "az"), ("casino", "generic", "en"), ("mərc", "generic", "az"), ("merc", "generic", "az"),
    ("bet", "generic", "en"), ("bahis", "generic", "tr"), ("ставки", "generic", "ru"), ("казино", "generic", "ru"),
    ("slot", "game", "en"), ("slotlar", "game", "az"), ("bonus", "promo", "az"), ("free spin", "promo", "en"),
    ("pulsuz fırlanma", "promo", "az"), ("pulsuz dönmə qazan", "promo", "az"), ("depozit bonusu", "promo", "az"),
    ("promo kod", "promo", "az"), ("aviator", "game", "en"),
    ("pinco", "brand", ""), ("pin up", "brand", ""), ("pinup", "brand", ""), ("mostbet", "brand", ""),
    ("1win", "brand", ""), ("1xbet", "brand", ""), ("melbet", "brand", ""), ("betandreas", "brand", ""),
    ("vavada", "brand", ""),
    # variants, misspellings, transliterations
    ("kazinosu", "generic", "az"), ("kazinolar", "generic", "az"), ("kazino onlayn", "generic", "az"),
    ("onlayn kazino", "generic", "az"), ("online kazino", "generic", "az"), ("kasino", "generic", "az"),
    ("casino az", "generic", "en"), ("mərclər", "generic", "az"), ("merc oyunlari", "generic", "az"),
    ("mərc oyunları", "generic", "az"), ("idman mərcləri", "generic", "az"), ("bukmeker", "generic", "az"),
    ("bukmeker kontoru", "generic", "az"), ("букмекер", "generic", "ru"), ("ставки на спорт", "generic", "ru"),
    ("онлайн казино", "generic", "ru"), ("слоты", "game", "ru"), ("фриспины", "promo", "ru"),
    ("промокод", "promo", "ru"), ("бонус за регистрацию", "promo", "ru"), ("bahis siteleri", "generic", "tr"),
    ("canlı bahis", "generic", "tr"), ("deneme bonusu", "promo", "tr"), ("bedava spin", "promo", "tr"),
    ("freespin", "promo", "en"), ("free spins", "promo", "en"), ("promokod", "promo", "az"),
    ("promo code", "promo", "en"), ("promo kodu", "promo", "az"), ("bonus kodu", "promo", "az"),
    ("qeydiyyat bonusu", "promo", "az"), ("depozit", "promo", "az"), ("depozitsiz bonus", "promo", "az"),
    ("pul qazan", "promo", "az"), ("pul qazanmaq", "promo", "az"), ("uduş", "generic", "az"),
    ("jackpot", "game", "en"), ("cekpot", "game", "az"), ("ruletka", "game", "az"), ("рулетка", "game", "ru"),
    ("blackjack", "game", "en"), ("poker", "game", "en"), ("lucky jet", "game", "en"), ("plinko", "game", "en"),
    ("sweet bonanza", "game", "en"), ("gates of olympus", "game", "en"), ("авиатор", "game", "ru"),
    ("pin-up", "brand", ""), ("пинап", "brand", ""), ("mosbet", "brand", ""), ("мостбет", "brand", ""),
    ("1вин", "brand", ""), ("1x bet", "brand", ""), ("1хбет", "brand", ""), ("мелбет", "brand", ""),
    ("пинко", "brand", ""), ("bet andreas", "brand", ""), ("вавада", "brand", ""), ("vadada", "brand", ""),
    ("betwinner", "brand", ""), ("22bet", "brand", ""), ("betbuta", "brand", ""), ("jetwin", "brand", ""),
    ("wepari", "brand", ""), ("fraga", "brand", ""), ("betpriz", "brand", ""),
    # learned from the historical workbook
    ("mega qeydiyyat bonusu", "promo", "az"), ("125% depozit", "promo", "az"), ("kod satışı", "promo", "az"),
    ("kod satisi", "promo", "az"), ("kazino kod", "promo", "az"), ("resmi kod", "promo", "az"),
    ("kassa", "payment", "az"), ("kassa kanalı", "payment", "az"), ("real pul", "generic", "az"),
    ("slot oyunları real pul", "game", "az"), ("aviator oyunu real pul", "game", "az"),
    ("ruletka onlayn", "game", "az"), ("idman mərcləri onlayn", "generic", "az"),
    ("free spin azerbaycan", "promo", "az"),
    ("10 line loto", "brand", ""), ("10lineloto", "brand", ""),
]

# Payment-rail vocabulary (Phase 5 aggregates these; extraction starts now)
PAYMENT_TERMS: dict[str, list[str]] = {
    "card:visa": ["visa"],
    "card:mastercard": ["mastercard", "master card"],
    "card:m10": ["m10"],
    "card:kapital": ["kapital bank", "birbank", "kapitalbank"],
    "card:leobank": ["leobank", "leo bank"],
    "card:abb": ["abb", "abb mobile"],
    "card:unibank": ["unibank"],
    "card:pasha": ["pasha bank", "pashabank"],
    "card:yelo": ["yelo"],
    "card:rabita": ["rabitəbank", "rabitabank"],
    "ewallet:emanat": ["emanat", "e-manat"],
    "ewallet:million": ["million terminal", "milliön"],
    "ewallet:portmanat": ["portmanat"],
    "ewallet:skrill": ["skrill"],
    "ewallet:neteller": ["neteller"],
    "ewallet:perfectmoney": ["perfect money", "perfectmoney"],
    "ewallet:piastrix": ["piastrix"],
    "ewallet:payeer": ["payeer"],
    "crypto:usdt": ["usdt", "tether", "trc20", "trc-20"],
    "crypto:btc": ["bitcoin", "btc"],
    "crypto:eth": ["ethereum", "eth"],
    "crypto:ton": ["toncoin"],
}
