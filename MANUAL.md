# AstraForce Manual / İstifadəçi Qaydası

English | [Azərbaycan dili](#azerbaijani-dili)

---

## English

### 1. What is AstraForce?

AstraForce is a web application that harmonizes 25 years of NASA MODIS (1 km, 2000–present) and VIIRS (375 m, 2012–present) active-fire hotspot data into one consistent daily record. It provides an interactive burning-activity calendar, anomaly detection, trend analysis, and CSV/PNG exports for any selected region.

### 2. Prerequisites

Before you begin, install the following:

- **Node.js 20+** — https://nodejs.org/
- **pnpm 10** — `npm install -g pnpm@10`
- **uv** (Python package manager) — https://docs.astral.sh/uv/
- **Docker Desktop** — https://www.docker.com/products/docker-desktop/ (must be running)
- **NASA FIRMS API Key** (optional for historical data, required for near-real-time) — https://firms.modaps.eosdis.nasa.gov/api/map_key/

### 3. Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/mmisovcahid-cmyk/AstraForce.git
cd AstraForce

# 2. Copy environment file
cp .env.example .env
# Edit .env and add your FIRMS_MAP_KEY if you want near-real-time data

# 3. Start everything with Docker Compose
docker compose up -d --build

# 4. Load data (first time takes ~1 hour)
pnpm ingest all --country AZ,TR,US,AR,GR,PT

# 5. Run harmonization
pnpm harmonize run --country AZ,TR,US,AR,GR,PT

# 6. Open the application
# Web: http://localhost:3000
# API docs: http://localhost:8000/docs
```

### 4. Commands Reference

| Command | Description |
|---------|-------------|
| `docker compose up -d --build` | Start database, API, and web |
| `docker compose down` | Stop all services |
| `pnpm setup:all` | Full local setup (Node, Python, DB, migrations) |
| `pnpm ingest all --country AZ,TR,US,AR,GR,PT` | Load NASA FIRMS data |
| `pnpm harmonize run --country AZ,TR,US,AR,GR,PT` | Harmonize MODIS + VIIRS data |
| `pnpm dev` | Run web (:3000) + API (:8000) locally without Docker |
| `pnpm test` | Run all tests (vitest + pytest) |
| `pnpm lint` | Run TypeScript + ruff checks |
| `pnpm add-country --code XX --name "Name" --archive-name "Archive" --bbox "w,s,e,n"` | Add a new country |

### 5. Using the Application

- **Home**: Interactive GitHub-style fire calendar (2000–present)
- **Map**: Draw polygons, search places, or enter lat/lon + radius
- **Matrix**: Month × year view with anomaly vs. historical median
- **Season**: Yearly totals, ranking, and trend analysis
- **Status**: Current month vs. median, last 7 days
- **Exports**: Hotspots CSV, daily CSV, matrix CSV, PNG charts, print report
- **Settings**: Color ramps (fire, cividis, anomaly), language (AZ/EN)

### 6. Supported Countries

AZ (Azerbaijan), TR (Türkiye), US (United States), AR (Argentina), GR (Greece), PT (Portugal)

### 7. Troubleshooting

| Problem | Solution |
|---------|----------|
| Docker not running | Start Docker Desktop, wait for "Engine running" |
| `.env` missing | Copy `.env.example` to `.env` and fill in values |
| `FIRMS_MAP_KEY` empty | Historical data works without it; NRT data needs a key |
| Port 5433/3000/8000 in use | Stop conflicting services or change ports in `.env` / `docker-compose.yml` |
| Data loading slow | First load is ~1 hour; subsequent runs are incremental |

---

## Azərbaycan dili

### 1. AstraForce Nədir?

AstraForce, NASA MODIS (1 km, 2000–indi) və VIIRS (375 m, 2012–indi) aktiv yangın bloßü tarixlərinin 25 illik tarixini süxi hatda birləşdirən bir veb tətbiqdir. Hansı bir seçilmiş bölgə üçün interaktiv yangın faaliyyət takvimi, anomalya tapılması, trend analizi və CSV/PNG icra mənbüsü təmin edir.

### 2. Təcbih Edilən Təbcələr

Başlamadan əvvəl aşağıdakılar yüklü olmalıdır:

- **Node.js 20+** — https://nodejs.org/
- **pnpm 10** — `npm install -g pnpm@10`
- **uv** (Python paket menecceri) — https://docs.astral.sh/uv/
- **Docker Desktop** — https://www.docker.com/products/docker-desktop/ (işləyib olmalıdır)
- **NASA FIRMS API açarı** (tarixli məlumatlar üçün lazım deyil, qısa müddətli gerçək vaxt üçün tələb olunur) — https://firms.modaps.eosdis.nasa.gov/api/map_key/

### 3. Təzi Başlanğıc

```bash
# 1. Depoyu klonlayın
git clone https://github.com/mmisovcahid-cmyk/AstraForce.git
cd AstraForce

# 2. Mühit faylını kopyalayın
cp .env.example .env
# .env faylını açın və FIRMS_MAP_KEY əlavə edin (qısa müddətli gerçək vaxt məlumatları üçün)

# 3. Docker Compose ilə başlayın
docker compose up -d --build

# 4. Məlumatları yükləyin (ilk dəfə ~1 saat sürər)
pnpm ingest all --country AZ,TR,US,AR,GR,PT

# 5. Həmrəstdəştirməni işə salın
pnpm harmonize run --country AZ,TR,US,AR,GR,PT

# 6. Tətbiqi açın
# Web: http://localhost:3000
# API sənədləri: http://localhost:8000/docs
```

### 4. Ərəzlər Cədvəli

| Ərəz | Təsvir |
|------|---------|
| `docker compose up -d --build` | Veritabanı, API və veb tətbiqi başlayın |
| `docker compose down` | Bütün xidmətdən dayanın |
| `pnpm setup:all` | Tam yerli quraşdırma (Node, Python, DB, köçürmələr) |
| `pnpm ingest all --country AZ,TR,US,AR,GR,PT` | NASA FIRMS məlumatlarını yükləyin |
| `pnpm harmonize run --country AZ,TR,US,AR,GR,PT` | MODIS + VIIRS məlumatlarını həmsenkəsləyin |
| `pnpm dev` | Web (:3000) + API (:8000)'i Dockerdan孝pa yerli işə salın |
| `pnpm test` | Bütün testləri işə salın (vitest + pytest) |
| `pnpm lint` | TypeScript + ruff yoxlamalarını işə salın |
| `pnpm add-country --code XX --name "Ad" --archive-name "Arşiv" --bbox "w,s,e,n"` | Yeni əlavə edin |

### 5. Tətbiqdən Faydalanın

- **Əsas səhifə**: Interaktiv yangın faaliyyət takvimi (2000–indi)
- **Xəritə**: Çoxbucaqlı çəkin, yer axtarın və ya enlem/boylam + radius daxil edin
- **Matrix**: Ay × il görünüşü, tarixi orta ilə anomalya
- **Mövsüm**: İllik cəmlər, sıralama və trend analizi
- **Hər halda**: Cari ay və orta, son 7 gün
- **İcra nümunələri**: Blöx CSV, günlük CSV, matrix CSV, PNG QR-serələri, çap edə bilərən hesabat
- **Ayarlar**: Rang xanaları (yangın, cividis, anomalya), dil (AZ/EN)

### 6. Təmkin Edilən Ülkələr

AZ (Azərbaycan), TR (Türkiye), US (Amerika Birləşmiş Ştatları), AR (Argentin), GR (Yunanıstan), PT (Portuqaliya)

### 7. Problemlərin Həll Edilməsi

| Problema | Həll |
|----------|------|
| Docker işləmir | Docker Desktop'u açın, "Engine running" olmasını gözləyin |
| `.env` yoxdur | `.env.example`'ı `.env`'ye kopyalayın və dəyərləri doldurun |
| `FIRMS_MAP_KEY` boşdur | Tarixli məlumatlar onun olmadan işləyir; NRT məlumat açarı tələb edir |
| Port 5433/3000/8000الدə var | Başqa xidməti dayanın və ya portları `.env` / `docker-compose.yml`-də dəyişin |
| Məlumat yüklemesi yavaşdır | İlk yükleme ~1 saat sürər; sonraki dəfələr inkrementaldır |

---

## Project Submission Info (NASA Space Apps 2026)

- **Repo**: https://github.com/mmisovcahid-cmyk/AstraForce
- **Demo**: Public Google Slides link (≤7 slides / ≤30 seconds video)
- **NASA Data Used**: FIRMS MODIS C6.1, FIRMS VIIRS 375 m, GIBS Land Cover MCD12Q1, NASA Earthdata
- **Other Data**: Natural Earth, OpenFreeMap, OpenStreetMap/Photon, Uber H3

---

*Manual prepared for NASA Space Apps Challenge 2026 submission.*