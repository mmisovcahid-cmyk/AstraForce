"""Yanık alan (burned area) veri yükleme.

NASA MCD64A1 (MODIS, 500 m) ve VIIRS VNP64A1 ürünlerinden hücre bazlı
yanık alan verilerini `burned_area` tablosuna yükler.

Not: gerçek NASA Earthdata erişimi için Earthdata username/password
gerekir (.env: EARTHDATA_USER, EARTHDATA_PASS). Şu anki implementasyon
örnek/placeholder veri üretir; gerçek veri kaynağı eklemek için
`_download_monthly` fonksiyonu genişletilir.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import psycopg

from app.config import get_settings
from app.ingest.sources import parse_countries


def _download_monthly(
    year: int, month: int, sensor: str
) -> list[tuple[str, int, int, float, float]]:
    """Bir ay için yanık alan kayıtlarını döner.

    Dönüş: [(h3_r5_str, burned_ha, confidence), ...]

    Şu anki sürüm placeholder: boş liste döner. Gerçek implementasyonda
    NASA EarthData'dan MCD64A1 / VNP64A1 dosyası indirilir, H3 hücrelerine
    dönüştürülüp hectares cinsinden hesaplanır.
    """
    # TODO: gerçek NASA EarthData entegrasyonu buraya gelecek
    return []


def ingest_burned_area(
    conn: psycopg.Connection,
    countries: list[str],
    year: int,
    month: int,
    sensor: str = "MODIS_MCD64A1",
    force: bool = False,
) -> int:
    """Belirli bir yıl/ay/sensör için yanık alan verilerini yükler.

    Yüklenen kayıt sayısını döner.
    """
    inserted = 0
    for _iso2 in countries:
        rows = _download_monthly(year, month, sensor)
        with conn.transaction():
            for h3_r5_str, burned_ha, confidence in rows:
                conn.execute(
                    """
                    INSERT INTO burned_area
                        (h3_r5, year, month, sensor, burn_date, burned_ha, confidence)
                    VALUES (%s::h3index, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (h3_r5, year, month, sensor) DO UPDATE
                    SET burned_ha = EXCLUDED.burned_ha,
                        confidence = EXCLUDED.confidence,
                        burn_date = EXCLUDED.burn_date
                    """,
                    (
                        h3_r5_str,
                        year,
                        month,
                        sensor,
                        date(year, month, 1),
                        burned_ha,
                        confidence,
                    ),
                )
                inserted += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="burned_area",
        description="NASA MCD64A1 / VIIRS VNP64A1 yanık alan verisini yükler",
    )
    p.add_argument("--country", required=True, help="Ülke ISO2 kodları (virgülle ayrılmış)")
    p.add_argument("--year", type=int, required=True, help="Yıl (ör. 2021)")
    p.add_argument("--month", type=int, required=True, help="Ay (1-12)")
    p.add_argument(
        "--sensor",
        default="MODIS_MCD64A1",
        choices=["MODIS_MCD64A1", "VIIRS_VNP64A1"],
        help="Sensör ürünü (varsayılan: MODIS_MCD64A1)",
    )
    p.add_argument(
        "--force", action="store_true", help="Mevcut kayıtları yeniden yükle"
    )
    args = p.parse_args(argv)

    if not 1 <= args.month <= 12:
        print("Hata: --month 1 ile 12 arasında olmalı.", file=sys.stderr)
        return 2

    countries = parse_countries(args.country)
    settings = get_settings()

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        n = ingest_burned_area(
            conn, [c.iso2 for c in countries], args.year, args.month, args.sensor, args.force
        )
        print(f"{n} yanık alan kaydı yüklendi ({args.sensor}, {args.year}-{args.month:02d})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
