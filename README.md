# Black Market Radar

Internal Azerlotereya tool for finding and documenting **unlicensed gambling promotion in Azerbaijan**:
domains, Meta ads, TikTok, Instagram, Facebook, Telegram, Play Store and App Store.
Rule: any gambling / betting / casino promotion not from the licensed whitelist
(Azerlotereya, Topaz / Etopaz, TFC) is illegal.

Azərbaycan dilində: [README.az.md](README.az.md) · Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

| Part | Path | Stack |
|---|---|---|
| Workers, importers, API, CLI | `backend/` | Python 3.12, SQLAlchemy, Alembic, Celery + Redis, FastAPI, Playwright |
| Dashboard (Azerbaijani UI) | `web/` | Next.js 15, TypeScript, plain CSS |
| Database | — | PostgreSQL 16 |
| Edge | `deploy/Caddyfile` | Caddy (TLS + basic auth) |

## Status

**Phase 1 (foundation) and Phase 2 (collectors) are done.** Phases 3–5 (AI classification
with review queue, full dashboard, leadership features) are next.

## Collectors

| Name | Source | Needs | Default schedule (Baku) |
|---|---|---|---|
| `ct_crtsh` | crt.sh certificate search for every operator alias and protected brand | — | every 6 h |
| `certstream` | live CertStream feed (own service, runs continuously) | — | continuous |
| `serp_google` | Google via SerpAPI, gl=az, in az / ru / tr / en, rotating queries | `SERP_API_KEY` | 06:10, 14:10 |
| `meta_ads` | Meta Ads Library (AZ) via Apify: keywords + tracked pages, OCR + image hash | `APIFY_TOKEN` | 07:35, 19:35 |
| `tiktok` | TikTok via Apify: hashtags, search, tracked + known accounts | `APIFY_TOKEN` | 08:50, 20:50 |
| `instagram` | Instagram via Apify: account search, bios, hashtag + account posts | `APIFY_TOKEN` | 09:05, 21:05 |
| `facebook` | Facebook page posts via Apify | `APIFY_TOKEN` | 10:25 |
| `telegram` | Telethon: channel search, new posts, invite links | `TELEGRAM_API_ID/HASH` + login | every 2 h |
| `stores` | Play Store + App Store (AZ): search, re-check known apps, disguised games | — | 11:15 |

Every collector reads the keyword list and tracked accounts from **Ayarlar**, skips the
licensed whitelist, logs each run to `collector_runs` (visible in **Kollektorlar**, with
"İndi işə sal" and on/off), and retries with exponential backoff. A collector without its
key is recorded as *skipped* rather than failing. Parameters (limits, actor IDs) have
defaults in code and can be overridden per collector via `PUT /api/collectors/{name}`.

```bash
radar collectors                       # list, schedule, missing secrets
radar collect ct_crtsh -p days=1       # run one now (with parameter overrides)
radar track tiktok_account kod_satisi  # add a tracked account (also in Ayarlar)
```

**Telegram login (once):** with `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` in `.env`, run
`docker compose run --rm api radar telegram-login`, enter the dedicated account's phone
number and the code Telegram sends. The session is stored in the `telegram` volume.

## Local setup

```bash
# Postgres 16 and Redis running locally
createuser -P radar && createdb -O radar radar        # password: radar

python3 -m venv .venv && . .venv/bin/activate
pip install -e "backend[dev]"
playwright install chromium                          # screenshots

cd backend
radar migrate
radar seed                                           # operators, keywords, whitelist
radar import-seed ../data/import/findings_seed.csv   # or: radar import-workbook <file.xlsx>
radar report                                         # data-quality report
uvicorn radar.api.main:app --port 8000

cd ../web && npm install && API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Tests (need a `radar_test` database owned by `radar`):

```bash
cd backend && pytest
```

## Deploying to a VPS

Target: Ubuntu 22.04/24.04, 4 vCPU, 8 GB RAM, 80 GB disk. Point the domain's DNS A record at
the server first (Caddy then gets a TLS certificate automatically).

```bash
git clone https://github.com/namiraaslanli-azl/blackmarketradar.git /opt/radar && cd /opt/radar
# optional: copy the historical seed into data/import/ first (from your computer):
#   scp Qara_Bazar_Import_Seed.xlsx root@SERVER_IP:/opt/radar/data/import/
sudo bash deploy/install.sh
```

The installer installs Docker, asks for the domain and a login password, writes `.env` with
random secrets, builds and starts everything, imports the seed if present, starts domain
enrichment and sets up a daily database backup. Re-run it after editing `.env` (e.g. adding
API keys) or after `git pull`; it keeps your settings. The whole site is behind the login
until Phase 5 adds user accounts with roles.

## Everyday commands

| Command | What it does |
|---|---|
| `radar import-seed FILE.csv|.xlsx` | Import the normalized findings seed (CSV, or Excel with a "Findings" sheet) |
| `radar import-workbook FILE.xlsx` | Import the original weekly workbook (all sheets) |
| `radar import-apify FILE...` | Import Apify dataset exports (JSON / JSONL / CSV) |
| `radar link` | Re-run operator matching, mirror patterns, impersonation, ad clustering |
| `radar enrich [--limit N] [--force] [--queue]` | RDAP/WHOIS, DNS, Cloudflare, abuse contacts, redirects, HTML, favicon, screenshot |
| `radar report` | Data-quality report |

Imports are idempotent: re-importing a file adds nothing new, and statuses only move
forward along the funnel (new → confirmed → reported → blocked).

## Adding keywords and whitelist entries

Use **Ayarlar** (Settings) in the dashboard. Every collector and rule reads from these
tables, so changes apply on the next run. Seed values live in `backend/radar/seeds.py`;
`radar seed` only adds missing rows and never overwrites your edits.

## Adding a collector

1. Create `backend/radar/collectors/<name>.py` with a subclass of `Collector`:
   `name`, `title` (Azerbaijani, shown in the UI), `schedule` (crontab kwargs),
   `defaults` (parameters), `requires` (settings that must be set, e.g. `("apify_token",)`)
   and `collect(ctx)` yielding `FindingIn` objects. Use `ctx.terms(...)` for keywords,
   `ctx.targets[...]` for tracked accounts and `ctx.error(...)` for per-item problems.
   For HTTP use `radar.collectors.http.request` (retries, backoff, per-host pacing); for
   Apify use `radar.collectors.apify.Apify().run_actor(...)`.
2. Import the module in `radar/collectors/__init__.py`.

That is all: the framework handles deduplication, whitelist exclusion, run logging,
linking, the Celery schedule and the UI row. Optional hooks: `after_upsert` (per item,
e.g. OCR) and `after_run`. Add a test in `backend/tests/test_collectors.py` with the
external service mocked.

## Database backup

```bash
# daily dump, keep 14 days (add to root's crontab)
0 3 * * * cd /opt/radar && docker compose exec -T db pg_dump -U radar -Fc radar > backups/radar-$(date +\%F).dump && find backups -name '*.dump' -mtime +14 -delete

# evidence files (screenshots, HTML) are in the "evidence" volume
docker run --rm -v radar_evidence:/e -v $PWD/backups:/b alpine tar czf /b/evidence-$(date +%F).tgz -C /e .

# restore
docker compose exec -T db pg_restore -U radar -d radar --clean < backups/radar-2026-10-23.dump
```

Copy `backups/` off the server (rsync / object storage): evidence hashes are only useful
if the files survive.

## Secrets

All secrets live in `.env` (never committed). See `.env.example`.
