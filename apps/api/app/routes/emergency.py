"""Acil durum uyarıları (EONET, GDACS, ReliefWeb) analitiği ve harita katmanı.

Üç farklı kaynaktan gelen uyarıları tek bir GeoJSON görünümde sunar.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.db import get_pool

router = APIRouter(prefix="/emergency")


@router.get("/alerts")
def emergency_alerts(
    area: Annotated[str, Query(description="Ülke kodu (AZ, TR) ya da roi:<id>")],
    date_from: Annotated[date, Query(description="Başlangıç tarihi")],
    date_to: Annotated[date, Query(description="Bitiş tarihi")],
    source: Annotated[
        str | None,
        Query(description="eonet, gdacs, reliefweb veya hepsi"),
    ] = None,
):
    """Seçilen bölge ve tarih aralığındaki acil durum uyarılarını GeoJSON olarak döner."""
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")

    if area.startswith("roi:"):
        roi_id = area[4:]
        where = "ST_Intersects((SELECT geom FROM roi WHERE id = %s), ea.geometry)"
        params: list = [roi_id]
    else:
        where = "ST_Intersects((SELECT geom FROM country_boundary WHERE iso2 = %s), ea.geometry)"
        params = [area.upper()]

    where += " AND ea.alert_date BETWEEN %s AND %s"
    params.extend([date_from, date_to])

    if source:
        where += " AND ea.source = %s"
        params.append(source)

    with get_pool().connection() as conn:
        fc = conn.execute(
            f"""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', coalesce(json_agg(json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(ea.geometry, 5)::json,
                    'properties', json_build_object(
                        'alert_id', ea.alert_id,
                        'alert_name', ea.alert_name,
                        'alert_description', ea.alert_description,
                        'alert_url', ea.alert_url,
                        'alert_date', ea.alert_date,
                        'source', ea.source,
                        'created_at', ea.created_at
                    )
                )), '[]'::json)
            )
            FROM emergency_alerts ea
            WHERE {where}
            ORDER BY ea.alert_date DESC NULLS LAST
            """,
            params,
        ).fetchone()[0]

    return fc or {"type": "FeatureCollection", "features": []}


@router.get("/summary")
def emergency_summary(
    area: Annotated[str, Query(description="Ülke kodu (AZ, TR) ya da roi:<id>")],
    date_from: Annotated[date, Query(description="Başlangıç tarihi")],
    date_to: Annotated[date, Query(description="Bitiş tarihi")],
):
    """Acil durum uyarı özeti: kaynak bazında sayı."""
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")

    if area.startswith("roi:"):
        roi_id = area[4:]
        where = "ST_Intersects((SELECT geom FROM roi WHERE id = %s), ea.geometry)"
        params: list = [roi_id]
    else:
        where = "ST_Intersects((SELECT geom FROM country_boundary WHERE iso2 = %s), ea.geometry)"
        params = [area.upper()]

    where += " AND ea.alert_date BETWEEN %s AND %s"
    params.extend([date_from, date_to])

    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT ea.source,
                   count(*) AS alerts,
                   min(ea.alert_date) AS first_alert,
                   max(ea.alert_date) AS last_alert
            FROM emergency_alerts ea
            WHERE {where}
            GROUP BY ea.source
            ORDER BY ea.source
            """,
            params,
        ).fetchall()

    return {
        "area": area,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "sources": [
            {
                "source": r[0],
                "alerts": r[1],
                "first_alert": r[2].isoformat() if r[2] else None,
                "last_alert": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ],
    }
