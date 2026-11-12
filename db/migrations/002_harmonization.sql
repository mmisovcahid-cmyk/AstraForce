-- 3. aşama: harmonizasyon çıktıları. Hepsi fire_detection'dan yeniden üretilebilir
-- (`pnpm harmonize run`), bu yüzden burada kaynak veri yok.

-- Sabit ısı kaynakları (endüstri, gaz meşaleleri) maskesi, H3 r8 hücreleri.
-- NRT verisinde `type` olmadığı için bu maske NASA'nın SP type=2 işaretinden ve
-- kalıcılıktan türetilir ve tüm ürünlere uygulanır.
CREATE TABLE static_mask (
    h3_r8   h3index PRIMARY KEY,
    reason  text NOT NULL CHECK (reason IN ('nasa_type2', 'persistent', 'neighbor'))
);

-- ST-DBSCAN ile birleştirilmiş yangın olayları (kaynak başına ayrı).
CREATE TABLE fire_event (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country     char(2) NOT NULL,
    source      text    NOT NULL,
    start_date  date    NOT NULL,
    end_date    date    NOT NULL,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    h3_r5       h3index NOT NULL,
    n_det       integer NOT NULL,
    frp_sum     real,
    frp_max     real,
    has_nrt     boolean NOT NULL
);
CREATE INDEX fire_event_country_source_start ON fire_event (country, source, start_date);

-- Kaynak × H3 r5 hücresi × gün istatistikleri (temizlenmiş tespitlerden).
-- n_evt: o gün o hücrede tespiti olan farklı olay sayısı ("olay-gün").
CREATE TABLE daily_cell_stats (
    country  char(2) NOT NULL,
    source   text    NOT NULL,
    h3_r5    h3index NOT NULL,
    day      date    NOT NULL,
    n_det    integer NOT NULL,
    n_evt    integer NOT NULL,
    frp_sum  real    NOT NULL,
    has_nrt  boolean NOT NULL,
    PRIMARY KEY (country, source, day, h3_r5)
);

-- Kalibrasyon modelleri: aday modeller, yıl-dışı doğrulama ölçüleri ve seçilen model.
CREATE TABLE calibration_model (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version     text    NOT NULL,
    country     char(2) NOT NULL,
    method      text    NOT NULL,
    selected    boolean NOT NULL DEFAULT false,
    params      jsonb   NOT NULL,
    metrics     jsonb   NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version, country, method)
);

-- Harmonize Yangın İndeksi (HFI), MODIS eşdeğeri olay-gün ölçeğinde.
CREATE TABLE harmonized_daily (
    country        char(2) NOT NULL,
    h3_r5          h3index NOT NULL,
    day            date    NOT NULL,
    hfi            real    NOT NULL,
    hfi_frp        real    NOT NULL,
    -- 'modis' (2000–2011), 'modis_terra_scaled' (Aqua öncesi), 'viirs_calibrated' (2012+)
    basis          text    NOT NULL,
    provisional    boolean NOT NULL,
    model_version  text    NOT NULL,
    PRIMARY KEY (country, day, h3_r5)
);

-- Ülke × yıl karşılaştırma tablosu (doğrulama ekranı için).
CREATE TABLE harmonized_validation (
    model_version  text    NOT NULL,
    country        char(2) NOT NULL,
    year           integer NOT NULL,
    modis_det      integer,
    viirs_det      real,
    modis_evt      real,
    viirs_evt      real,
    hfi            real,
    PRIMARY KEY (model_version, country, year)
);
