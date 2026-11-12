-- Veritabanı ilk oluşturulduğunda bir kez çalışır (boş volume).
-- Yeniden çalıştırmak için: pnpm db:reset
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS h3;
CREATE EXTENSION IF NOT EXISTS h3_postgis CASCADE;
