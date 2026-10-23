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

**Mərhələ 1 (təməl) hazırdır:** sxem, təkrarların silinməsi, idxal (seed CSV, orijinal
Excel hesabatı, Apify eksportları), oflayn əlaqələndirici, domen zənginləşdirmə worker-i,
data keyfiyyəti hesabatı, panelin əsası, Docker Compose. Növbəti: 2–5-ci mərhələlər.

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
| `radar import-seed FAYL.csv` | Normallaşdırılmış tapıntılar CSV-sini idxal edir |
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

1. `backend/radar/collectors/<ad>.py` faylında `FindingIn` obyektləri qaytaran funksiya yazın.
2. İşi `track_run("<ad>")` ilə əhatə edin, hər obyekti
   `upsert_finding(session, item, status_policy="keep")` ilə yazın — təkrarların silinməsi,
   `last_seen` və tarixçə orada idarə olunur.
3. `radar/tasks.py`-da `**RETRY` (eksponensial gözləmə) və `rate_limit` ilə Celery tapşırığı
   yaradın, `beat_schedule`-a cədvəl əlavə edin.
4. Sonda `run_linker(session, yeni_tapıntılar)` çağırın.

İşə düşmə **Kollektorlar** bölməsində say, xəta və müddətlə görünəcək.

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
