"""İndirmeler: arama sonucu sıcak noktalar (CSV), günlük harmonize seri, ay × yıl matrisi."""

import csv
import io
from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from psycopg import sql

from app.analytics import month_matrix
from app.areas import FIRST_DAY, AreaNotReady
from app.db import get_pool
from app.routes.analytics import (
    AreaQ,
    Metric,
    full,
    load_series,
    not_ready_response,
    parse_area_or_400,
)

router = APIRouter(prefix="/export")

MAX_HOTSPOT_ROWS = 2_000_000
ATTRIBUTION = "Source: NASA FIRMS (MODIS C6.1, VIIRS 375 m); harmonization: AstraForce"


def _filename(area_code: str, kind: str, suffix: str = "") -> str:
    safe = area_code.replace(":", "-")
    return f"astraforce_{safe}_{kind}{suffix}.csv"


def _csv_response(rows: Iterator[str], filename: str) -> StreamingResponse:
    return StreamingResponse(
        rows,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Data-Attribution": ATTRIBUTION,
        },
    )


@router.get("/hotspots.csv")
def hotspots(area: AreaQ, date_from: date, date_to: date):
    """Seçilen alan ve tarih aralığındaki tüm ham sıcak noktalar (NASA FIRMS kayıtları).

    `used_in_harmonization` = temizlik filtresinden geçti (güven ≥ nominal, sabit kaynak değil);
    `static_source_mask` = sabit ısı kaynağı (endüstri/gaz meşalesi) maskesinde.
    """
    a = parse_area_or_400(area)
    if date_to < date_from:
        raise HTTPException(400, "date_to, date_from'dan önce olamaz")
    if a.kind == "country":
        where = sql.SQL("f.country = {}").format(sql.Literal(a.key))
    else:
        where = sql.SQL("f.geom && r.geom AND ST_Intersects(f.geom, r.geom) AND r.id = {}").format(
            sql.Literal(a.key)
        )
    query = sql.SQL(
        """
        COPY (
            SELECT f.acq_date AS date, to_char(f.acq_ts AT TIME ZONE 'UTC', 'HH24:MI') AS time_utc,
                   f.lat AS latitude, f.lon AS longitude, f.source, f.satellite, f.product,
                   f.confidence_raw AS confidence, f.confidence_level, f.frp AS frp_mw,
                   f.bright_main AS brightness_k, f.bright_aux AS brightness_aux_k, f.daynight,
                   f.fire_type, f.country,
                   (de.detection_id IS NOT NULL) AS used_in_harmonization,
                   (m.h3_r8 IS NOT NULL) AS static_source_mask
            FROM fire_detection f
            {roi_join}
            LEFT JOIN detection_event de ON de.detection_id = f.id
            LEFT JOIN static_mask m ON m.h3_r8 = f.h3_r8
            WHERE {where} AND f.acq_date BETWEEN {d0} AND {d1}
            ORDER BY f.acq_ts
            LIMIT {limit}
        ) TO STDOUT WITH (FORMAT csv, HEADER true)
        """
    ).format(
        roi_join=sql.SQL("CROSS JOIN roi r" if a.kind == "roi" else ""),
        where=where,
        d0=sql.Literal(date_from),
        d1=sql.Literal(date_to),
        limit=sql.Literal(MAX_HOTSPOT_ROWS),
    )

    def stream() -> Iterator[bytes]:
        with get_pool().connection() as conn, conn.cursor() as cur, cur.copy(query) as copy:
            yield from copy

    return _csv_response(stream(), _filename(a.code, "hotspots", f"_{date_from}_{date_to}"))


@router.get("/daily.csv")
def daily(area: AreaQ, date_from: date | None = None, date_to: date | None = None):
    """Günlük harmonize seri: sıcak nokta, olay-gün, FRP (yangınsız günler 0)."""
    a = parse_area_or_400(area)
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    d0, d1 = date_from or FIRST_DAY, date_to or today
    series = {m: full(df, m, today) for m in ("hotspots", "events", "frp")}
    prov = df["provisional"] if not df.empty else None

    def rows() -> Iterator[str]:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "date",
                "hotspots_harmonized",
                "fire_events_harmonized",
                "frp_mw_harmonized",
                "provisional_nrt",
                "area",
            ]
        )
        for ts, h in series["hotspots"].items():
            if not (d0 <= ts.date() <= d1):
                continue
            w.writerow(
                [
                    ts.date().isoformat(),
                    round(h, 3),
                    round(series["events"][ts], 3),
                    round(series["frp"][ts], 2),
                    bool(prov.get(ts, False)) if prov is not None else False,
                    a.code,
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    return _csv_response(rows(), _filename(a.code, "daily"))


@router.get("/matrix.csv")
def matrix(area: AreaQ, metric: Metric = "hotspots"):
    """Ay × yıl matrisi: toplam, tarihsel medyan ve medyana göre anomali (%)."""
    a = parse_area_or_400(area)
    try:
        df, today = load_series(a)
    except AreaNotReady as e:
        return not_ready_response(e)
    m = month_matrix(full(df, metric, today), FIRST_DAY, today)

    def rows() -> Iterator[str]:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "year",
                "month",
                f"{metric}_harmonized",
                "historical_median",
                "anomaly_pct",
                "anomaly_class",
                "partial_month",
                "median_base_years",
                "area",
            ]
        )
        base = f"{m['base_years'][0]}-{m['base_years'][1]}"
        for c in m["cells"]:
            w.writerow(
                [
                    c["year"],
                    c["month"],
                    c["value"],
                    c["median"],
                    c["anomaly_pct"],
                    c["anomaly_class"],
                    c["partial"],
                    base,
                    a.code,
                ]
            )
        yield buf.getvalue()

    return _csv_response(rows(), _filename(a.code, "monthly", f"_{metric}"))
