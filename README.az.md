# Black Market Radar

Azərbaycanda **lisenziyasız qumar reklamını** aşkarlamaq və sənədləşdirmək üçün
Azerlotereyanın daxili aləti: domenlər, Meta reklamları, TikTok, Instagram, Facebook,
Telegram, Play Store və App Store.
Qayda: lisenziyalı ağ siyahıda (Azerlotereya, Topaz / Etopaz, TFC) olmayan hər hansı qumar,
mərc və ya kazino reklamı qanunsuzdur.

English: [README.md](README.md) · Arxitektura: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

| Hissə | Qovluq | Texnologiya |
|---|---|---|
| Worker-lər, idxal, API, CLI | `backend/` | Python 3.12, SQLAlchemy, Alembic, Celery + Redis, FastAPI, Playwright |
| İdarə paneli (Azərbaycan dilində) | `web/` | Next.js 15, TypeScript |
| Verilənlər bazası | — | PostgreSQL 16 |
| Giriş qatı | `deploy/Caddyfile` | Caddy (TLS + şifrə) |

## Vəziyyət

**1-ci mərhələ (təməl) və 2-ci mərhələ (kollektorlar) hazırdır.** Növbəti: 3–5-ci mərhələlər
(süni intellektlə təsnifat və yoxlama növbəsi, tam panel, rəhbərlik üçün funksiyalar).

## Kollektorlar

| Ad | Mənbə | Lazımdır | Cədvəl (Bakı) |
|---|---|---|---|
| `ct_crtsh` | crt.sh — hər operator və qorunan brend üçün sertifikat axtarışı | — | 6 saatdan bir |
| `certstream` | Canlı sertifikat axını (ayrıca servis) | — | daim |
| `serp_google` | Google (SerpAPI), gl=az, az / ru / tr / en | `SERP_API_KEY` | 06:10, 14:10 |
| `meta_ads` | Meta reklam kitabxanası (AZ), Apify: açar sözlər + izlənən səhifələr, OCR | `APIFY_TOKEN` | 07:35, 19:35 |
| `tiktok` | TikTok (Apify): hashtag, axtarış, hesablar | `APIFY_TOKEN` | 08:50, 20:50 |
| `instagram` | Instagram (Apify): hesab axtarışı, bio, postlar | `APIFY_TOKEN` | 09:05, 21:05 |
| `facebook` | Facebook səhifə postları (Apify) | `APIFY_TOKEN` | 10:25 |
| `telegram` | Telegram: kanal axtarışı, yeni postlar, dəvət linkləri | `TELEGRAM_API_ID/HASH` + giriş | 2 saatdan bir |
| `stores` | Play Store + App Store (AZ), maskalanmış oyunlar | — | 11:15 |

Hər kollektor açar sözləri və izlənən hesabları **Ayarlar**-dan oxuyur, ağ siyahını
keçir, hər işə düşməni **Kollektorlar** bölməsində göstərir ("İndi işə sal", yandır/söndür)
və xəta olduqda gözləmə ilə təkrar cəhd edir. Açarı olmayan kollektor xəta vermir, "atlandı"
kimi qeyd olunur.

```bash
radar collectors                       # siyahı, cədvəl, çatışmayan açarlar
radar collect ct_crtsh -p days=1       # birini indi işə sal
radar track tiktok_account kod_satisi  # izlənən hesab əlavə et (Ayarlar-da da olar)
```

**Telegram girişi (bir dəfə):** `.env`-də `TELEGRAM_API_ID` və `TELEGRAM_API_HASH` yazıldıqdan
sonra `docker compose run --rm api radar telegram-login` işə salın, ayrıca hesabın nömrəsini
və Telegram-ın göndərdiyi kodu daxil edin. Sessiya `telegram` volume-da saxlanılır.

## Lokal quraşdırma

```bash
createuser -P radar && createdb -O radar radar        # şifrə: radar
python3 -m venv .venv && . .venv/bin/activate
pip install -e "backend[dev]"
playwright install chromium

cd backend
radar migrate
radar seed
radar import-seed ../data/import/findings_seed.csv   # və ya: radar import-workbook <fayl.xlsx>
radar report
uvicorn radar.api.main:app --port 8000

cd ../web && npm install && API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Testlər: `cd backend && pytest` (`radar_test` bazası lazımdır).

## VPS-ə yerləşdirmə

Hədəf: Ubuntu 24.04, 4 vCPU, 8 GB RAM, 80 GB disk.

```bash
curl -fsSL https://get.docker.com | sh
git clone <repo> /opt/radar && cd /opt/radar
cp .env.example .env && nano .env              # şifrələr, SITE_ADDRESS, API açarları
docker compose run --rm caddy caddy hash-password --plaintext 'şifrəniz'   # → BASIC_AUTH_HASH
docker compose up -d --build

mkdir -p data/import && cp findings_seed.csv data/import/
docker compose exec api radar import-seed /data/import/findings_seed.csv
docker compose exec api radar enrich --queue
docker compose exec api radar report
```

Domenin DNS A qeydini VPS-in IP-sinə yönləndirin — Caddy TLS sertifikatını avtomatik alır.
5-ci mərhələdə istifadəçi hesabları və rollar əlavə olunana qədər bütün sayt şifrə ilə qorunur.

## Əsas əmrlər

| Əmr | Nə edir |
|---|---|
| `radar import-seed FAYL.csv|.xlsx` | Normallaşdırılmış tapıntıları idxal edir (CSV və ya "Findings" vərəqli Excel) |
| `radar import-workbook FAYL.xlsx` | Həftəlik Excel hesabatını (bütün vərəqlər) idxal edir |
| `radar import-apify FAYL...` | Apify eksportlarını (JSON / JSONL / CSV) idxal edir |
| `radar link` | Operator, güzgü domen nümunələri, imitasiya və reklam klasterlərini yenidən hesablayır |
| `radar enrich [--limit N] [--force] [--queue]` | RDAP/WHOIS, DNS, Cloudflare, abuse əlaqəsi, yönləndirmələr, HTML, favicon, ekran görüntüsü |
| `radar report` | Data keyfiyyəti hesabatı |

İdxal təkrar işlədilə bilər: eyni fayl ikinci dəfə heç nə əlavə etmir, statuslar isə yalnız
irəli gedir (yeni → təsdiqlənib → şikayət olunub → bloklanıb).

## Açar söz və ağ siyahı əlavə etmək

Paneldə **Ayarlar** bölməsindən. Bütün kollektorlar və qaydalar bu cədvəllərdən oxuyur,
dəyişiklik növbəti işə düşmədə tətbiq olunur. İlkin dəyərlər `backend/radar/seeds.py`-dadır;
`radar seed` yalnız çatışmayanları əlavə edir, sizin dəyişikliklərinizi silmir.

## Yeni kollektor əlavə etmək

1. `backend/radar/collectors/<ad>.py` faylında `Collector` sinfindən törəmə yazın: `name`,
   `title` (paneldə görünən ad), `schedule`, `defaults`, `requires` və `FindingIn`
   obyektləri qaytaran `collect(ctx)`.
2. Modulu `radar/collectors/__init__.py`-da import edin.

Qalanını çərçivə edir: təkrarların silinməsi, ağ siyahı, jurnal, əlaqələndirmə, Celery cədvəli
və paneldəki sətir. Testi `backend/tests/test_collectors.py`-a əlavə edin.

## Bazanın ehtiyat nüsxəsi

```bash
# hər gün saat 03:00, 14 gün saxlanılır (root crontab)
0 3 * * * cd /opt/radar && docker compose exec -T db pg_dump -U radar -Fc radar > backups/radar-$(date +\%F).dump && find backups -name '*.dump' -mtime +14 -delete

# sübut faylları (ekran görüntüləri, HTML) "evidence" volume-dadır
docker run --rm -v radar_evidence:/e -v $PWD/backups:/b alpine tar czf /b/evidence-$(date +%F).tgz -C /e .

# bərpa
docker compose exec -T db pg_restore -U radar -d radar --clean < backups/radar-2026-10-23.dump
```

`backups/` qovluğunu serverdən kənara köçürün — sübut hash-ləri yalnız fayllar qorunduqda dəyərlidir.

## Gizli açarlar

Bütün açarlar `.env` faylındadır (git-ə düşmür). Nümunə: `.env.example`.
