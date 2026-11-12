"""Veritabanı bakımı: sıcak noktaları konuma göre fiziksel olarak sıralar (CLUSTER) ve
istatistikleri günceller. Büyük çizilmiş bölgelerin ilk hesaplanmasını belirgin hızlandırır:
bir bölgenin noktaları diskte yan yana durur, 25 yıl için çok daha az sayfa okunur.

  python -m app.optimize      (ya da kökten `pnpm db:optimize`)

Tabloyu yeniden yazar: geçici olarak tablonun boyutu kadar ek disk ister ve sürerken tabloyu
kilitler (veri yükleme / harmonizasyon ile aynı anda çalıştırmayın). Birkaç dakika sürer.
"""

import sys
import time

import psycopg

from app.config import get_settings

STATEMENTS = (
    (
        "fire_detection konuma göre sıralanıyor (CLUSTER)",
        "CLUSTER fire_detection USING fire_detection_geom",
    ),
    ("detection_event sıralanıyor", "CLUSTER detection_event USING detection_event_pkey"),
    ("İstatistikler güncelleniyor (ANALYZE)", "ANALYZE"),
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        for label, statement in STATEMENTS:
            t = time.perf_counter()
            print(f"{label}…", flush=True)
            conn.execute(statement)
            print(f"  {time.perf_counter() - t:.0f} sn", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
