"""Normalize satırları COPY ile geçici tabloya, oradan fire_detection'a aktarır.

Fonksiyonlar çağıranın transaction'ı içinde çalışır; commit etmez.
"""

from collections.abc import Iterable
from datetime import date

import psycopg

from app.ingest.parse import STAGE_COLUMNS

_CREATE_STAGE = """
CREATE TEMP TABLE IF NOT EXISTS stage_fire (
    source text, product text, country char(2), acq_ts timestamptz,
    lat double precision, lon double precision,
    bright_main real, bright_aux real, scan real, track real, frp real,
    confidence_raw text, confidence_level smallint, daynight char(1),
    fire_type smallint, satellite text, version text
)
"""

_COLS = ", ".join(STAGE_COLUMNS)

_INSERT = f"""
INSERT INTO fire_detection ({_COLS}, acq_date, geom, h3_r8)
SELECT {", ".join("s." + c for c in STAGE_COLUMNS)},
       (s.acq_ts AT TIME ZONE 'UTC')::date,
       ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326),
       h3_latlng_to_cell(point(s.lon, s.lat), 8)
FROM stage_fire s
{{where}}
ON CONFLICT ON CONSTRAINT fire_detection_natural_key DO NOTHING
"""

# FIRMS API sınırlayıcı kutuyla çalışır; ülke poligonu dışındaki noktaları at.
_CLIP = """
WHERE EXISTS (
    SELECT 1 FROM country_boundary b
    WHERE b.iso2 = s.country
      AND ST_Intersects(b.geom, ST_SetSRID(ST_MakePoint(s.lon, s.lat), 4326))
)
"""


def load_rows(
    conn: psycopg.Connection, rows: Iterable[tuple], clip_to_country: bool = False
) -> int:
    """Satırları yükler, gerçekten eklenen (yeni) satır sayısını döndürür."""
    with conn.cursor() as cur:
        cur.execute(_CREATE_STAGE)
        cur.execute("TRUNCATE stage_fire")
        with cur.copy(f"COPY stage_fire ({_COLS}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
        cur.execute(_INSERT.format(where=_CLIP if clip_to_country else ""))
        return cur.rowcount


def delete_nrt(conn: psycopg.Connection, source: str, country: str, start: date, end: date) -> int:
    """Kesinleşmiş SP verisi gelen günlerin geçici NRT kayıtlarını siler (çift sayımı önler)."""
    cur = conn.execute(
        "DELETE FROM fire_detection WHERE product = 'NRT' AND source = %s AND country = %s"
        " AND acq_date BETWEEN %s AND %s",
        (source, country, start, end),
    )
    return cur.rowcount


def log_ingest(
    conn: psycopg.Connection,
    key: str,
    kind: str,
    status: str,
    *,
    source: str | None = None,
    product: str | None = None,
    country: str | None = None,
    period: tuple[date, date] | None = None,
    rows_read: int = 0,
    rows_inserted: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_log (key, kind, source, product, country, period_start, period_end,
                                status, rows_read, rows_inserted, error, finished_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (key) DO UPDATE SET
            status = EXCLUDED.status, rows_read = EXCLUDED.rows_read,
            rows_inserted = EXCLUDED.rows_inserted, error = EXCLUDED.error,
            finished_at = EXCLUDED.finished_at
        """,
        (
            key,
            kind,
            source,
            product,
            country,
            period[0] if period else None,
            period[1] if period else None,
            status,
            rows_read,
            rows_inserted,
            error,
        ),
    )


def is_done(conn: psycopg.Connection, key: str) -> bool:
    row = conn.execute("SELECT status FROM ingest_log WHERE key = %s", (key,)).fetchone()
    return row is not None and row[0] == "ok"
