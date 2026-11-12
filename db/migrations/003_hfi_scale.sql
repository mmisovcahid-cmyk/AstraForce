-- Takvim renk düzeyleri için bölgeye özgü eşikler (yangınlı günlerin p50 / p80 / p95'i).
-- Her harmonizasyon sonunda yeniden hesaplanır; yıllar arası karşılaştırma için sabit kalır.
CREATE TABLE hfi_scale (
    country        char(2) PRIMARY KEY,
    model_version  text    NOT NULL,
    thresholds     real[]  NOT NULL,
    base_years     int4range NOT NULL,
    computed_at    timestamptz NOT NULL DEFAULT now()
);
