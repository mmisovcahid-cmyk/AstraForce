import time
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.db import get_pool
from app.ingest.sources import COUNTRIES

router = APIRouter()

MAX_RANGE_DAYS = 31
MAX_LIMIT = 20000


# /data/status 26 M satırı tarar (~6 sn); veri günde bir değiştiği için kısa süre önbelleklenir.
STATUS_TTL_S = 600
_status_cache: tuple[float, dict] | None = None


@router.get("/data/status")
def data_status() -> dict:
    """Ülke / kaynak / ürün / yıl bazında yüklü kayıt sayıları (10 dk önbellekli)."""
    global _status_cache
    now = time.monotonic()
    if _status_cache and now - _status_cache[0] < STATUS_TTL_S:
        return _status_cache[1]
    body = _load_status()
    _status_cache = (now, body)
    return body


def _load_status() -> dict:
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT country, source, product, extract(year FROM acq_date)::int AS year,
                   count(*), min(acq_date), max(acq_date)
            FROM fire_detection GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4
            """
        ).fetchall()
    return {
        "rows": [
            {
                "country": c,
                "source": s,
                "product": p,
                "year": y,
                "count": n,
                "first_date": d0.isoformat(),
                "last_date": d1.isoformat(),
            }
            for c, s, p, y, n, d0, d1 in rows
        ]
    }


@router.get("/detections")
def detections(
    country: Annotated[str, Query(description="AZ, TR veya US")],
    date_from: date,
    date_to: date,
    min_confidence: Annotated[int, Query(ge=0, le=2)] = 1,
    exclude_static: Annotated[bool, Query(description="sabit kaynakları (type=2) gizle")] = True,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 5000,
) -> dict:
    """Ham tespit noktaları (GeoJSON). FRP'si en yüksek olanlar önce; `limit` ile kesilir."""
    country = country.upper()
    if country not in COUNTRIES:
        raise HTTPException(400, f"Bilinmeyen ülke: {country}")
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(400, f"En fazla {MAX_RANGE_DAYS} günlük aralık istenebilir")

    where = """
        country = %(country)s AND acq_date BETWEEN %(date_from)s AND %(date_to)s
        AND confidence_level >= %(min_conf)s
        AND (NOT %(exclude_static)s OR fire_type IS DISTINCT FROM 2)
    """
    params = {
        "country": country,
        "date_from": date_from,
        "date_to": date_to,
        "min_conf": min_confidence,
        "exclude_static": exclude_static,
        "limit": limit,
    }
    with get_pool().connection() as conn:
        by_source = dict(
            conn.execute(
                f"SELECT source, count(*) FROM fire_detection WHERE {where} GROUP BY source",
                params,
            ).fetchall()
        )
        features = conn.execute(
            f"""
            SELECT coalesce(json_agg(json_build_object(
                'type', 'Feature',
                'geometry', json_build_object(
                    'type', 'Point', 'coordinates', json_build_array(lon, lat)),
                'properties', json_build_object(
                    'source', source, 'product', product, 'acq_ts', acq_ts, 'frp', frp,
                    'confidence', confidence_level, 'daynight', daynight)
            )), '[]'::json)
            FROM (
                SELECT * FROM fire_detection WHERE {where}
                ORDER BY frp DESC NULLS LAST LIMIT %(limit)s
            ) d
            """,
            params,
        ).fetchone()[0]
    total = sum(by_source.values())
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "total": total,
            "returned": len(features),
            "truncated": total > len(features),
            "by_source": by_source,
        },
    }
