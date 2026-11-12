-- NOAA-21 (VIIRS) bölge önbelleğine; günlük güncelleme kaydı.
ALTER TABLE roi_daily ADD COLUMN noaa21_det integer NOT NULL DEFAULT 0;

-- Otomatik güncellemelerin geçmişi (arayüzde "son güncelleme" ve hata takibi için).
CREATE TABLE update_run (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error')),
    countries    text[] NOT NULL,
    detail       text
);
