# AGENTS.md — AstraForce

Compact guidance for OpenCode sessions. Only non-obvious, repo-specific facts below.

## Repo shape
- Monorepo (pnpm workspace), packages under `apps/`: `api` (FastAPI, Python 3.12, `uv`) and `web` (Next.js 16, Tailwind v4, MapLibre GL v6).
- Root `package.json` orchestrates both via `pnpm --filter <api|web> ...`.
- Single `.env` at repo root is shared by docker compose, the API (`app/config.py` `ROOT_ENV`), and the web app (`@next/env`). Do **not** create per-app `.env` files.

## Required order (local)
```
pnpm db:up          # Docker PostGIS 17 + H3 on port 5433
pnpm db:migrate     # apply db/migrations/NNN_*.sql
pnpm ingest all --country AZ,TR,US,AR,GR,PT   # idempotent, resumable (~1 h first time)
pnpm harmonize run --country AZ,TR,US,AR,GR,PT
pnpm dev            # web :3000 + API :8000 (concurrently)
```
- `pnpm db:reset` wipes the DB volume (all ingested data), re-runs `db/init/*.sql` and migrations.
- Supported countries: AZ, TR, US, AR, GR, PT. Add a new country with `pnpm add-country --code XX --name "Adı" --archive-name "Arşiv_Adı" --bbox "w,s,e,n"` (edits `sources.py` + `regions.ts`, then runs `ingest` + `harmonize`).

## PowerShell quirk (read this first)
On Windows PowerShell, `--country AZ,TR,US` arrives as `"AZ TR US"`. List arguments must be split on commas **and** whitespace (handled in `apps/api/app/ingest/sources.py` and the harmonize CLI).

## Commands
| What | Command | Notes |
|------|---------|-------|
| All tests | `pnpm test` | vitest (web) + pytest (api) |
| All lint | `pnpm lint` | `tsc --noEmit` (web) + `ruff check` (api) |
| E2E responsive tests | `pnpm test:e2e` | Playwright (mobile + desktop viewports) |
| Build web | `pnpm build` / `pnpm --filter web build` | |
| Single API test | `cd apps/api && uv run pytest tests/test_parse.py::test_acq_time_padding` | `db`-marked tests hit real DB in rolled-back txn, skip if DB down |
| Single web test | `pnpm --filter web exec vitest run -t "bboxes"` | |
| Daily refresh | `pnpm --filter api run update` | **Must use `run`**. Without `run`, pnpm's built-in `update` silently bumps dependencies instead. |
| DB shell | `pnpm db:psql` | |
| Dump / restore | `pnpm db:dump` / `scripts/restore-db.sh` | |
| Burned area ingest | `pnpm --filter api ingest burned_area --country XX --year YYYY --month N` | MODIS MCD64A1 / VIIRS VNP64A1 via NASA Earthdata (requires `EARTHDATA_USER` / `EARTHDATA_PASS` in `.env`) |

## Framework/toolchain quirks
- **MapLibre v6**: no default export (`import * as maplibregl`), and its Web Worker can't be bundled by Turbopack. `apps/web/scripts/copy-maplibre-worker.mjs` runs in `predev`/`prebuild` and copies the worker to `public/maplibre/`; `FireMap.tsx` calls `setWorkerUrl`. MapLibre is client-only via `next/dynamic(ssr: false)`.
- **API health**: `/health` never throws. If the DB is down it returns `status: "degraded`; the connection pool opens lazily so the API starts even without DB.
- **ROI state machine**: `pending → running → ready/error`, claimed atomically in SQL (`claim_roi`), heartbeat staleness after 10 min, `MAX_CONCURRENT_ROI=2`. A harmonize run resets ROIs of that country to `pending` (stale results dropped).
- **Ingest**: one run at a time via Postgres advisory lock (`INGEST_LOCK_ID`); second run exits code 3. Each file/API window is one transaction recorded in `ingest_log`. Raw downloads cached in `data/raw/`.
- **`/detections`**: caps range at 31 days, result at 20k points (strongest FRP first); hides `fire_type=2` and confidence 0 by default.

## Data / calibration
- `HFI_VERSION = "hfi-v2"` in `apps/api/app/harmonize/settings.py`. Bump it when the method changes.
- Pipeline: `mask.py` → `events.py` (ST-DBSCAN 1.5 km / 1 day) → `calibrate.py` (ratio / log-linear / random forest, leave-one-year-out) → `apply.py`.
- Never compare raw MODIS and VIIRS counts directly; always go through `harmonized_daily`.
- `FIRMS_MAP_KEY` required only for current-year NRT via FIRMS Area API; yearly country archives need no key.

## What's been removed (local-only now)
- `render.yaml`, `docker-compose.prod.yml`, `deploy/Caddyfile` are archived under `deploy/archive/`. No Render/Caddy/production flow. Focus is local Docker Compose (`docker-compose.yml`, DB on 5433).

## Existing instruction file
- `CLAUDE.md` at root has additional operational detail (commands, layout, ingestion, harmonization, areas). It remains authoritative where it overlaps; this file is the condensed agent reference.