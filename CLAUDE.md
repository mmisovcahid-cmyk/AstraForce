# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Always answer the user fully in Turkish. Do not write code until the user says START; plan and analyze first when asked to.

## Status

AstraForce harmonizes NASA FIRMS MODIS and VIIRS active-fire hotspots into one consistent 2000 → today record and shows it as a "fire calendar" for preset countries or user-drawn areas. It was built for the NASA Space Apps 2026 challenge "Harmonization of MODIS and VIIRS Hot Spots"; README.md maps each challenge objective to a feature and is the current feature list.

- **Local-only.** The Render/Caddy/prod-compose files were moved to `deploy/archive/` and are not maintained. `apps/*/Dockerfile`, the `DB_HOSTPORT` branch in `app/config.py` and `db/init/02-restore-dump.sh` (a no-op without `DUMP_URL`) only served that setup. Only `docker-compose.yml` (the DB) is live.
- Countries: AZ, TR, US, AR, GR, PT, about 24 M detections (ES was dropped: its archive never loaded). NOAA-21 (`VIIRS_NOAA21`, from 2023) comes from the FIRMS API only (there are no yearly country files), so it is often only partially loaded.
- Recent additions, partly unfinished (see "Known broken"): the `pnpm add-country` wizard, a static heat sources map layer (`routes/static_sources.py`, serves `static_mask` cells), a burned-area layer (`routes/burned_area.py`, migration 009) and Playwright E2E tests.

`plan.pdf` (gitignored, local only) is the original design doc (Azerbaijani, **image-only**: `pdftotext` returns nothing; render pages with PyMuPDF and view them). Other docs: `docs/METHODS.md` and `docs/LIMITATIONS.md` (method write-up and scientific caveats), `START.md` (Turkish setup guide for end users), `AGENTS.md` (condensed copy of this file for other agents; keep the two in sync, this one wins on conflicts). `config.yaml` and `scripts/synthetic_generate.py` are **not read by any app code**; the real parameters live in `harmonize/settings.py` and `ingest/sources.py`.

## Commands (run from repo root)

| Command | What it does |
|---|---|
| `pnpm setup:all` | One-shot setup (`scripts/setup.mjs`): creates `.env` from `.env.example` if missing or empty, `pnpm install`, `uv sync` (fetches Python 3.12), builds/starts the DB container, runs migrations |
| `pnpm dev` | Web on :3000 and API on :8000 together (`concurrently -k`). The API runs **without** `--reload`: on Windows the reload hangs, exits, and `concurrently -k` then kills the web server too. Use `pnpm --filter api dev:reload` if you want reload; otherwise restart after backend edits. Claude preview config: `astraforce-dev` in `.claude/launch.json` |
| `pnpm ingest all --country AZ,TR,US` | Boundaries + yearly archives 2000..last year + the current year via the FIRMS API (NOAA-21 from 2023 via the API too). Resumable/idempotent; rerun to refresh NRT. `all` and `api` need `FIRMS_MAP_KEY` in `.env` (exit 2 without it); `archive` needs no key |
| `pnpm ingest archive --country TR --years 2010-2012 --sources modis,snpp` · `pnpm ingest api --country AZ --from 2026-10-01` · `pnpm ingest status` · `pnpm ingest boundaries` | Partial loads / summary. Source aliases: `modis,snpp,noaa20,noaa21`. `--force` reloads logged items |
| `pnpm harmonize run --country AZ,TR` · `--steps mask,events,calibrate` · `pnpm harmonize status` | Rebuilds the static mask, events, calibration and HFI (idempotent; ~30 s per country for AZ/TR, ~10 min for a multi-country run, mostly US event clustering). Rerun after every ingest. `status` lists each candidate model's leave-one-year-out metrics |
| `pnpm update:daily` (`app/update.py`; `--bootstrap` for an empty DB, `--country`, `--optimize`) | Daily refresh: `ingest api` from Jan 1 for each country, then `harmonize` (the mask step only on Mondays). Each run is logged in `update_run` (shown via `/health`). Called directly it must be `pnpm --filter api run update`: without `run`, pnpm's built-in `update` bumps dependencies instead |
| `pnpm db:migrate` | Applies new `db/migrations/NNN_*.sql`, each in one transaction, tracked by file name in `schema_migrations`. Only `setup:all` and `db:reset` run it for you |
| `pnpm db:optimize` (`app/optimize.py`) | CLUSTERs `fire_detection` by location + ANALYZE; speeds up first computation of large ROIs. Locks the table and needs free disk the size of the table (~10 GB): never run alongside ingest/harmonize; `--bootstrap` does not run it |
| `pnpm db:dump` | `pg_dump -Fc` via `docker compose exec` into `data/dumps/astraforce.dump`. There is no working local restore (see "Known broken") |
| `pnpm db:up` / `db:down` / `db:reset` / `db:logs` / `db:psql` | Docker DB lifecycle; `db:reset` wipes the volume (all ingested data!), re-runs `db/init/*.sql` and migrations |
| `pnpm add-country --code XX --name "Name" --archive-name "Archive_Name" --bbox "w,s,e,n"` | `scripts/add_country.py`: adds the country to `COUNTRIES` (`ingest/sources.py`) and `REGIONS` (`web/src/lib/regions.ts`), then runs ingest + harmonize. **Broken**, see "Known broken" |
| `pnpm ingest burned_area --country XX --year YYYY --month N` | MCD64A1 / VNP64A1 (`--sensor`) into `burned_area`. Placeholder: `_download_monthly` returns no rows, so it always loads 0; nothing reads `EARTHDATA_USER/PASS` yet |
| `pnpm test` | vitest (web) + pytest (api) |
| `pnpm test:e2e` | Playwright (`apps/web/tests/e2e`, desktop Chrome + Pixel 5 + iPhone 12); starts/reuses the web dev server on :3000. **Broken**, see "Known broken" |
| `pnpm lint` | `tsc --noEmit` (web) + `ruff check` (api: line length 100, rules E/F/I/UP/B) |
| `pnpm build` | Next.js production build |

Single tests: `cd apps/api && uv run pytest tests/test_parse.py::test_acq_time_padding` · `cd apps/api && uv run pytest -m "not db"` (without the database) · `pnpm --filter web exec vitest run -t "bboxes"`. Tests marked `db` need the running PostGIS and skip when it, or the data they read, is missing. Direct-connection tests (`test_load_db.py`, `test_areas.py`) run inside a `force_rollback` transaction; route tests read the real DB through `TestClient`.

Requires Docker Desktop running (WSL2) and `uv`. `docker` may not be on PATH in terminals opened before Docker was installed; it lives in `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`.

## Data flow

```
FIRMS yearly CSVs + area API --ingest--> fire_detection (raw rows of both sensors, h3_r8)
harmonize  mask.py                --> static_mask (H3 r8)
           events.py              --> detection_event, fire_event, daily_cell_stats (country x source x r5 x day)
           calibrate.py, apply.py --> calibration_model, harmonized_factor (country x day),
                                      harmonized_daily (r5 x day), harmonized_validation (country x year)
API        countries read harmonized_daily; an ROI is fire_detection + detection_event x harmonized_factor -> roi_daily (cache)
web        / = calendar (CalendarView), /map = map (Dashboard, FireMap), /validation, /about (method page)
```

Bookkeeping tables: `ingest_log` (one row per loaded file or API window; it also defines satellite coverage), `update_run`, `country_boundary` (Natural Earth 10m), `schema_migrations`.

## Layout and non-obvious wiring

- `apps/web` (Next.js 16, Turbopack, Tailwind v4, MapLibre GL v6, ECharts, terra-draw) and `apps/api` (FastAPI, psycopg 3 pool, pandas, scikit-learn, scipy; managed by `uv`, `package = false`) are both pnpm workspace packages; the api's `package.json` only wraps `uv run` so `pnpm --filter api ...` works. API CLIs: `python -m app.ingest`, `app.harmonize`, `app.migrate`, `app.optimize` and `app.update` (calls the ingest and harmonize `main(argv)` in-process).
- **One `.env` at the repo root** serves everything: docker compose reads it directly, the API loads it via `app/config.py` (`ROOT_ENV`), and `apps/web/next.config.ts` loads it with `@next/env`. Don't add per-app `.env` files. Ports are fixed in the package scripts (web 3000, API 8000; `API_PORT` in `.env` is unused). Hostnames in `CORS_ORIGINS` also become Next's `allowedDevOrigins`, so add an origin there to open the dev site from another host (e.g. a LAN IP).
- The browser calls the API directly at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`, inlined at build time; `lib/api.ts`). next.config adds an `/api/*` rewrite only when `API_INTERNAL_URL` is set (archived Render setup).
- DB: `db/Dockerfile` = `postgis/postgis:17-3.6` + `postgresql-17-h3`. Use 3.6 tags (trixie); 17-3.5 is bullseye and PGDG no longer serves bullseye, so the h3 install fails. Host port is **5433** (bound to 127.0.0.1). Extensions (postgis, h3, h3_postgis) are created by `db/init/01-extensions.sql`, which only runs on an empty volume.
- Schema changes go in a new `db/migrations/NNN_*.sql` (runner: `apps/api/app/migrate.py`), never in `db/init/`. Applied files are never re-run, so don't edit one that is already applied.
- MapLibre v6 has **no default export** (`import * as maplibregl`) and its Web Worker can't be bundled by Turbopack: `apps/web/scripts/copy-maplibre-worker.mjs` (run by `predev`/`prebuild`) copies it to `public/maplibre/` (gitignored) and `FireMap.tsx` calls `setWorkerUrl`. MapLibre is loaded client-only via `next/dynamic` with `ssr: false`.
- Map style is OpenFreeMap (no token), configurable via `NEXT_PUBLIC_MAP_STYLE_URL`. The browser also calls NASA GIBS (land cover overlay) and Photon (place search, `PlaceSearch.tsx`); neither needs a key.
- i18n is a plain dictionary in `apps/web/src/lib/i18n.ts` (AZ, EN; the default is EN, overridable via `NEXT_PUBLIC_DEFAULT_LOCALE`, see `useLocale.ts`). A test enforces that both locales have identical keys. A missing `region.<ID>` name is caught only by `tsc`: at runtime `translate()` falls back to the raw key. Preset countries and their map bboxes are `REGIONS` in `src/lib/regions.ts`; the API side is `COUNTRIES` in `ingest/sources.py` (FIRMS archive name + API bboxes). The two lists must match.
- API `/health` never throws: DB failure is reported as `status: "degraded"`; the pool opens lazily so the API starts even when the DB is down.
- **Language conventions**: code comments, docstrings, CLI output and API error messages are written in Turkish; keep that. UI text goes through `i18n.ts` (AZ + EN), never hard-coded. Test function names are English.

## Data ingestion (`apps/api/app/ingest/`)

- **Two FIRMS inputs.** (1) Yearly per-country CSVs `firms.modaps.eosdis.nasa.gov/data/country/{modis|viirs-snpp|viirs-jpss1}/{year}/..._{archive_name}.csv` (`Country.archive_name`, e.g. `Turkey`, `United_States`): no key, no rate limit, SP data, 2000..last year. NOAA-20's directory is `viirs-jpss1`; there is none for NOAA-21. (2) The area API `/api/area/csv/{key}/{SOURCE}/{w,s,e,n}/{1-5 days}/{start}` for the current year: max 5 days per request, `DATE` is the window start. The country API endpoint returns "Invalid API call", so API rows are fetched by bbox (`COUNTRIES[..].api_bboxes`, US split at the antimeridian) and clipped to the `country_boundary` polygon (Natural Earth 10m) in SQL.
- `sources.plan_windows` uses `/api/data_availability` to fetch SP up to its max date and NRT after it. When an SP window lands, the NRT rows of those days are deleted (`delete_nrt`), so a fire is never counted twice. SP windows are logged once; NRT windows are refetched every run.
- API limit: 5000 transactions / 10 min, and a large bbox (US) counts as several. Requests are paced 0.25 s apart; a "transaction limit" reply waits 2 min and retries (up to 8 times). Error messages mask the key.
- `fire_detection` holds raw detections in one schema for both sensors, with natural key `(source, acq_ts, lat, lon)` and `ON CONFLICT DO NOTHING`. `confidence_level` is normalized to 0/1/2 (MODIS <30 / <80 / ≥80; VIIRS l/n/h) and `confidence_raw` keeps the original. `fire_type` 2 = static industrial source (gas flares); NRT has no `type` column, so it is NULL there. `h3_r8` is precomputed; get coarser cells with `h3_cell_to_parent`. Use `h3_latlng_to_cell`, not the deprecated `h3_lat_lng_to_cell`.
- Loading is CSV → `normalize()` (header-name based; NRT `acq_time` lacks zero padding) → `COPY` into a temp `stage_fire` → `INSERT ... SELECT` that computes geom/h3. Each file or API window is one transaction (the CLI connection is autocommit) and is recorded in `ingest_log` (`key` = `archive:SRC:CC:YEAR` / `api:FIRMS_SOURCE:CC:start:days`).
- Raw downloads (including the Natural Earth GeoJSON) are cached in `data/raw/` (gitignored); re-runs do not re-download.
- Only one ingest runs at a time: a Postgres advisory lock (`INGEST_LOCK_ID`), and the second run exits with code 3; `harmonize` has its own lock and does the same. `status` skips the lock. Two runs at once used to crash on Windows when both renamed the same `.part` file; temp files are now per-PID.
- PowerShell turns `--country AZ,TR,US` into `"AZ TR US"`, so list arguments split on commas and whitespace.
- `/detections` caps the range at 31 days and the result at 20k points (strongest FRP first). By default it hides `fire_type=2` and confidence 0.

## Harmonization (`apps/api/app/harmonize/`, parameters in `settings.py`)

The HFI (Harmonized Fire Index) is MODIS-equivalent. hfi-v2 calibrates **two targets**: `det`, the hotspot count (the default UI metric, stored as `harmonized_daily.hfi_det`), and `evt`, the event-days (`hfi`). FRP is a ratio model only. Pipeline: `mask.py` → `events.py` → `calibrate.py` → `apply.py`. Everything is derived from `fire_detection` and fully rebuilt on each run. Bump `HFI_VERSION` when the method changes.
1. **Static mask** (`static_mask`, r8): NASA `type=2` cells, plus cells with detections on ≥100 days in ≥5 years, dilated by one H3 ring. It is needed because NRT has no `type`, and type=2 is ~25% of VIIRS points in TR versus ~3% for MODIS. The mask is global: the mask step truncates and rebuilds it for all countries even with `--country`, while only the listed countries get new events.
2. **Cleaning**: confidence ≥ nominal, `coalesce(fire_type,0)=0`, not masked.
3. **Events**: ST-DBSCAN with `min_samples=1` reduces to connected components within 1.5 km / 1 day. It uses BallTree haversine and runs in yearly chunks with an `EPS_DAYS` carry-over plus union-find. Clustering is per source (MODIS = Terra+Aqua). The daily metric is `n_evt`, distinct events per r5 cell-day. Note: clustering did **not** close the sensor gap; VIIRS/MODIS is still ~2.6–2.9× at event level, because VIIRS sees whole small fires MODIS misses. Calibration does the real work.
4. **Series** (`build_series`): VIIRS = **mean** of SNPP, NOAA-20 and NOAA-21 (`VIIRS_SOURCES` in `settings.py`) over satellites that delivered data that day. Coverage is per country (`load_coverage`): the source has a loaded `ingest_log` item for that country and ≥1 raw detection that day in any country, which separates "no fire" from an outage, so a partially loaded satellite such as NOAA-21 does not drag the mean down. Summing them would create a false jump in 2018. MODIS before 2002-07-04 (Terra only) is scaled by the per-country (Terra+Aqua)/Terra ratio from 2003–2007.
5. **Calibration** (`calibrate.py`): each target is the country-day MODIS value (`m_det`, `m_evt`), trained on 2012+ days where both sensors delivered SP data. Candidates: `viirs_raw` (baseline, not selectable), `ratio` (month × ±2-year rolling window with shrinkage to the window ratio, which captures MODIS orbit drift), `loglinear`, `random_forest`. Each is scored with leave-one-year-out (years with ≥300 overlap days); the winner has the lowest mean |annual bias|, ties broken by daily r. The season metric is the mean shift of the 10/50/90% cumulative-fire dates, not the argmax, because TR/AZ have bimodal seasons.
6. **Apply** (`apply.py`): the per-target predictions become **country × day factors** in `harmonized_factor`. On VIIRS days, factor = prediction ÷ country VIIRS satellite-mean. On MODIS days, factor = Terra scale or 1. The factors are multiplied with H3 cell values (`harmonized_daily`) and with ROI values (`areas.harmonize_roi`), so an area's total equals the sum of its parts. NRT-derived rows are `provisional`. The events step also writes `detection_event(detection_id, event_no)` for the cleaned detections, so ROI queries can count event-days, and "has a detection_event row" == "used in harmonization". A harmonize run sets every ROI of that country back to `pending`, so ROIs are recomputed on the next view.
- Current results (`pnpm harmonize status`, hotspot target, mean |annual bias|): US rf 2.1 %, AR rf 3.2 %, TR ratio 4.4 %, PT rf 6.6 %, AZ rf 7.9 %, GR ratio 8.5 %; uncalibrated VIIRS is +170–280 %.
- The yearly HFI in `harmonized_validation` for 2012+ comes from the final model fitted on all years (in-sample). The honest numbers are the leave-one-year-out `calibration_model.metrics`.
- Never compare raw MODIS and VIIRS counts directly; always go through `harmonized_daily`.

## Areas, calendar and analytics (`app/areas.py`, `app/analytics.py`, `routes/{analytics,roi,export}.py`, `CalendarView.tsx`)

- **Area** = a preset country (`TR`) or a user ROI (`roi:<id>`). Every analytics and export endpoint takes `area=` and `metric=hotspots|events|frp`. `areas.daily_series()` returns one daily frame for both: countries come from `harmonized_daily`, ROIs from the `roi_daily` cache.
- **ROI**: `POST /roi` accepts `{geojson}` or `{circle:{lat,lon,radius_km}}`. The geometry is made valid in SQL, and the area must be between 1 km² and 3.5 M km² and intersect a loaded country (`covered_pct` is reported). The id is a hash of the geometry, so the same shape reuses its cache. Computation runs in a FastAPI BackgroundTask, year by year, with progress in `roi.progress`. Analytics answer **202 {status, progress}** until it is ready; the UI polls `GET /roi/{id}`. A Manavgat 30 km circle takes about 3 s.
- **ROI state machine** (`areas.claim_roi`, migration 008): the work is claimed atomically in SQL (`pending`, or `running` whose `heartbeat_at` is older than `ROI_STALE_AFTER`), so several uvicorn workers never compute one ROI twice; at most `MAX_CONCURRENT_ROI` run at once (the rest stay `pending` and are claimed on a later poll). Nothing is reset on API start. Progress updates and the final `ready` write only `WHERE status = 'running'`: if a harmonize run reset the ROI to `pending` mid-computation, the stale result is dropped (`_Superseded`). `error` is never retried automatically; the UI shows a Retry button that calls `POST /roi/{id}/retry`.
- **The metrics disagree on purpose.** Hotspots and FRP peak with big forest fires (TR 2021-07-28, Manavgat). Events peak with many small agricultural burns (TR in November).
- **Colour levels** 0..4 are computed on the fly per area from its own fire days in 2001..last full year (≤p50/≤p80/≤p95/>p95; `levels()` uses `searchsorted(side="left")`). The `hfi_scale` table is obsolete and unused.
- **Anomalies** are measured against the **median** of the 2001..last-full-year base years: `month_matrix` per month (the current month is compared with the same days of past years), `current_status` (month-to-date and last 7 days), `/analytics/range`. If the median is < 1, no percentage is given, because the result would be meaningless. All analytics are computed **as of the area's last data day** (`areas.data_until` = last `harmonized_factor` day, the most lagging country for an ROI), not today: FIRMS lags 1–2 days, and counting those days as "no fire" biased every anomaly low. Calendar days after it are `null`; `/analytics/range` clips to it and reports `effective_date_to`.
- **Exports**: `/export/hotspots.csv` streams raw FIRMS rows via COPY (cap 2 M, sent as `X-Row-Limit`; at most `MAX_CONCURRENT_EXPORTS` streams per worker hold pool connections, the rest wait outside the pool) with `used_in_harmonization` and `static_source_mask` flags. Also `/export/daily.csv` and `/export/matrix.csv`. Charts have an ECharts PNG button (canvas renderer). "Print report" calls `window.print()` (controls are `print:hidden`).
- Page state lives in the URL via `lib/url.ts` (plain `window.location`, not `useSearchParams`): calendar `/?area=TR|roi:…&year=&mode=mean&metric=&compare=&from=&to=` (a legacy `region=` is still read), map `/map?region=&area=&date=&range=&layer=density&draw=1`. The map draws polygons with **terra-draw** (`FireMap` `drawing` prop); finishing one calls POST /roi and navigates to `/?area=roi:…`.
- Ramps live in `lib/calendar.ts` (`RAMPS.fire`, `RAMPS.cividis`, `ANOMALY_COLORS`); the choice is saved in localStorage (`useRamp`). Azerbaijani month and day names are hard-coded, because Chromium Intl has no `az` data.
- Dev gotchas: stopped previews can leave an orphaned uvicorn on :8000, which serves stale code and 404s new routes. Check it with `Get-NetTCPConnection -LocalPort 8000`. The hidden Claude browser pane does not paint scrolled canvases in screenshots; check charts via DOM or canvas pixels instead.

## Known broken (checked 2026-11-14)

- **`pnpm add-country`**: on Windows its `subprocess.run(["pnpm", ...])` raises `FileNotFoundError` (pnpm is a `.cmd` shim), right after it has edited `sources.py` and `regions.ts`. It also passes `--years` to `ingest all`, which rejects it, and it adds no `region.XX` names to `i18n.ts`, so `pnpm lint` fails and the UI shows the raw key. Its edits are idempotent. By hand: add the names in both locales, then `pnpm ingest all --country XX`, `pnpm harmonize run --country XX`, and restart the API.
- **Burned area**: ingest loads nothing (see Commands). In `routes/burned_area.py` the country branch of both endpoints passes more parameters than the SQL has placeholders, and `GET /burned-area` orders by a non-aggregated column next to `json_agg`, which PostgreSQL rejects. The map toggle hides the errors.
- **`pnpm test:e2e`**: `@playwright/test` is not installed (only `playwright`), and `responsive.spec.ts` opens `/` (the calendar) while the map and the `map-panel` toggle it checks are on `/map`.
- **Restore**: `scripts/restore-db.sh` still targets the archived `docker-compose.prod.yml`.
- README's "Demo / synthetic data" section doesn't work: `scripts/synthetic_generate.py` writes files outside the `data/raw/country/...` layout that ingest reads.

## Background (from plan.pdf)

Raw fire-point counts from the two sensors can't be compared directly. MODIS pixels are about 1 km and VIIRS I-band pixels 375 m, so VIIRS sees many more small fires (one fire can show up as about 10 VIIRS pixels against 1 MODIS pixel). MODIS runs from 2000 (Terra) and 2002 (Aqua); VIIRS from 2012 (Suomi-NPP), then NOAA-20 (2018) and NOAA-21 (2023), so joining the records naively creates a false upward trend after 2012. Overpass times and viewing angles differ too.

The plan's method ideas (H3 binning, overlap calibration with regression or Random Forest, ST-DBSCAN events, confidence filtering) are implemented as described above, with one exception: there is no cross-sensor deduplication, because each day uses either calibrated VIIRS or MODIS, never both. Decided: PostGIS (not DuckDB), MapLibre (not Mapbox/Leaflet), UI languages AZ + EN. Data: NASA FIRMS MODIS C6.1 (MCD14) and VIIRS 375 m (VNP14IMG / VJ114IMG / VJ214IMG); MCD12Q1 land cover is only a visual overlay.
