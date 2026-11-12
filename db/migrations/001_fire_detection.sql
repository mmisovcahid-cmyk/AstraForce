-- Ham aktif yangın tespitleri (MODIS + VIIRS), iki sensör için ortak format.
-- Harmonizasyon bu tablodan türetilir; ham veri olduğu gibi saklanır.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS h3;
CREATE EXTENSION IF NOT EXISTS h3_postgis CASCADE;

CREATE TABLE fire_detection (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- MODIS | VIIRS_SNPP | VIIRS_NOAA20 | VIIRS_NOAA21
    source           text        NOT NULL,
    -- SP: kesinleşmiş arşiv, NRT: yakın-gerçek-zamanlı (SP gelince silinir)
    product          text        NOT NULL CHECK (product IN ('SP', 'NRT')),
    country          char(2)     NOT NULL,
    acq_ts           timestamptz NOT NULL,
    acq_date         date        NOT NULL,
    lat              double precision NOT NULL,
    lon              double precision NOT NULL,
    geom             geometry(Point, 4326) NOT NULL,
    h3_r8            h3index     NOT NULL,
    -- MODIS: brightness / bright_t31, VIIRS: bright_ti4 / bright_ti5 (Kelvin)
    bright_main      real,
    bright_aux       real,
    scan             real,
    track            real,
    frp              real,
    -- Orijinal güven değeri (MODIS 0-100, VIIRS l/n/h) ve normalize düzey
    confidence_raw   text,
    -- 0 = low, 1 = nominal, 2 = high
    confidence_level smallint    NOT NULL CHECK (confidence_level BETWEEN 0 AND 2),
    daynight         char(1),
    -- 0 bitki örtüsü, 1 volkan, 2 sabit kaynak (endüstri/gaz meşalesi), 3 deniz; NRT'de olmayabilir
    fire_type        smallint,
    satellite        text,
    version          text,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fire_detection_natural_key UNIQUE (source, acq_ts, lat, lon)
);

CREATE INDEX fire_detection_country_source_date ON fire_detection (country, source, acq_date);
CREATE INDEX fire_detection_acq_ts_brin ON fire_detection USING brin (acq_ts);
CREATE INDEX fire_detection_geom ON fire_detection USING gist (geom);
CREATE INDEX fire_detection_h3_r8 ON fire_detection (h3_r8);

-- Hangi dosya / API penceresi yüklendi; yarıda kalan yüklemeler buradan devam eder.
CREATE TABLE ingest_log (
    key            text PRIMARY KEY,
    kind           text        NOT NULL CHECK (kind IN ('archive', 'api', 'boundaries')),
    source         text,
    product        text,
    country        char(2),
    period_start   date,
    period_end     date,
    status         text        NOT NULL CHECK (status IN ('ok', 'missing', 'error')),
    rows_read      integer     NOT NULL DEFAULT 0,
    rows_inserted  integer     NOT NULL DEFAULT 0,
    error          text,
    finished_at    timestamptz NOT NULL DEFAULT now()
);

-- Ülke sınırları (Natural Earth 10m). FIRMS API verisini ülkeye kırpmak için.
CREATE TABLE country_boundary (
    iso2  char(2) PRIMARY KEY,
    name  text NOT NULL,
    geom  geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX country_boundary_geom ON country_boundary USING gist (geom);
