"""ReliefWeb (UN OCHA) afet raporu yükleyici.

ReliefWeb: https://api.reliefweb.int/v1/reports
Yangın / yangınla ilgili raporları filtreleyip `reliefweb_reports` tablosuna yazar.
Kimlik gerektirmeyen açık API'dir (rate-limited).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from typing import Any

import httpx
import psycopg

from app.config import get_settings

RELIEFWEB_API = "https://api.reliefweb.int/v1/reports"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def fetch_reliefweb_reports(
    start: date, end: date, query: str | None = "fire"
) -> list[dict[str, Any]]:
    """ReliefWeb API'dan belirli tarih aralığındaki raporları çeker."""
    params: dict[str, Any] = {
        "profile": "full",
        "limit": 100,
        "sort": "date:desc",
        "filter": {
            "field": "date",
            "value": {"from": start.isoformat(), "to": end.isoformat()},
        },
    }
    if query:
        params["filter"] = {
            "operator": "AND",
            "conditions": [
                {"field": "date", "value": {"from": start.isoformat(), "to": end.isoformat()}},
                {"field": "body", "value": query, "operator": "like"},
            ],
        }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(RELIEFWEB_API, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! ReliefWeb çekme hatası: {exc}", file=sys.stderr)
        return []
    return data.get("data", [])


def ingest_reliefweb(
    conn: psycopg.Connection,
    start: date,
    end: date,
    query: str | None = "fire",
    force: bool = False,
) -> int:
    """ReliefWeb raporlarını `reliefweb_reports` tablosuna yazar. Eklenen kayıt sayısını döner."""
    reports = fetch_reliefweb_reports(start, end, query)
    inserted = 0
    for rep in reports:
        fields = rep.get("fields", {})
        rid = fields.get("rid", "")
        name = fields.get("name", "")
        body = fields.get("body", "")
        primary_url = fields.get("primary_url", {})
        url = primary_url.get("value", "") if isinstance(primary_url, dict) else ""
        date_field = fields.get("date", {})
        report_date = (
            _parse_date(date_field.get("created")) if isinstance(date_field, dict) else None
        )

        # ReliefWeb'te coğrafya genellikle country objesi içinde; burada basitçe boş bırakıyoruz.
        geom_wkt = None

        conn.execute(
            """
            INSERT INTO reliefweb_reports
                (rid, name, body, url, date, geometry, source, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s::geometry, %s, now())
            ON CONFLICT (rid) DO UPDATE
                SET name = EXCLUDED.name,
                    body = EXCLUDED.body,
                    url = EXCLUDED.url,
                    date = EXCLUDED.date,
                    geometry = EXCLUDED.geometry,
                    source = EXCLUDED.source,
                    updated_at = now()
            """,
            (
                rid,
                name,
                body,
                url,
                report_date,
                geom_wkt,
                "reliefweb",
            ),
        )
        inserted += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="reliefweb",
        description="ReliefWeb afet raporlarını yükler",
    )
    p.add_argument("--days", type=int, default=30, help="Geri dönük arama aralığı (gün)")
    p.add_argument("--query", default="fire", help="ReliefWeb arama terimi (varsayılan: fire)")
    args = p.parse_args(argv)

    end = date.today()
    start = end - timedelta(days=args.days)
    settings = get_settings()

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        n = ingest_reliefweb(conn, start, end, args.query)
        print(f"{n} ReliefWeb raporu yüklendi ({start} -> {end}, sorgu: {args.query})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
