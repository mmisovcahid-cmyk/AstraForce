-- 9. aşama: yanık alan (burned area) katmanı.
--
-- NASA MCD64A1 (MODIS, 500 m) ve VIIRS VNP64A1 ürünlerinden türetilen
-- hücre bazlı yanık alan verileri. H3 r5 hücreleri üzerinden toplanır;
-- análisis fire_detection'dan bağımsızdır.
--
-- Alan birimi: hektar (ha). Bir hücrede bir yılda birden çok yangın
-- olabilir; bu tabloda en ilginç (en büyük alan) kayıt tutulur.

CREATE TABLE burned_area (
    h3_r5         h3index NOT NULL,
    year          integer NOT NULL,
    month         integer NOT NULL CHECK (month BETWEEN 1 AND 12),
    sensor        text NOT NULL CHECK (sensor IN ('MODIS_MCD64A1', 'VIIRS_VNP64A1')),
    burn_date     date,                     -- ilk tespit edilen yanık günü (yaklaşık)
    burned_ha     real NOT NULL,            -- hektar cinsinden yanık alan
    confidence    real NOT NULL DEFAULT 0,  -- 0..1 güven skoru
    PRIMARY KEY (h3_r5, year, month, sensor)
);
CREATE INDEX burned_area_year_month ON burned_area (year, month);
CREATE INDEX burned_area_h3_r5 ON burned_area (h3_r5);
