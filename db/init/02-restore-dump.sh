#!/bin/sh
# Veritabanı ilk kez oluşturulurken (boş disk) çalışır. DUMP_URL ortam değişkeni varsa
# `pnpm db:dump` ile alınmış yedeği indirip yükler; böylece 25 yıllık veri sunucuda yeniden
# indirilmez. DUMP_URL yoksa hiçbir şey yapmaz (veri `python -m app.update --bootstrap` ile
# doldurulabilir).
#
# Not: postgres giriş betiği çalıştırılabilir olmayan *.sh dosyalarını "source" eder; bu yüzden
# burada `exit` ya da `set -u` kullanılmıyor (giriş betiğini erken sonlandırırdı).
if [ -n "${DUMP_URL:-}" ]; then
  echo "[astraforce] Yedek indiriliyor: $DUMP_URL"
  if curl -fL --retry 3 -o /tmp/astraforce.dump "$DUMP_URL"; then
    echo "[astraforce] Yedek yükleniyor (birkaç dakika)…"
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --if-exists --clean -j 2 \
      /tmp/astraforce.dump || echo "[astraforce] pg_restore uyarılarla bitti (genelde zararsız)"
    rm -f /tmp/astraforce.dump
    echo "[astraforce] Yedek yüklendi."
  else
    echo "[astraforce] UYARI: yedek indirilemedi; boş veritabanıyla devam ediliyor."
  fi
else
  echo "[astraforce] DUMP_URL yok, yedek yüklenmeyecek."
fi
