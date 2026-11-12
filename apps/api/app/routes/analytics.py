"""Alan (ülke ya da ROI) analitiği: takvim, sezon, ay × yıl matrisi, durum, aralık, hücreler.

Tüm uç noktalar `area=TR` ya da `area=roi:<id>` ve `metric=hotspots|events|frp` alır.
ROI henüz hesaplanıyorsa 202 + {status, progress} döner.
"""

from datetime import date, timedelta
from typing import Annotated, Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.analytics import (
    BASE_FIRST_YEAR,
    anomaly_pct,
    base_years,
    climatology,
    current_status,
    full_series,
    last_complete_year,
    levels,
    month_matrix,
    season_dates,
    thresholds,
    trend,
)
from app.areas import (
    FIRST_DAY,
    Area,
    AreaError,
    AreaNotReady,
    daily_series,
    parse_area,
    raw_counts,
)
from app.db import get_pool
from app.harmonize.settings import MODIS, VIIRS_SOURCES

router = APIRouter(prefix="/analytics")

Metric = Literal["hotspots", "events", "frp"]
AreaQ = Annotated[str, Query(description="Ülke kodu (AZ, TR, US, AR) ya da roi:<id>")]
MEAN_DISPLAY_YEAR = 2024  # ortalama modunda 366 günlük takvim için artık yıl
MAX_CELL_RANGE_DAYS = 366


def parse_area_or_400(value: str) -> Area:
    try:
        return parse_area(value)
    except AreaError as e:
        raise HTTPException(400, str(e)) from e


def not_ready_response(e: AreaNotReady) -> JSONResponse:
    # 202: bölge hâlâ hesaplanıyor; istemci ilerlemeyi gösterip tekrar dener
    return JSONResponse({"status": e.status, "progress": e.progress}, status_code=202)


def load_series(area: Area) -> tuple[pd.DataFrame, date]:
    """Alanın günlük serisi. ROI hazır değilse AreaNotReady yükselir."""
    with get_pool().connection() as conn:
        try:
            df = daily_series(conn, area)
        except AreaError as e:
            raise HTTPException(404, str(e)) from e
    if area.kind == "country" and df.empty:
        raise HTTPException(404, f"{area.key} için harmonizasyon yok (pnpm harmonize run)")
    return df, date.today()


def full(df: pd.DataFrame, metric: str, today: date) -> pd.Series:
    return full_series(df[metric] if not df.empty else pd.Series(dtype=float), FIRST_DAY, today)


@router.get("/calendar")
def calendar(
    area: AreaQ,
    year: int | None = None,
    mode: Literal["year", "mean"] = "year",
    year_from: int = BASE_FIRST_YEAR,
    year_to: int | None = None,
):
    """GitHub tarzı takvim: her gün için üç göstergenin değeri ve renk düzeyleri.

    Düzeyler alanın kendi 20 yıllık yangınlı günlerine göredir (p50/p80/p95).
    mode=mean: [year_from, year_to] yıllarında her takvim gününün ortalaması (2024 takvimiyle).
    """
    a = parse_area_or_400(area)
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    series = {m: full(df, m, today) for m in ("hotspots", "events", "frp")}
    th = {m: thresholds(s, today) for m, s in series.items()}
    prov = df["provisional"] if not df.empty else pd.Series(dtype=bool)

    if mode == "mean":
        y_to = year_to or last_complete_year(today)
        if not BASE_FIRST_YEAR <= year_from <= y_to:
            raise HTTPException(400, "Geçersiz yıl aralığı")
        means = {}
        for m, s in series.items():
            part = s[(s.index.year >= year_from) & (s.index.year <= y_to)]
            means[m] = part.groupby(part.index.strftime("%m-%d")).mean()
        days = []
        for md in sorted(means["hotspots"].index):
            vals = {m: float(means[m][md]) for m in means}
            days.append(
                {
                    "date": f"{MEAN_DISPLAY_YEAR}-{md}",
                    **{m: round(v, 3) for m, v in vals.items()},
                    **{f"level_{m}": int(levels([vals[m]], th[m])[0]) for m in vals},
                    "provisional": False,
                }
            )
        return {
            "area": a.code,
            "mode": "mean",
            "years": [year_from, y_to],
            "thresholds": th,
            "days": days,
        }

    if year is None:
        raise HTTPException(400, "year gerekli (ya da mode=mean)")
    first, last = date(year, 1, 1), date(year, 12, 31)
    with get_pool().connection() as conn:
        raw = raw_counts(conn, a, first, last)
    days = []
    for ts in pd.date_range(first, last, freq="D"):
        iso = ts.date().isoformat()
        if ts.date() < FIRST_DAY or ts.date() > today:
            days.append(
                {
                    "date": iso,
                    "hotspots": None,
                    "level_hotspots": None,
                    "level_events": None,
                    "level_frp": None,
                    "provisional": False,
                }
            )
            continue
        vals = {m: float(series[m].get(ts, 0.0)) for m in series}
        r = raw.get(iso, {})
        days.append(
            {
                "date": iso,
                **{m: round(v, 3) for m, v in vals.items()},
                **{f"level_{m}": int(levels([vals[m]], th[m])[0]) for m in vals},
                "provisional": bool(prov.get(ts, False)),
                "modis_det": r.get(MODIS, 0),
                "viirs_snpp_det": r.get(VIIRS_SOURCES[0], 0),
                "viirs_noaa20_det": r.get(VIIRS_SOURCES[1], 0),
            }
        )
    in_year = {
        m: s[(s.index >= pd.Timestamp(first)) & (s.index <= pd.Timestamp(last))]
        for m, s in series.items()
    }
    return {
        "area": a.code,
        "mode": "year",
        "year": year,
        "thresholds": th,
        "totals": {m: round(float(v.sum()), 2) for m, v in in_year.items()},
        "days": days,
    }


@router.get("/season")
def season(area: AreaQ, metric: Metric = "hotspots"):
    """Yıllık sezon tarihleri, toplamlar, sıra; 20 yıllık klimatoloji (medyan dahil); trend."""
    a = parse_area_or_400(area)
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    s = full(df, metric, today)
    yrs = base_years(today)

    years = []
    for yr in range(FIRST_DAY.year, today.year + 1):
        info = season_dates(s[s.index.year == yr])
        info.update({"year": yr, "complete": yrs[0] <= yr <= yrs[-1]})
        years.append(info)
    complete = [y for y in years if y["complete"]]
    totals = {y["year"]: y["total"] for y in complete}
    ranking = sorted(totals, key=totals.get, reverse=True)
    mean_total = float(np.mean(list(totals.values()))) if totals else 0.0
    median_total = float(np.median(list(totals.values()))) if totals else 0.0
    for y in years:
        y["rank"] = ranking.index(y["year"]) + 1 if y["year"] in totals else None
        y["vs_median_pct"] = (
            round((y["total"] / median_total - 1) * 100, 1)
            if y["complete"] and median_total
            else None
        )

    def mean_doy(key: str) -> float | None:
        vals = [pd.Timestamp(y[key]).day_of_year for y in complete if y[key]]
        return round(float(np.mean(vals)), 1) if vals else None

    return {
        "area": a.code,
        "metric": metric,
        "base_years": [yrs[0], yrs[-1]],
        "mean_total": round(mean_total, 1),
        "median_total": round(median_total, 1),
        "mean_season_doy": {k: mean_doy(k) for k in ("start", "mid", "end", "peak_week_start")},
        "years": years,
        "climatology": climatology(s, yrs),
        "trend": trend(list(totals), list(totals.values())),
    }


@router.get("/matrix")
def matrix(area: AreaQ, metric: Metric = "hotspots"):
    """Ay × yıl matrisi: toplam, o ayın tarihsel medyanı, medyana göre anomali, renk düzeyi."""
    a = parse_area_or_400(area)
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    body = month_matrix(full(df, metric, today), FIRST_DAY, today)
    return {"area": a.code, "metric": metric, **body}


@router.get("/status")
def status(area: AreaQ, metric: Metric = "hotspots"):
    """Acil durum özeti: bu ay (şimdiye kadar) ve son 7 gün, tarihsel medyana göre."""
    a = parse_area_or_400(area)
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    out = current_status(full(df, metric, today), today)
    latest = df.index.max() if not df.empty else None
    out.update(
        {
            "area": a.code,
            "metric": metric,
            "latest_data_day": latest.date().isoformat() if latest is not None else None,
        }
    )
    return out


def same_range_in_year(date_from: date, date_to: date, year: int) -> tuple[date, date]:
    """[date_from, date_to] aralığını, bitişi `year` yılına düşecek şekilde kaydırır."""
    shift = year - date_to.year

    def move(d: date) -> date:
        try:
            return d.replace(year=d.year + shift)
        except ValueError:  # 29 Şubat
            return d.replace(year=d.year + shift, day=28)

    return move(date_from), move(date_to)


@router.get("/range")
def range_summary(area: AreaQ, date_from: date, date_to: date, metric: Metric = "hotspots"):
    """Seçilen tarih aralığının toplamı ve aynı takvim aralığının tarihsel medyanı."""
    a = parse_area_or_400(area)
    if date_to < date_from or (date_to - date_from).days > 365:
        raise HTTPException(400, "Aralık 1..366 gün olmalı")
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    s = full(df, metric, today)

    def total(f: date, t: date) -> float:
        return float(s[(s.index >= pd.Timestamp(f)) & (s.index <= pd.Timestamp(t))].sum())

    value = total(date_from, date_to)
    hist = [total(*same_range_in_year(date_from, date_to, y)) for y in base_years(today)]
    med = float(np.median(hist)) if hist else 0.0
    sel = s[(s.index >= pd.Timestamp(date_from)) & (s.index <= pd.Timestamp(date_to))]
    return {
        "area": a.code,
        "metric": metric,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total": round(value, 2),
        "median": round(med, 2),
        "anomaly_pct": anomaly_pct(value, med),
        "fire_days": int((sel > 0).sum()),
    }


@router.get("/cells")
def cells(area: AreaQ, date_from: date, date_to: date):
    """Dönem için H3 r5 altıgenlerinde harmonize toplamlar (GeoJSON), harita yoğunluk katmanı.

    ROI için: merkezi bölgenin içinde kalan hücreler.
    """
    a = parse_area_or_400(area)
    if date_to < date_from or (date_to - date_from) > timedelta(days=MAX_CELL_RANGE_DAYS - 1):
        raise HTTPException(400, f"Aralık 1..{MAX_CELL_RANGE_DAYS} gün olmalı")
    if a.kind == "country":
        where, params = "hd.country = %s", [a.key]
    else:
        where = (
            "hd.country = ANY((SELECT countries FROM roi WHERE id = %s)::char(2)[])"
            " AND ST_Intersects((SELECT geom FROM roi WHERE id = %s),"
            " h3_cell_to_geometry(hd.h3_r5))"
        )
        params = [a.key, a.key]
    with get_pool().connection() as conn:
        fc = conn.execute(
            f"""
            SELECT json_build_object('type', 'FeatureCollection', 'features',
              coalesce(json_agg(json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(h3_cell_to_boundary_geometry(h3_r5), 5)::json,
                'properties', json_build_object(
                    'h3', h3_r5::text, 'hotspots', round(d::numeric, 2),
                    'hfi', round(h::numeric, 2), 'frp', round(f::numeric, 1), 'days', n)
              )), '[]'::json))
            FROM (
                SELECT hd.h3_r5, sum(hd.hfi_det) AS d, sum(hd.hfi) AS h, sum(hd.hfi_frp) AS f,
                       count(*) AS n
                FROM harmonized_daily hd
                WHERE {where} AND hd.day BETWEEN %s AND %s GROUP BY hd.h3_r5
            ) c
            """,
            (*params, date_from, date_to),
        ).fetchone()[0]
    values = [f["properties"]["hotspots"] for f in fc["features"]]
    fc["meta"] = {
        "cells": len(values),
        "total": round(float(sum(values)), 1),
        "max": max(values) if values else 0,
    }
    return fc
