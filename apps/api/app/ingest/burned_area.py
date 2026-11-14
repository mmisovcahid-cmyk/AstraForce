"""Yanık alan (burned area) veri yükleme.

NASA MCD64A1 (MODIS, 500 m) ve VIIRS VNP64A1 ürünlerinden hücre bazlı
yanık alan verilerini `burned_area` tablosuna yükler.

Gerçek NASA Earthdata erişimi için Earthdata username/password
gerekir (.env: EARTHDATA_USER, EARTHDATA_PASS). Kimlik bilgileri
eksikse fonksiyon boş liste döner ve uyarı basar.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import httpx
import psycopg

from app.config import get_settings
from app.ingest.sources import parse_countries

# NASA Earthdata / LPDAAC arama ve indirme endpointleri
EARTHDATA_SEARCH = "https://cmr.earthdata.nasa.gov/search/granules.json"
EARTHDATA_DOWNLOAD = "https://ladsweb.modaps.eosdis.nasa.gov/archive/all/"

# H3 r5 hücresi yaklaşık alanı (km^2) -> hektar için çarpan
H3_R5_AREA_KM2 = 2.59  # H3 res 5 ~ 2.59 km^2


def _earthdata_auth() -> tuple[str, str] | None:
    """Earthdata kimlik bilgilerini .env'den döner."""
    settings = get_settings()
    if not settings.earthdata_user or not settings.earthdata_pass:
        return None
    return settings.earthdata_user, settings.earthdata_pass


def _search_granules(
    short_name: str, start: date, end: date, bbox: tuple[float, float, float, float]
) -> list[dict]:
    """NASA CMR'den uygun granule'ları arar."""
    auth = _earthdata_auth()
    params = {
        "short_name": short_name,
        "temporal": f"{start.isoformat()}T00:00:00Z,{end.isoformat()}T23:59:59Z",
        "bounding_box": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "page_size": 200,
    }
    try:
        with httpx.Client(timeout=30.0, auth=auth) as client:
            resp = client.get(EARTHDATA_SEARCH, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001 - ağ / kimlik sorunları sessize geçer
        print(f"  ! Earthdata arama hatası ({short_name}): {exc}", file=sys.stderr)
        return []
    return data.get("feed", {}).get("entry", [])


def _granule_download_url(entry: dict) -> str | None:
    """Granule girişinden en uygun indirme URL'sini döner."""
    for link in entry.get("links", []):
        if link.get("rel") == "http://esipfed.org/ont/fed/links#has-detailed-metadata":
            continue
        href = link.get("href", "")
        if href.endswith((".h5", ".hdf", ".he5")):
            return href
    return None


def _parse_h5_burned_cells(h5_content: bytes) -> list[tuple[str, float]]:
    """HDF5 içeriğinden H3 r5 hücreleri ve yanık alanları çıkarır.

    Gerçek MCD64A1 / VNP64A1 dosyalarında 'BurnDate' ve 'FirstBurn' gibi
    katmanlar vardır; burada basit bir iskelet döndürülür. Gerçek
    implementasyon h5py / rasterio ile katman okunmalı, suyu-maskelenmiş
    pikseller filtrelenmeli ve H3 hücrelerine dönüştürülmeli.
    """
    # TODO: gerçek HDF5 okuma (h5py/rasterio) buraya gelecek
    # Şu anki sürüm boş döner; dosya indirildiği anlaşılır ama işlenmez.
    return []


def _download_monthly(
    year: int, month: int, sensor: str
) -> list[tuple[str, float, float]]:
    """Bir ülke için bir ayın yanık alan kayıtlarını döner.

    Dönüş: [(h3_r5_str, burned_ha, confidence), ...]

    NASA Earthdata'dan MCD64A1 (MODIS) / VNP64A1 (VIIRS) granule'larını
    arar, indirme URL'sini bulur ve hücre bazlı yanık alanı çıkarır.
    Kimlik bilgisi yoksa veya ağ hatası varsa boş liste döner.
    """
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    # FIRMS'te desteklenen 6 ülke için tahmini bounding box'lar
    # (Gerçek implementasyonda sources.py'den COUNTRIES api_bboxes kullanılmalı)
    COUNTRY_BBOXES: dict[str, tuple[float, float, float, float]] = {
        "AZ": (44.7, 38.3, 50.7, 42.0),
        "TR": (25.6, 35.8, 44.9, 42.2),
        "US": (-125.0, 24.4, -66.8, 49.5),
        "AR": (-73.6, -55.1, -53.5, -21.7),
        "GR": (19.3, 34.7, 29.7, 41.8),
        "PT": (-9.6, 36.9, -6.1, 42.2),
    }

    short_name = "MCD64A1" if sensor == "MODIS_MCD64A1" else "VNP64A1"
    results: list[tuple[str, float, float]] = []

    for iso2, bbox in COUNTRY_BBOXES.items():
        entries = _search_granules(short_name, start, end, bbox)
        if not entries:
            continue
        # En yeni granule'u seç (bir ayda genellikle birkaç ürün vardır)
        entry = entries[0]
        url = _granule_download_url(entry)
        if not url:
            continue
        # Kimlik bilgisi yoksa indirme çalışmayabilir; hata sessize geçer
        try:
            auth = _earthdata_auth()
            with httpx.Client(timeout=60.0, auth=auth) as client:
                resp = client.get(url, follow_redirects=True)
                resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(
                f"  ! Earthdata indirme hatası ({iso2}, {short_name}): {exc}",
                file=sys.stderr,
            )
            continue
        cells = _parse_h5_burned_cells(resp.content)
        for h3_r5_str, burned_ha in cells:
            results.append((h3_r5_str, burned_ha, 0.8))

    return results


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

    if not settings.earthdata_user or not settings.earthdata_pass:
        print(
            "Uyarı: EARTHDATA_USER / EARTHDATA_PASS .env'de tanımlı değil. "
            "Yanık alan verisi yüklenemeyecek.",
            file=sys.stderr,
        )

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        n = ingest_burned_area(
            conn, [c.iso2 for c in countries], args.year, args.month, args.sensor, args.force
        )
        print(f"{n} yanık alan kaydı yüklendi ({args.sensor}, {args.year}-{args.month:02d})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
