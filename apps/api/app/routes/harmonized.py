from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from app.db import get_pool
from app.ingest.sources import COUNTRIES

router = APIRouter(prefix="/harmonized")


def _country(value: str) -> str:
    code = value.upper()
    if code not in COUNTRIES:
        raise HTTPException(400, f"Bilinmeyen ülke: {code}")
    return code


@router.get("/daily")
def daily(
    country: Annotated[str, Query(description="AZ, TR veya US")],
    date_from: date,
    date_to: date,
) -> dict:
    """Ülke toplamı günlük HFI (MODIS eşdeğeri olay-gün). Yangın olmayan günler listede yok."""
    country = _country(country)
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")
    with get_pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT day, sum(hfi), sum(hfi_frp), bool_or(provisional), min(model_version)
            FROM harmonized_daily
            WHERE country = %s AND day BETWEEN %s AND %s
            GROUP BY day ORDER BY day
            """,
            (country, date_from, date_to),
        ).fetchall()
    return {
        "country": country,
        "model_version": rows[0][4] if rows else None,
        "days": [
            {"day": d.isoformat(), "hfi": round(h, 3), "hfi_frp": round(f, 2), "provisional": p}
            for d, h, f, p, _ in rows
        ],
    }


@router.get("/validation")
def validation(
    country: Annotated[str, Query(description="AZ, TR, US veya AR")],
    target: Literal["det", "evt"] = "det",
) -> dict:
    """Aday modellerin yıl-dışı doğrulama ölçüleri ve yıllık karşılaştırma serisi."""
    country = _country(country)
    with get_pool().connection() as conn:
        models = conn.execute(
            """
            SELECT version, method, selected, metrics, params - 'factors', created_at
            FROM calibration_model WHERE country = %s AND target = %s
            ORDER BY selected DESC, method
            """,
            (country, target),
        ).fetchall()
        if not models:
            raise HTTPException(404, f"{country} için harmonizasyon yok (pnpm harmonize run)")
        selected_version = next(v for v, _, s, *_ in models if s)
        years = conn.execute(
            """
            SELECT year, modis_det, viirs_det, modis_evt, viirs_evt, hfi, hfi_det
            FROM harmonized_validation WHERE country = %s AND model_version = %s ORDER BY year
            """,
            (country, selected_version),
        ).fetchall()
    return {
        "country": country,
        "target": target,
        "model_version": selected_version,
        "candidates": [
            {"method": m, "selected": s, "metrics": met, "params": p, "created_at": c.isoformat()}
            for _, m, s, met, p, c in models
        ],
        "years": [
            {
                "year": y,
                "modis_det": md,
                "viirs_det": vd,
                "modis_evt": me,
                "viirs_evt": ve,
                "hfi": h,
                "hfi_det": hd,
            }
            for y, md, vd, me, ve, h, hd in years
        ],
    }
