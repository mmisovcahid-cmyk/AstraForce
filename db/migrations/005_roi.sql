-- 5. aşama: kullanıcının seçtiği bölgeler (ROI) ve harmonize sıcak nokta sayısı.

-- Her temiz tespitin hangi olaya ait olduğu (events adımında yazılır). Büyük tabloyu
-- UPDATE etmek yerine ayrı tablo: COPY ile hızlı, fire_detection şişmez.
CREATE TABLE detection_event (
    detection_id  bigint PRIMARY KEY,
    event_no      integer NOT NULL  -- (country, source) içinde olay numarası
);

-- Harmonize sıcak nokta sayısı (MODIS eşdeğeri tespit) — görevin "number of hotspots"u.
ALTER TABLE harmonized_daily ADD COLUMN hfi_det real NOT NULL DEFAULT 0;

-- Kalibrasyon artık iki hedef için: olay-gün (evt) ve sıcak nokta (det).
ALTER TABLE calibration_model ADD COLUMN target text NOT NULL DEFAULT 'evt';
ALTER TABLE calibration_model DROP CONSTRAINT calibration_model_version_country_method_key;
ALTER TABLE calibration_model ADD CONSTRAINT calibration_model_key
    UNIQUE (version, country, method, target);

-- Ülke × gün harmonizasyon katsayıları: bölge değeri = katsayı × bölgedeki VIIRS (uydu
-- ortalaması) değeri; VIIRS olmayan günlerde MODIS değeri × katsayı (Terra ölçeği ya da 1).
CREATE TABLE harmonized_factor (
    country      char(2) NOT NULL,
    day          date    NOT NULL,
    basis        text    NOT NULL,   -- viirs_calibrated | modis | modis_terra_scaled
    v_n          smallint NOT NULL,  -- o gün veri veren VIIRS uydusu sayısı
    f_evt        real    NOT NULL,
    f_det        real    NOT NULL,
    f_frp        real    NOT NULL,
    provisional  boolean NOT NULL,
    PRIMARY KEY (country, day)
);

-- Kullanıcı bölgeleri. Kimlik kısa ve paylaşılabilir (?area=roi:abc123).
CREATE TABLE roi (
    id           text PRIMARY KEY,
    name         text,
    geom         geometry(MultiPolygon, 4326) NOT NULL,
    area_km2     real NOT NULL,
    countries    text[] NOT NULL,          -- verisi yüklü ve bölgeyle kesişen ülkeler
    covered_pct  real NOT NULL,            -- bölgenin yüklü ülkelerle örtüşen yüzdesi
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'running', 'ready', 'error')),
    progress     real NOT NULL DEFAULT 0,
    error        text,
    model_version text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    computed_at  timestamptz
);
CREATE INDEX roi_geom ON roi USING gist (geom);

-- Bölgenin günlük harmonize serisi (önbellek; harmonizasyon değişince yeniden hesaplanır).
CREATE TABLE roi_daily (
    roi_id       text NOT NULL REFERENCES roi(id) ON DELETE CASCADE,
    day          date NOT NULL,
    hotspots     real NOT NULL,   -- harmonize sıcak nokta (MODIS eşdeğeri)
    events       real NOT NULL,   -- harmonize olay-gün
    frp          real NOT NULL,   -- harmonize FRP (MW)
    provisional  boolean NOT NULL,
    modis_det    integer NOT NULL,
    snpp_det     integer NOT NULL,
    noaa20_det   integer NOT NULL,
    PRIMARY KEY (roi_id, day)
);
