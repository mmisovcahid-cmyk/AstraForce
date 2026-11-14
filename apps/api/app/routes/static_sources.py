"""Endüstriyel tesisler ve gaz meşaleleri gibi statik ısı kaynakları katmanı.

`static_mask` tablosundaki H3 r8 hücrelerini GeoJSON olarak döner. Bu hücreler
analizden çıkarılmış ama harita üzerinde gösterilebilir, raporlanabilir verilerdir.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.db import get_pool

router = APIRouter(prefix="/static-sources")


@router.get("")
def static_sources(
    country: Annotated[str | None, Query(description="ISO2 ülke kodu (AZ, TR, vb.)")] = None,
    reason: Annotated[
        str | None,
        Query(
            description="nasa_type2, persistent veya neighbor",
            pattern="^(nasa_type2|persistent|neighbor)$",
        ),
    ] = None,
):
    """Statik ısı kaynaklarını (meşale, endüstri) GeoJSON FeatureCollection olarak döner."""
    where = "1=1"
    params: list = []
    if country:
        where += " AND fm.country = %s"
        params.append(country.upper())
    if reason:
        where += " AND m.reason = %s"
        params.append(reason)

    with get_pool().connection() as conn:
        # Ülke filtresi fire_detection üzerinden; static_mask'te country yok.
        fc = conn.execute(
            f"""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', coalesce(json_agg(json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(h3_cell_to_boundary_geometry(h3_r8), 5)::json,
                    'properties', json_build_object(
                        'h3', h3_r8::text, 'reason', m.reason,
                        'center_lat', ST_Y(h3_cell_to_geometry(h3_r8)),
                        'center_lon', ST_X(h3_cell_to_geometry(h3_r8))
                    )
                )), '[]'::json)
            )
            FROM static_mask m
            LEFT JOIN LATERAL (
                SELECT country FROM fire_detection f
                WHERE f.h3_r8 = m.h3_r8 LIMIT 1
            ) fm ON true
            WHERE {where}
            """,
            params,
        ).fetchone()[0]

    return fc or {"type": "FeatureCollection", "features": []}


@router.get("/summary")
def static_summary(
    country: Annotated[str | None, Query(description="ISO2 ülke kodu (AZ, TR, vb.)")] = None,
):
    """Statik kaynak özeti: neden bazında hücre sayıları."""
    where = "1=1"
    params: list = []
    if country:
        where += " AND fm.country = %s"
        params.append(country.upper())

    with get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            SELECT m.reason, count(DISTINCT m.h3_r8) AS cells
            FROM static_mask m
            LEFT JOIN LATERAL (
                SELECT country FROM fire_detection f
                WHERE f.h3_r8 = m.h3_r8 LIMIT 1
            ) fm ON true
            WHERE {where}
            GROUP BY m.reason
            ORDER BY m.reason
            """,
            params,
        ).fetchall()
    return {"country": country or "all", "sources": [{"reason": r, "cells": c} for r, c in rows]}
