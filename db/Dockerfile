# PostgreSQL 17 + PostGIS 3.6 + H3 (Uber altıgen ızgara) eklentisi.
# Not: 17-3.5 etiketi Debian bullseye tabanlı; PGDG artık bullseye paketi yayınlamıyor,
# bu yüzden trixie tabanlı 17-3.6 kullanılıyor.
# Render'ın yönetilen PostgreSQL'inde H3 yok → üretimde bu imaj "private service" olarak çalışır.
FROM postgis/postgis:17-3.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-h3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# İlk açılışta (boş disk) init betikleri: eklentiler + (DUMP_URL verilmişse) yedeği yükle
COPY init/ /docker-entrypoint-initdb.d/
