# AstraForce — Harmonized MODIS + VIIRS Burning Activity Calendar

**NASA Space Apps Challenge 2026 · "Harmonization of MODIS and VIIRS Hot Spots"**

AstraForce turns 25 years of NASA FIRMS active-fire hotspots from two sensor families into **one consistent time series**. With that series, *the sensor of origin no longer matters*. The app then serves the series as an interactive **burning activity calendar** for any area a user draws, types in, or uploads.

> MODIS (Terra/Aqua, 1 km, since 2000) is nearing end of life. VIIRS (Suomi-NPP, NOAA-20, NOAA-21, 375 m, since 2012) sees roughly 3× more hotspots for the same fires. Joining the two records naively creates a false upward trend after 2012. AstraForce calibrates VIIRS to the MODIS scale, so the 2000–today record is comparable.

## What it does

| Challenge objective | AstraForce |
|---|---|
| Harmonize MODIS and VIIRS hotspots | Static-source masking, satellite-aware VIIRS averaging, ST-DBSCAN fire events, and a **calibration selected by leave-one-year-out validation** (see below) |
| Burning activity calendar, early 2000s → present | GitHub-style daily calendar (2000-11 → today, including near-real-time data) **and** a 25-year **month × year** calendar |
| Select a region and a date range | 6 preset countries, **draw a polygon on the map**, **search a place name** or **enter lat/lon + radius**, or **upload GeoJSON / KML**; free date range |
| Compare current activity with the historical median | "Current situation" card: month-to-date and last 7 days vs. the **2001–2025 median**, plus anomaly classes; per-month anomalies in the matrix |
| Which months / years had the most fire? | Month × year matrix (values or anomaly view), yearly ranking, Theil–Sen trend with Mann–Kendall test |
| Accessible color ramps | Monotonic-lightness fire ramp, a **colorblind-safe (cividis)** option, and a diverging blue–red ramp for anomalies; all with numeric legends |
| Download analytics, visualizations, hotspot CSV | **Raw hotspots CSV** for any area and date range, daily harmonized series CSV, month × year CSV, PNG for every chart, printable report |
| Early warning: up-to-date data | A **daily job** pulls the newest FIRMS data (near-real-time) and re-harmonizes; the header shows the latest data day |
| Context for land managers | **Land cover overlay** (NASA GIBS, MODIS MCD12Q1 IGBP, 2001–2024) under the fire layers; an in-app **Method** page with live validation numbers; works on phones |

Three metrics are available. **Hotspots** (harmonized hotspot count, MODIS-equivalent) is the default. **Fire events** counts neighbouring pixels as one fire. **Fire power** is FRP in MW. They answer different questions. In Türkiye in 2021, hotspot and FRP counts peak during the Manavgat forest fires (28 July). Event counts instead peak during the November stubble burning in the south-east.

## Harmonization method

1. **Data.** We use NASA FIRMS yearly country archives (standard processing) for 2000 → last year, and the FIRMS area API (SP, then NRT) for the current year. Sources are MODIS C6.1 (Terra + Aqua), VIIRS S-NPP, NOAA-20 and NOAA-21 (API only, since 2023). The database covers Azerbaijan, Türkiye, the United States, Argentina, Greece and Portugal, about 24 M detections. NOAA-21 history is loaded for Greece and Portugal; for the other countries the daily job adds it from the current year on, and coverage is tracked per country, so missing NOAA-21 history never biases the VIIRS mean.
2. **Cleaning.** We keep detections with confidence ≥ nominal. We remove static thermal sources (gas flares, industry): cells NASA flags `type=2`, plus cells that are hot on more than 100 days across 5 or more years. The mask is dilated by one H3 ring. This matters because in Türkiye about 25 % of VIIRS hotspots are static sources, versus about 3 % for MODIS.
3. **Satellites.** The VIIRS value of a day is the *mean* of the VIIRS satellites that delivered data that day; summing them would create a false jump in 2018. MODIS before Aqua (2000-11 → 2002-07) is scaled by the regional (Terra+Aqua)/Terra ratio.
4. **Fire events.** ST-DBSCAN (1.5 km, 1 day) merges multi-pixel detections into fire events.
5. **Calibration.** On the 2012–2025 overlap we fit four candidate models per country and per target: no calibration, a monthly ratio over a rolling ±2-year window (this tracks the MODIS orbit drift), log-linear regression, and Random Forest. Each is scored with **leave-one-year-out** validation, and the lowest mean |annual bias| wins.
6. **Application.** Each country × day gets a factor (harmonized value ÷ VIIRS value). The same factors are applied to H3 cells and to any user-drawn area, so an area's total always equals the sum of its parts.

### Validation (leave-one-year-out, harmonized hotspot count)

| Country | Selected model | Mean \|annual bias\| | Daily r | Weekly r | Season timing shift | Uncalibrated VIIRS bias |
|---|---|---|---|---|---|---|
| Argentina | Random Forest | **3.2 %** | 0.94 | 0.99 | 2.2 days | 226 % |
| United States | Random Forest | **2.1 %** | 0.95 | 0.99 | 2.0 days | 250 % |
| Türkiye | Monthly ratio | **4.4 %** | 0.89 | 0.97 | 3.7 days | 217 % |
| Azerbaijan | Random Forest | **7.9 %** | 0.85 | 0.95 | 5.7 days | 281 % |
| Portugal | Random Forest | **6.6 %** | 0.89 | 0.96 | 3.2 days | 171 % |
| Greece | Monthly ratio | **8.5 %** | 0.83 | 0.96 | 3.4 days | 241 % |

The season timing shift is the mean difference of the dates when 10 / 50 / 90 % of the yearly fire activity is reached. Known events reproduce. Manavgat 2021: a 30 km radius ranks 2021 first of 25 years and puts the season start on 28 July. United States 2020: the top FRP year, with the peak week starting 5 September.

## Run locally

Requirements: Node 20+, pnpm 10, [uv](https://docs.astral.sh/uv/) and Docker Desktop.

```bash
pnpm setup:all                              # deps, Python 3.12, PostGIS+H3 container, migrations
# put your free NASA FIRMS key in .env → FIRMS_MAP_KEY=...
pnpm ingest all --country AZ,TR,US,AR       # ~1 h the first time (resumable, idempotent)
pnpm harmonize run --country AZ,TR,US,AR    # ~10 min
pnpm dev                                    # http://localhost:3000 (API on :8000/docs)
```

Run `pnpm test` (pytest and vitest) and `pnpm lint`. `pnpm update:daily` refreshes the near-real-time data and re-harmonizes; it is the same job the server runs every day. `pnpm db:optimize` physically orders hotspots by location, which makes large drawn areas much faster; it needs free disk space about the size of the `fire_detection` table (~10 GB), so it is not part of `--bootstrap` (add `--optimize` if the disk allows).

## Yerel Çalıştırma (Local-Only)

AstraForce şu an sadece yerel geliştirme için yapılandırılmıştır. Render dağıtımı (`render.yaml`, `docker-compose.prod.yml`, Caddy) kaldırılmıştır.

```bash
# 1. Veritabanını başlat (PostGIS 17 + H3, port 5433)
pnpm db:up

# 2. Migrasyonları uygula
pnpm db:migrate

# 3. Veriyi yükle (ilk sefer, ~1 sa; durable/idempotent)
pnpm ingest all --country AZ,TR,US,AR,GR,PT

# 4. Harmonizasyonu çalıştır (maske, olaylar, kalibrasyon)
pnpm harmonize run --country AZ,TR,US,AR,GR,PT

# 5. Uygulamayı başlat (web:3000, api:8000)
pnpm dev
```

### Demo / Senteşik Veri (FIRMS anahtarı olmadan)

`scripts/synthetic_generate.py` kullanarak Azerbaycan için gerçekçi senteşik FIRMS verisi üretebilir ve boru hattını test edebilirsiniz:

```bash
python scripts/synthetic_generate.py
# ardından ingest + harmonize akışını normal şekilde çalıştırın
```

Senteşik veri, mevcut FIRMS CSV başlıklarını ve sensör fiziklerini taklit eder; `FIRMS_MAP_KEY` gerektirmez.

## Stack

PostgreSQL 17 + PostGIS 3.6 + H3 · FastAPI, pandas, scikit-learn · Next.js 16, Tailwind, MapLibre GL, terra-draw, ECharts, togeojson · OpenFreeMap tiles, NASA GIBS land cover, Photon (OpenStreetMap) place search.

## Data & attribution

Active fire data: **NASA FIRMS** (MODIS Collection 6.1 MCD14; VIIRS 375 m VNP14IMG / VJ114IMG / VJ214IMG), NRT and standard products. Land cover: **NASA GIBS**, MODIS MCD12Q1 (IGBP). Country boundaries: Natural Earth (public domain). Base map © OpenFreeMap, © OpenStreetMap contributors. Place search: Photon by Komoot (OpenStreetMap data).

## Limitations

- Areas must fall inside the loaded countries (AZ, TR, US, AR, GR, PT). Any other country can be added with one `ingest` + `harmonize` command, after adding it to `COUNTRIES` in `apps/api/app/ingest/sources.py` and `REGIONS` in `apps/web/src/lib/regions.ts`.
- The land cover overlay is visual only; per-fire land cover statistics are not computed.
- Near-real-time days are provisional. They are marked on the calendar and replaced by standard-processing data when NASA publishes it.
- Calibration is per country. Small areas inherit their country's daily factors.

## Dokümantasyon

- `docs/METHODS.md` — bilimsel harmonizasyon yöntemi (MODIS/VIIRS sensör ayrımı, H3 hücre-gün, yerel gün içi tarih, statik maske, kalibrasyon modeli)
- `docs/LIMITATIONS.md` — bilimsel sınırlamalar ve varsayımlar (bulut kapaması, gece/gece geçişi, erken MODIS dönemi, burned area vs cell-day)
- `config.yaml` — işletimsel yapılandırma (H3 çözünürlüğü, tarih eşikleri, güven seviyeleri, model parametreleri)
