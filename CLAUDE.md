# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Always answer the user fully in Turkish. Do not write code until the user says START; plan and analyze first when asked to.

## Status

Done: phase 1 (skeleton: monorepo, PostGIS + H3, FastAPI, Next.js map, AZ/EN), phase 2 (FIRMS ingestion for AZ/TR/US, MODIS + VIIRS SNPP + NOAA-20, `/data/status`, `/detections`, raw-points map layer with date/range picker) phase 3 (harmonization → HFI, `/harmonized/*`, `/validation` page) and phase 4 (fire calendar as the home page `/`: GitHub-style heatmap, KPIs, seasonality, trend, monthly comparison, `/analytics/*`; map moved to `/map`, which got a density layer). Next: ROI selection (draw a polygon, upload GeoJSON/KML) → export (CSV/GeoJSON/PDF). NOAA-21 is not ingested (no yearly country files; API only).

`plan.pdf` is the original design doc (Azerbaijani, **image-only**: `pdftotext` returns nothing; render pages with PyMuPDF and view them).

## Commands (run from repo root)

| Command | What it does |
|---|---|
| `pnpm setup:all` | One-shot setup: creates `.env` from `.env.example` if empty, `pnpm install`, `uv sync` (fetches Python 3.12), builds/starts the DB container, runs migrations |
| `pnpm ingest all --country AZ,TR,US` | Boundaries + yearly archives 2000..last year + current year via FIRMS API. Resumable/idempotent; rerun to refresh NRT |
| `pnpm ingest archive --country TR --years 2010-2012 --sources modis,snpp` · `pnpm ingest api --country AZ --from 2026-10-01` · `pnpm ingest status` · `pnpm ingest boundaries` | Partial loads / summary. `--force` reloads logged items |
| `pnpm harmonize run --country AZ,TR` · `--steps mask,events,calibrate` · `pnpm harmonize status` | Rebuilds the static mask, events, calibration and HFI (idempotent, ~30 s per country for AZ/TR). Rerun after every ingest |
| `pnpm db:migrate` | Applies new `db/migrations/NNN_*.sql` (tracked in `schema_migrations`) |
| `pnpm dev` | Web on :3000 and API on :8000 together (`concurrently`) |
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
- i18n is a plain dictionary in `apps/web/src/lib/i18n.ts` (AZ default, EN); a test enforces both locales have identical keys. Test regions (TR, AZ, contiguous US) and their bboxes live in `src/lib/regions.ts`.
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

The HFI (Harmonized Fire Index) is in **MODIS-equivalent event-days**. Pipeline: `mask.py` → `events.py` → `calibrate.py` → `apply.py`. Everything is derived from `fire_detection` and fully rebuilt on each run. Bump `HFI_VERSION` when the method changes.
1. **Static mask** (`static_mask`, r8): NASA `type=2` cells, plus cells with detections on ≥100 days in ≥5 years, dilated by one H3 ring. It is needed because NRT has no `type`, and type=2 is ~25% of VIIRS points in TR versus ~3% for MODIS.
2. **Cleaning**: confidence ≥ nominal, `coalesce(fire_type,0)=0`, not masked.
3. **Events**: ST-DBSCAN with `min_samples=1` reduces to connected components within 1.5 km / 1 day. It uses BallTree haversine and runs in yearly chunks with an `EPS_DAYS` carry-over plus union-find. Clustering is per source (MODIS = Terra+Aqua). The daily metric is `n_evt`, distinct events per r5 cell-day. Note: clustering did **not** close the sensor gap; VIIRS/MODIS is still ~2.6–2.9× at event level, because VIIRS sees whole small fires MODIS misses. Calibration does the real work.
4. **Series** (`build_series`): VIIRS = **mean** of SNPP and NOAA-20 over satellites that delivered data that day. Coverage = the source has ≥1 raw detection anywhere in the DB that day, which separates "no fire" from an outage. Summing them would create a false jump in 2018. MODIS before 2002-07-04 (Terra only) is scaled by the per-country (Terra+Aqua)/Terra ratio from 2003–2007.
5. **Calibration**: country-day target = MODIS event-days. Candidates: `viirs_raw` (baseline, not selectable), `ratio` (month × ±2-year rolling window with shrinkage to the window ratio, which captures MODIS orbit drift), `loglinear`, `random_forest`. Each is scored with leave-one-year-out; the winner has the lowest mean |annual bias|, ties broken by daily r. The season metric is the mean shift of the 10/50/90% cumulative-fire dates, not the argmax, because TR/AZ have bimodal seasons. Results (hfi-v1): TR → ratio (3.96% bias, weekly r 0.97, 6.4 days); AZ → random_forest (8.0%, daily r 0.83); US → random_forest (2.8%, daily r 0.95, 3.5 days). A full `run --country AZ,TR,US` takes ~7 min, ~5 of them US event clustering.
6. **Apply**: the predicted country-day HFI is split over r5 cells by each cell's VIIRS share. Pre-2012 days, and days with no VIIRS, use MODIS cell values. `hfi_frp` (secondary) always uses the FRP ratio model. NRT-derived rows are `provisional`.
- The yearly HFI in `harmonized_validation` for 2012+ comes from the final model fitted on all years (in-sample). The honest numbers are the leave-one-year-out `calibration_model.metrics`.
- Never compare raw MODIS and VIIRS counts directly; always go through `harmonized_daily`.

## Calendar and analytics (`apps/api/app/analytics.py`, `routes/analytics.py`, `apps/web/src/components/CalendarView.tsx`)

- **Two metrics, and they disagree on purpose.** `hfi` (event count) highlights many small fires; in TR its top 2021 days are November stubble burning. `frp` (fire power) highlights a few big fires; there TR 2021 ranks 3rd of 25 and its peak week starts 28 Jul (Manavgat). Every analytics endpoint takes `metric=hfi|frp`.
- **Colour levels** 0..4 are region-relative: 0 = no fire, then ≤p50 / ≤p80 / ≤p95 / >p95 of that region's fire days in 2001..last full year. They live in `hfi_scale` (`thresholds`, `frp_thresholds`), are recomputed at the end of every `harmonize` calibrate step (`compute_scale`), and `levels()` uses `searchsorted(side="left")`.
- `/analytics/calendar?year=` or `?mode=mean` (mean per MM-DD, shown on the 2024 leap calendar) · `/analytics/season` (10/50/90% dates, peak 7-day window, rank, climatology mean and p10–p90 of 7-day means, Theil–Sen + Kendall trend over complete years only) · `/analytics/monthly?years=` · `/analytics/cells` (H3 r5 GeoJSON, ≤366 days).
- Page state lives in the URL (`?region=TR&year=2021&metric=frp&compare=2024`; map: `?region&date&range&layer=density`) via `lib/url.ts`, not `useSearchParams`, so no Suspense is needed. Clicking a calendar day opens `/map?...&date=…&range=1`.
- **Azerbaijani month and day names are hard-coded** in `lib/calendar.ts`, because Chromium's Intl has no `az` data and falls back to "M01"/"Mon". `formatNumber` for `az` uses the ru-RU format (space thousands separator, comma decimals).
- Charts go through `components/EChart.tsx`, which lazy-loads echarts and uses ResizeObserver. `useLocale().t` is memoized, so chart options built with `useMemo` only rebuild when the language changes.
- Dev gotcha: `uvicorn --reload` on Windows sometimes hangs on "Reloading..." and keeps serving the old code, and stopped previews can leave an orphaned uvicorn worker on :8000 (stale code, 404s on new routes). After changing API routes, restart `pnpm dev`, and check the port owner with `Get-NetTCPConnection -LocalPort 8000` if a route 404s.

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

Decided: PostGIS (not DuckDB), MapLibre (not Mapbox/Leaflet), UI languages AZ + EN, test regions Türkiye / Azerbaijan / USA. Git is not set up yet.

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
