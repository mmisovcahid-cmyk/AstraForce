#!/usr/bin/env sh
# Sunucuda: data/dumps/astraforce.dump yedeğini üretim veritabanına yükler.
#   POSTGRES_PASSWORD=... sh scripts/restore-db.sh
set -eu
compose="docker compose -f docker-compose.prod.yml"
$compose up -d --wait db
$compose exec -T db pg_restore -U "${POSTGRES_USER:-astra}" -d "${POSTGRES_DB:-astraforce}" \
  --clean --if-exists --no-owner -j 4 /dumps/astraforce.dump
echo "Yedek yüklendi. Uygulamayı başlatın: $compose up -d --build"
