# Black Market Radar — architecture

## Shape

```
                 ┌──────────────── single Linux VPS (docker compose) ────────────────┐
  Apify ───────► │  worker (Celery)          beat (Celery scheduler)                 │
  SERP API ────► │   ├ collectors/*  ──► normalize ► dedup upsert ► classify queue   │
  CertStream ──► │   ├ enrichment     (RDAP, DNS, CF, abuse, redirects, Playwright)  │
  Telethon ────► │   ├ classify       (rules ► Claude Haiku ► review queue)          │
  Stores ──────► │   └ reports        (Telegram digest, PDF, Excel template)         │
                 │          │                                                        │
                 │      Redis (broker)        PostgreSQL 16        /data/evidence    │
                 │          │                     ▲                (screens, HTML)   │
                 │   api (FastAPI) ───────────────┘                                  │
                 │          ▲                                                        │
                 │   web (Next.js, TypeScript)  ◄── Caddy (TLS, basic hardening)     │
                 └───────────────────────────────────────────────────────────────────┘
  AZ probe agent (laptop in Baku) ──HTTPS + token──► api /probe  (block checks)
```

* **Python package `radar`** holds everything server-side: SQLAlchemy models, Alembic
  migrations, collectors, enrichment, classification, importers, the FastAPI app and a
  CLI (`radar ...`). Workers and API share one image.
* **Queue**: Celery + Redis. Each collector is a task with `autoretry_for`, exponential
  backoff + jitter, per-collector rate limits and a schedule in `beat`. Every run writes a
  `collector_runs` row (found / new / updated / errors / duration).
* **Web**: Next.js App Router + TypeScript, server components calling the API. No UI kit;
  hand-written CSS tokens (IBM Plex Sans / Plex Mono, one red-orange signal accent).
* **Evidence** lives on disk (`/data/evidence/<yyyy>/<mm>/<finding>/<capture>.png|html`);
  each capture is a row in `evidence` with SHA-256 and `captured_at`. Back up with the DB.

## Data model (Phase 1)

| table | purpose |
|---|---|
| `findings` | one row per unique entity. `source`, `entity_type`, `url`, **`canonical_key` (unique)**, title/text, media, first/last_seen, operator, keywords, AI fields, status + funnel timestamps, category / suggested action, metrics (views, followers, subscribers, likes), raw JSON, enrichment JSON |
| `evidence` | captures per finding (screenshot / html / favicon), path, SHA-256, captured_at. History kept — a finding can have many captures |
| `operators` | brands (Pin-Up, Mostbet, 1win, Pinco …) with aliases and `is_licensed` |
| `links` | edges finding↔operator and finding↔finding: `operator`, `favicon_hash`, `redirect`, `promo_code`, `payment_method`, `telegram_link`, `app_package`, `landing`, `ad_cluster`, `mentions_domain` |
| `finding_events` | history: detected, re-detected, status change, enrichment, label |
| `keywords`, `whitelist` | editable from Settings; all collectors and rules read from here |
| `collector_runs` | run log shown in UI |
| `import_batches` | each import with its data-quality report |

**Dedup**: `canonical_key = <entity-kind>:<normalized id>` — host without `www.` for web,
ad-library id for Meta, package for Play, numeric id for App Store, lowercase username
for Telegram / TikTok / Instagram (invite hashes stay case-sensitive), video/post id for
posts. Upsert = `INSERT … ON CONFLICT (canonical_key) DO UPDATE last_seen, merge fields`.

## Phases
1. Foundation — schema, dedup, importers (seed CSV, original workbook, Apify exports),
   enrichment worker, data-quality report, compose, minimal UI shell.
2. Collectors — CT/crt.sh, SERP, Meta Ads (Apify + OCR), TikTok, IG/FB, Telegram, stores.
3. Classification — rules → Claude Haiku (with images, few-shot from labels) → Review Queue.
4. Dashboard — date-range everywhere, per-source pages, operators graph, search.
5. Leadership — exposure index, funnel & mirror rotation, AZ probe, impersonation,
   influencers, payment rails, evidence packages, reports, auth + roles.
