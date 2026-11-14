"""NASA EONET (Earth Observatory Natural Event Tracker) olay yükleyici.

EONET: https://eonet.gsfc.nasa.gov/api/v3/events
Yangınla ilgili olayları (category: Wildfires) filtreleyip `eonet_events` tablosuna yazar.
Kimlik gerektirmeyen açık API'dir.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from typing import Any

import httpx
import psycopg

from app.config import get_settings

EONET_API = "https://eonet.gsfc.nasa.gov/api/v3/events"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def fetch_eonet_events(
    start: date, end: date, category: str | None = "Wildfires"
) -> list[dict[str, Any]]:
    """EONET API'den belirli tarih aralığındaki olayları çeker."""
    params: dict[str, str] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": "1000",
    }
    if category:
        params["category"] = category
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(EONET_API, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! EONET çekme hatası: {exc}", file=sys.stderr)
        return []
    return data.get("events", [])


def ingest_eonet(
    conn: psycopg.Connection,
    start: date,
    end: date,
    category: str | None = "Wildfires",
    force: bool = False,
) -> int:
    """EONET olaylarını `eonet_events` tablosuna yazar. Eklenen kayıt sayısını döner."""
    events = fetch_eonet_events(start, end, category)
    inserted = 0
    for ev in events:
        geometries = ev.get("geometries", [])
        geom_wkt = None
        event_date = None
        if geometries:
            g = geometries[0]
            geom = g.get("geometry", {})
            if geom:
                coords = geom.get("coordinates", [])
                geom_type = geom.get("type", "Point")
                if coords:
                    # Basit WKT üretimi (Point / Polygon destekli)
                    if geom_type == "Point":
                        lon, lat = coords[0], coords[1]
                        geom_wkt = f"POINT({lon} {lat})"
                    elif geom_type in ("Polygon", "MultiPolygon"):
                        # İlk exterior ring'i al
                        rings = coords[0] if geom_type == "Polygon" else coords[0][0]
                        pts = " ".join(f"{c[0]} {c[1]}" for c in rings)
                        geom_wkt = f"POLYGON(({pts}))"
                    event_date = _parse_date(g.get("date"))
        sources = ev.get("sources", [])
        source_name = sources[0].get("id", "eonet") if sources else "eonet"

        conn.execute(
            """
            INSERT INTO eonet_events
                (id, title, description, link, closed, event_date, geometry, source, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::geometry, %s, now())
            ON CONFLICT (id) DO UPDATE
                SET title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    link = EXCLUDED.link,
                    closed = EXCLUDED.closed,
                    event_date = EXCLUDED.event_date,
                    geometry = EXCLUDED.geometry,
                    source = EXCLUDED.source,
                    updated_at = now()
            """,
            (
                ev.get("id"),
                ev.get("title"),
                ev.get("description"),
                ev.get("link"),
                bool(ev.get("closed")),
                event_date,
                geom_wkt,
                source_name,
            ),
        )
        inserted += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="eonet",
        description="NASA EONET yangın olaylarını yükler",
    )
    p.add_argument("--days", type=int, default=30, help="Kağit geriye doğru arama aralığı (gün)")
    p.add_argument(
        "--category", default="Wildfires", help="EONET kategori filtresi (varsayılan: Wildfires)"
    )
    args = p.parse_args(argv)

    end = date.today()
    start = end - timedelta(days=args.days)
    settings = get_settings()

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        n = ingest_eonet(conn, start, end, args.category)
        print(f"{n} EONET olayı yüklendi ({start} -> {end}, kategori: {args.category})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
