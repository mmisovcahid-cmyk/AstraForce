"""Yanık alan (burned area) analitiği ve harita katmanı.

MODIS MCD64A1 / VIIRS VNP64A1 ürünlerinden türetilen hücre bazlı yanık alan
verilerini GeoJSON ve özet olarak döner.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.db import get_pool

router = APIRouter(prefix="/burned-area")


@router.get("")
def burned_area_geojson(
    area: Annotated[str, Query(description="Ülke kodu (AZ, TR) ya da roi:<id>")],
    date_from: Annotated[date, Query(description="Başlangıç tarihi")],
    date_to: Annotated[date, Query(description="Bitiş tarihi")],
    sensor: Annotated[
        str | None,
        Query(description="MODIS_MCD64A1 veya VIIRS_VNP64A1"),
    ] = None,
):
    """Seçilen bölge ve tarih aralığındaki yanık alan hücrelerini GeoJSON olarak döner."""
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")

    where = "ba.year BETWEEN EXTRACT(YEAR FROM %s::date) AND EXTRACT(YEAR FROM %s::date)"
    params: list = [date_from, date_to]

    if area.startswith("roi:"):
        roi_id = area[4:]
        where += (
            " AND ST_Intersects((SELECT geom FROM roi WHERE id = %s),"
            " h3_cell_to_geometry(ba.h3_r5))"
        )
        params.append(roi_id)
    else:
        where += " AND %s = ANY((SELECT countries FROM roi WHERE id = %s)::char(2)[])"
        # ülke kodu doğrudan fire_detection üzerinden filtrelenecek; burned_area'da country yok
        # h3 hücreleri ülke sınırlarıyla kesişimi kontrol edilir
        where = (
            "ST_Intersects((SELECT geom FROM country_boundary WHERE iso2 = %s),"
            " h3_cell_to_geometry(ba.h3_r5))"
        )
        params = [area.upper(), date_from, date_to]

    if sensor:
        where += " AND ba.sensor = %s"
        params.append(sensor)

    with get_pool().connection() as conn:
        fc = conn.execute(
            f"""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', coalesce(json_agg(json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(h3_cell_to_boundary_geometry(ba.h3_r5), 5)::json,
                    'properties', json_build_object(
                        'h3', ba.h3_r5::text, 'year', ba.year, 'month', ba.month,
                        'sensor', ba.sensor, 'burn_date', ba.burn_date,
                        'burned_ha', round(ba.burned_ha::numeric, 2),
                        'confidence', round(ba.confidence::numeric, 2),
                        'center_lat', ST_Y(h3_cell_to_geometry(ba.h3_r5)),
                        'center_lon', ST_X(h3_cell_to_geometry(ba.h3_r5))
                    )
                )), '[]'::json)
            )
            FROM burned_area ba
            WHERE {where}
            ORDER BY ba.burned_ha DESC
            """,
            params,
        ).fetchone()[0]

    return fc or {"type": "FeatureCollection", "features": []}


@router.get("/summary")
def burned_area_summary(
    area: Annotated[str, Query(description="Ülke kodu (AZ, TR) ya da roi:<id>")],
    date_from: Annotated[date, Query(description="Başlangıç tarihi")],
    date_to: Annotated[date, Query(description="Bitiş tarihi")],
):
    """Yanık alan özeti: toplam hektar, hücre sayısı, sensör bazında."""
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")

    if area.startswith("roi:"):
        roi_id = area[4:]
        where = (
            "ST_Intersects((SELECT geom FROM roi WHERE id = %s),"
            " h3_cell_to_geometry(ba.h3_r5))"
        )
        params: list = [roi_id]
    else:
        where = (
            "ST_Intersects((SELECT geom FROM country_boundary WHERE iso2 = %s),"
            " h3_cell_to_geometry(ba.h3_r5))"
        )
        params = [area.upper(), date_from, date_to]

    where += " AND ba.year BETWEEN EXTRACT(YEAR FROM %s::date) AND EXTRACT(YEAR FROM %s::date)"
    params.extend([date_from, date_to])

    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT ba.sensor,
                   count(DISTINCT ba.h3_r5) AS cells,
                   round(sum(ba.burned_ha)::numeric, 2) AS total_ha,
                   min(ba.burn_date) AS first_burn,
                   max(ba.burn_date) AS last_burn
            FROM burned_area ba
            WHERE {where}
            GROUP BY ba.sensor
            ORDER BY ba.sensor
            """,
            params,
        ).fetchall()

    return {
        "area": area,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "sensors": [
            {
                "sensor": r[0],
                "cells": r[1],
                "total_ha": r[2],
                "first_burn": r[3].isoformat() if r[3] else None,
                "last_burn": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ],
    }
