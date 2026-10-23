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

**Phase 1 (foundation) is done:** schema, deduplication, importers (seed CSV, original
workbook, Apify exports), offline linker, enrichment worker, data-quality report,
dashboard shell, Docker Compose. Phases 2–5 (collectors, AI classification, full
dashboard, leadership features) are next.

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

Tested target: Ubuntu 24.04, 4 vCPU, 8 GB RAM, 80 GB disk.

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh

# 2. Code and secrets
git clone <repo> /opt/radar && cd /opt/radar
cp .env.example .env && nano .env              # set passwords, SITE_ADDRESS, API keys
docker compose run --rm caddy caddy hash-password --plaintext 'your-password'   # → BASIC_AUTH_HASH

# 3. Start (runs migrations and seeds on api start)
docker compose up -d --build

# 4. Historical data
mkdir -p data/import && cp findings_seed.csv data/import/
docker compose exec api radar import-seed /data/import/findings_seed.csv
docker compose exec api radar enrich --queue     # enrich all domains in the background
docker compose exec api radar report
```

Point the domain's DNS A record at the VPS; Caddy gets a TLS certificate automatically.
The whole site is behind basic auth until Phase 5 adds user accounts with roles.

## Everyday commands

| Command | What it does |
|---|---|
| `radar import-seed FILE.csv` | Import the normalized findings CSV |
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

1. Create `backend/radar/collectors/<name>.py` with a function that yields `FindingIn`
   objects (see `radar/importers/apify.py:item_to_finding` for Apify-based sources).
2. Wrap the run in `track_run("<name>")` and write each item with
   `upsert_finding(session, item, status_policy="keep")` — deduplication, `last_seen`
   updates and history are handled there. Count `stats.found / new / updated`.
3. Register a Celery task in `radar/tasks.py` with `**RETRY` (exponential backoff) and a
   `rate_limit`, and add a `beat_schedule` entry.
4. Call `run_linker(session, new_findings)` at the end so operators, links and derived
   findings are created.

The run then appears in **Kollektorlar** with counts, errors and duration.

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
