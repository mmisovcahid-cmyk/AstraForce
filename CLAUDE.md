# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Always answer the user fully in Turkish. Do not write code until the user says START; plan and analyze first when asked to.

## Status

Done: phases 1–5 plus deploy prep. Countries: AZ, TR, US, AR, GR, PT (ES was dropped: its archive never loaded). Render: web proxies /api/* to the API over the private network (`API_HOSTPORT` build arg → next.config rewrites), and coverage is per country (`load_coverage(conn, country)` joins ingest_log), so partially loaded satellites such as NOAA-21 do not bias the VIIRS mean. FIRMS API rate-limit errors now wait 2 min and retry. Phase 1: skeleton (monorepo, PostGIS + H3, FastAPI, Next.js, AZ/EN). Phase 2: FIRMS ingestion for AZ/TR/US/AR, MODIS + VIIRS SNPP + NOAA-20 (23.4 M rows). Phase 3: harmonization. Phase 4: calendar UI. Phase 5, the NASA Space Apps 2026 requirements: user areas (draw / lat-lon-radius / GeoJSON), the harmonized **hotspot count** as the default metric, the month × year matrix, anomalies vs the median, a status card, date ranges, CSV/PNG/print exports, a colorblind-safe ramp, EN as the default language, git, an English README, and a production Docker setup (not deployed yet: that needs a VPS and a domain from the user). NOAA-21 (`VIIRS_NOAA21`, from 2023) is ingested via the FIRMS API only (no yearly country files), so it is often only partially loaded. The competition brief is the Space Apps challenge "Harmonization of MODIS and VIIRS Hot Spots"; README.md maps each objective to a feature.

`plan.pdf` is the original design doc (Azerbaijani, **image-only**: `pdftotext` returns nothing; render pages with PyMuPDF and view them).

## Commands (run from repo root)

| Command | What it does |
|---|---|
| `pnpm setup:all` | One-shot setup: creates `.env` from `.env.example` if empty, `pnpm install`, `uv sync` (fetches Python 3.12), builds/starts the DB container, runs migrations |
| `pnpm ingest all --country AZ,TR,US` | Boundaries + yearly archives 2000..last year + current year via FIRMS API. Resumable/idempotent; rerun to refresh NRT |
| `pnpm ingest archive --country TR --years 2010-2012 --sources modis,snpp` · `pnpm ingest api --country AZ --from 2026-10-01` · `pnpm ingest status` · `pnpm ingest boundaries` | Partial loads / summary. `--force` reloads logged items |
| `pnpm harmonize run --country AZ,TR` · `--steps mask,events,calibrate` · `pnpm harmonize status` | Rebuilds the static mask, events, calibration and HFI (idempotent, ~30 s per country for AZ/TR). Rerun after every ingest |
| `pnpm db:migrate` | Applies new `db/migrations/NNN_*.sql` (tracked in `schema_migrations`) |
| `pnpm dev` | Web on :3000 and API on :8000 together (`concurrently`). The API runs **without** `--reload`: on Windows the reload hangs, exits, and `concurrently -k` then kills the web server too. Use `pnpm --filter api dev:reload` if you want reload, and restart after backend edits. |
| `pnpm db:dump` / `scripts/restore-db.sh` | Yerel veritabanı yedekleme ve geri yükleme. |
| `pnpm update:daily` (`app/update.py`; `--bootstrap` for an empty DB, `--country`, `--optimize`) | Günlük NRT tazeleme + yeniden harmonizasyon. Yerel olarak `pnpm update:daily` ile çalıştırılır. `--optimize` (CLUSTER) ~10 GB ek disk ister; lokalde önerilmez. |
| `pnpm db:optimize` (`app/optimize.py`) | CLUSTERs `fire_detection` by location + ANALYZE; speeds up first computation of large ROIs. Locks the table and needs free disk the size of the table (~10 GB): never run alongside ingest/harmonize, and not on Render's 20 GB disk (so `--bootstrap` no longer runs it) |
| `pnpm test` | vitest (web) + pytest (api) |
| `pnpm lint` | `tsc --noEmit` (web) + `ruff check` (api) |
| `pnpm build` | Next.js production build |
| `pnpm db:up` / `db:down` / `db:reset` / `db:logs` / `db:psql` | Docker DB lifecycle; `db:reset` wipes the volume (all ingested data!), re-runs `db/init/*.sql` and migrations |

Single tests: `cd apps/api && uv run pytest tests/test_parse.py::test_acq_time_padding` · `pnpm --filter web exec vitest run -t "bboxes"`. Tests marked `db` (`tests/test_load_db.py`) hit the real DB inside a rolled-back transaction and skip if it is down.

Requires Docker Desktop running (WSL2) and `uv`. `docker` may not be on PATH in terminals opened before Docker was installed; it lives in `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`.

## Layout and non-obvious wiring

- `apps/web` (Next.js 16, Turbopack, Tailwind v4, MapLibre GL v6) and `apps/api` (FastAPI, psycopg 3 pool, managed by `uv`) are both pnpm workspace packages; the api's `package.json` only wraps `uv run` so `pnpm --filter api ...` works.
- **One `.env` at the repo root** serves everything: docker compose reads it directly, the API loads it via `app/config.py` (`ROOT_ENV`), and `apps/web/next.config.ts` loads it with `@next/env`. Don't add per-app `.env` files.
- DB: `db/Dockerfile` = `postgis/postgis:17-3.6` + `postgresql-17-h3`. Use 3.6 tags (trixie); 17-3.5 is bullseye and PGDG no longer serves bullseye, so the h3 install fails. Host port is **5433**. Extensions are created by `db/init/01-extensions.sql`, which only runs on an empty volume.
- MapLibre v6 has **no default export** (`import * as maplibregl`) and its Web Worker can't be bundled by Turbopack: `apps/web/scripts/copy-maplibre-worker.mjs` (run by `predev`/`prebuild`) copies it to `public/maplibre/` and `FireMap.tsx` calls `setWorkerUrl`. MapLibre is loaded client-only via `next/dynamic` with `ssr: false`.
- Map style is OpenFreeMap (no token), configurable via `NEXT_PUBLIC_MAP_STYLE_URL`.
- i18n is a plain dictionary in `apps/web/src/lib/i18n.ts` (AZ, EN; the default is EN, overridable via `NEXT_PUBLIC_DEFAULT_LOCALE`, see `useLocale.ts`); a test enforces both locales have identical keys. Preset countries (AZ, TR, contiguous US, AR, GR, PT) and their bboxes live in `src/lib/regions.ts`.
- API `/health` never throws: DB failure is reported as `status: "degraded"`; the pool opens lazily so the API starts even when the DB is down.
- Schema changes go in a new `db/migrations/NNN_*.sql` (runner: `apps/api/app/migrate.py`), never in `db/init/`.

## Data ingestion (`apps/api/app/ingest/`)

- **Two FIRMS inputs.** (1) Yearly per-country CSVs `firms.modaps.eosdis.nasa.gov/data/country/{modis|viirs-snpp|viirs-jpss1}/{year}/..._{Azerbaijan|Turkey|United_States}.csv`: no key, no rate limit, SP data, 2000..last year. NOAA-20's directory is `viirs-jpss1`; there is none for NOAA-21. (2) The area API `/api/area/csv/{key}/{SOURCE}/{w,s,e,n}/{1-5 days}/{start}` for the current year: max 5 days per request, `DATE` is the window start. The country API endpoint returns "Invalid API call", so API rows are fetched by bbox (`COUNTRIES[..].api_bboxes`, US split at the antimeridian) and clipped to the `country_boundary` polygon (Natural Earth 10m) in SQL.
- `sources.plan_windows` uses `/api/data_availability` to fetch SP up to its max date and NRT after it. When an SP window lands, the NRT rows of those days are deleted (`delete_nrt`), so a fire is never counted twice. SP windows are logged once; NRT windows are refetched every run.
- `fire_detection` holds raw detections in one schema for both sensors, with natural key `(source, acq_ts, lat, lon)` and `ON CONFLICT DO NOTHING`. `confidence_level` is normalized to 0/1/2 (MODIS <30 / <80 / ≥80; VIIRS l/n/h) and `confidence_raw` keeps the original. `fire_type` 2 = static industrial source (gas flares); NRT has no `type` column, so it is NULL there. `h3_r8` is precomputed; get coarser cells with `h3_cell_to_parent`. Use `h3_latlng_to_cell`, not the deprecated `h3_lat_lng_to_cell`.
- Loading is CSV → `normalize()` (header-name based; NRT `acq_time` lacks zero padding) → `COPY` into a temp `stage_fire` → `INSERT ... SELECT` that computes geom/h3. Each file or API window is one transaction (the CLI connection is autocommit) and is recorded in `ingest_log` (`key` = `archive:SRC:CC:YEAR` / `api:FIRMS_SOURCE:CC:start:days`).
- Raw downloads are cached in `data/raw/` (gitignored); re-runs do not re-download.
- Only one ingest runs at a time: a Postgres advisory lock (`INGEST_LOCK_ID`), and the second run exits with code 3. `status` skips the lock. Two runs at once used to crash on Windows when both renamed the same `.part` file; temp files are now per-PID.
- PowerShell turns `--country AZ,TR,US` into `"AZ TR US"`, so list arguments split on commas and whitespace.
- `/detections` caps the range at 31 days and the result at 20k points (strongest FRP first). By default it hides `fire_type=2` and confidence 0.

## Harmonization (`apps/api/app/harmonize/`, parameters in `settings.py`)

The HFI (Harmonized Fire Index) is MODIS-equivalent. hfi-v2 calibrates **two targets**: `det`, the hotspot count (the default UI metric, stored as `harmonized_daily.hfi_det`), and `evt`, the event-days (`hfi`). FRP is a ratio model only. Pipeline: `mask.py` → `events.py` → `calibrate.py` → `apply.py`. Everything is derived from `fire_detection` and fully rebuilt on each run. Bump `HFI_VERSION` when the method changes.
1. **Static mask** (`static_mask`, r8): NASA `type=2` cells, plus cells with detections on ≥100 days in ≥5 years, dilated by one H3 ring. It is needed because NRT has no `type`, and type=2 is ~25% of VIIRS points in TR versus ~3% for MODIS.
2. **Cleaning**: confidence ≥ nominal, `coalesce(fire_type,0)=0`, not masked.
3. **Events**: ST-DBSCAN with `min_samples=1` reduces to connected components within 1.5 km / 1 day. It uses BallTree haversine and runs in yearly chunks with an `EPS_DAYS` carry-over plus union-find. Clustering is per source (MODIS = Terra+Aqua). The daily metric is `n_evt`, distinct events per r5 cell-day. Note: clustering did **not** close the sensor gap; VIIRS/MODIS is still ~2.6–2.9× at event level, because VIIRS sees whole small fires MODIS misses. Calibration does the real work.
4. **Series** (`build_series`): VIIRS = **mean** of SNPP, NOAA-20 and NOAA-21 (`VIIRS_SOURCES` in `settings.py`) over satellites that delivered data that day. Coverage is per country: the source has a loaded `ingest_log` item for that country and ≥1 raw detection that day, which separates "no fire" from an outage. Summing them would create a false jump in 2018. MODIS before 2002-07-04 (Terra only) is scaled by the per-country (Terra+Aqua)/Terra ratio from 2003–2007.
5. **Calibration**: country-day target = MODIS event-days. Candidates: `viirs_raw` (baseline, not selectable), `ratio` (month × ±2-year rolling window with shrinkage to the window ratio, which captures MODIS orbit drift), `loglinear`, `random_forest`. Each is scored with leave-one-year-out; the winner has the lowest mean |annual bias|, ties broken by daily r. The season metric is the mean shift of the 10/50/90% cumulative-fire dates, not the argmax, because TR/AZ have bimodal seasons. Results (hfi-v1): TR → ratio (3.96% bias, weekly r 0.97, 6.4 days); AZ → random_forest (8.0%, daily r 0.83); US → random_forest (2.8%, daily r 0.95, 3.5 days). A full `run --country AZ,TR,US` takes ~7 min, ~5 of them US event clustering.
6. **Apply** (`apply.py`): the per-target predictions become **country × day factors** in `harmonized_factor`. On VIIRS days, factor = prediction ÷ country VIIRS satellite-mean. On MODIS days, factor = Terra scale or 1. The factors are multiplied with H3 cell values (`harmonized_daily`) and with ROI values (`areas.harmonize_roi`), so an area's total equals the sum of its parts. NRT-derived rows are `provisional`. The events step also writes `detection_event(detection_id, event_no)` for the cleaned detections, so ROI queries can count event-days, and "has a detection_event row" == "used in harmonization". A harmonize run sets every ROI of that country back to `pending`, so ROIs are recomputed on the next view. Results (hfi-v2, hotspot target): US rf 2.1 %, AR rf 3.2 %, TR ratio 4.4 %, AZ rf 7.9 % mean |annual bias|. A full 4-country run takes ~10 min.
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
- Page state lives in the URL (`?area=roi:abc&year=2021&metric=frp&compare=2024&from=&to=`; map: `?region|area&date&range&layer=density&draw=1`), via `lib/url.ts`, not `useSearchParams`. The map draws polygons with **terra-draw** (`FireMap` `drawing` prop). Finishing a polygon calls POST /roi and redirects to `/?area=roi:…`.
- Ramps live in `lib/calendar.ts` (`RAMPS.fire`, `RAMPS.cividis`, `ANOMALY_COLORS`); the choice is saved in localStorage (`useRamp`). Azerbaijani month and day names are hard-coded, because Chromium Intl has no `az` data.
- Dev gotchas: stopped previews can leave an orphaned uvicorn on :8000, which serves stale code and 404s new routes. Check it with `Get-NetTCPConnection -LocalPort 8000`. The hidden Claude browser pane does not paint scrolled canvases in screenshots; check charts via DOM or canvas pixels instead.

## Project goal (from plan.pdf)

AstraForce is a web app for **harmonizing NASA MODIS and VIIRS active-fire data** into one consistent 20+ year record (2000 to today), and showing it as a "fire calendar" for any region the user picks.

The core problem is that raw fire-point counts from the two sensors cannot be compared directly:
- **Spatial resolution:** MODIS pixels are about 1 km; VIIRS I-band pixels are 375 m. VIIRS detects many more small fires, and one fire can show up as about 10 VIIRS pixels against 1 MODIS pixel.
- **Temporal coverage:** MODIS runs from 2000 (Terra) and 2002 (Aqua). VIIRS runs from 2012 (Suomi-NPP), and later on NOAA-20 and NOAA-21. Naively joining the two creates a false upward trend after 2012.
- **Overpass times and viewing angles** differ between the satellites.

## Harmonization method (planned)

1. **Spatial binning:** aggregate points into a fixed grid (0.1°/0.25°) or Uber H3 hexagons. Compute burned-area index or total FRP (Fire Radiative Power) per cell instead of raw point counts.
2. **Overlap calibration:** for 2012 onward, both sensors exist. Fit a regression (linear or Random Forest) of VIIRS against MODIS to get scaling factors, so that both map to one Harmonized Fire Index.
3. **ST-DBSCAN:** spatio-temporal clustering that merges nearby pixels into single "fire events", which removes the multi-pixel bias.
4. **Deduplication:** VIIRS and MODIS detections that fall at the same time and place are treated as duplicates.
5. **Confidence filtering:** remove false positives (industrial heat, gas flares, reflections) using MODIS confidence (0–100%) and VIIRS confidence (low/nominal/high). Picking the cutoff thresholds is still being researched.

## Data sources

- NASA FIRMS, MODIS: Terra/Aqua, products MCD14DL / MOD14 / MYD14
- NASA FIRMS, VIIRS: Suomi-NPP / NOAA-20 / NOAA-21, products VNP14IMGTDL / VJ114IMGTDL
- MCD12Q1 Land Cover Type: an auxiliary layer for spread dynamics by landscape type
- Ingestion: see "Data ingestion" above. The FIRMS API needs `FIRMS_MAP_KEY` in `.env` (5000 transactions / 10 min).

## Architecture

```
NASA FIRMS API / CSV archives
  -> apps/api: FastAPI + PostGIS/H3 (+ GeoPandas, scikit-learn planned)
       bounding-box/polygon filtering, harmonization (regression, hex binning),
       historical stats (seasonality, peak days)
  -> apps/web: Next.js + Tailwind + MapLibre GL + ECharts (calendar heatmap, charts)
```

Decided: PostGIS (not DuckDB), MapLibre (not Mapbox/Leaflet), UI languages AZ + EN.

## Planned user flow

1. **ROI selection:** a global map with search (country/region/city), a polygon drawing tool, and GeoJSON/KML upload. The backend validates the geometry and runs it as a spatial query.
2. **Filters:** a 20+ year time slider, a monthly/yearly toggle, and a confidence filter (nominal, high).
3. **Processing:** show a progress indicator. The backend deduplicates, calibrates and computes daily intensity and burned-area projection.
4. **Fire calendar and analytics:**
   - A GitHub-contribution-style 365-day heatmap, colored from light yellow to dark red. Hovering a day shows a tooltip with fire count and FRP.
   - A seasonality chart: when the season starts, peaks and ends, plus a 20-year trend curve.
   - A spatial density heatmap layer.
   - A year-over-year comparison chart.
   - Results are rendered as SVG charts and GeoJSON/vector-tile map layers.
5. **Export:** CSV, GeoJSON or a PDF summary.
