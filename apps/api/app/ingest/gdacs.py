"""GDACS (Global Disaster Alert and Coordination System) uyarı yükleyici.

GDACS: https://www.gdacs.org/ (XML/RSS feed)
Yangın (Vegetation Fire) uyarılarını filtreleyip `gdacs_alerts` tablosuna yazar.
Kimlik gerektirmeyen açık kaynaktır.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

import httpx
import psycopg

from app.config import get_settings

GDACS_RSS = "https://www.gdacs.org/XML/rss.xml"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def fetch_gdacs_alerts(
    start: date, end: date, event_type: str | None = "VF"
) -> list[dict[str, Any]]:
    """GDACS RSS feed'inden belirli tarih aralığındaki uyarıları çeker."""
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(GDACS_RSS)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! GDACS çekme hatası: {exc}", file=sys.stderr)
        return []

    items = root.findall(".//item")
    results: list[dict[str, Any]] = []
    for item in items:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_date_el = item.find("pubDate")
        guid_el = item.find("guid")

        eventid = guid_el.text.strip() if guid_el is not None and guid_el.text else ""
        if not eventid:
            eventid = (link_el.text.strip() if link_el is not None and link_el.text else "")

        # GDACS özel alanları: eventtype, alertlevel, countryname, iso3, fromdate, todate
        pub_date_text = pub_date_el.text.strip() if pub_date_el and pub_date_el.text else ""
        pub_date = _parse_date(pub_date_text)
        if pub_date and (pub_date < start or pub_date > end):
            continue

        # Basit coğrafya: GDACS RSS'te genellikle koordinat yok; boş bırakıyoruz.
        eventname = title_el.text.strip() if title_el is not None and title_el.text else ""
        results.append(
            {
                "eventid": eventid,
                "eventname": eventname,
                "countryname": None,
                "iso3": None,
                "eventtype": event_type,
                "alertlevel": None,
                "fromdate": pub_date,
                "todate": pub_date,
                "geometry_wkt": None,
                "source": "gdacs",
            }
        )
    return results


def ingest_gdacs(
    conn: psycopg.Connection,
    start: date,
    end: date,
    event_type: str | None = "VF",
    force: bool = False,
) -> int:
    """GDACS uyarılarını `gdacs_alerts` tablosuna yazar. Eklenen kayıt sayısını döner."""
    alerts = fetch_gdacs_alerts(start, end, event_type)
    inserted = 0
    for al in alerts:
        conn.execute(
            """
            INSERT INTO gdacs_alerts
                (eventid, eventname, countryname, iso3, eventtype, alertlevel,
                 fromdate, todate, geometry, source, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::geometry, %s, now())
            ON CONFLICT (eventid) DO UPDATE
                SET eventname = EXCLUDED.eventname,
                    countryname = EXCLUDED.countryname,
                    iso3 = EXCLUDED.iso3,
                    eventtype = EXCLUDED.eventtype,
                    alertlevel = EXCLUDED.alertlevel,
                    fromdate = EXCLUDED.fromdate,
                    todate = EXCLUDED.todate,
                    geometry = EXCLUDED.geometry,
                    source = EXCLUDED.source,
                    updated_at = now()
            """,
            (
                al["eventid"],
                al["eventname"],
                al["countryname"],
                al["iso3"],
                al["eventtype"],
                al["alertlevel"],
                al["fromdate"],
                al["todate"],
                al["geometry_wkt"],
                al["source"],
            ),
        )
        inserted += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="gdacs",
        description="GDACS afet uyarılarını yükler",
    )
    p.add_argument("--days", type=int, default=30, help="Geri dönük arama aralığı (gün)")
    p.add_argument(
        "--event-type",
        default="VF",
        help="GDACS event tür filtresi (varsayılan: VF = Vegetation Fire)",
    )
    args = p.parse_args(argv)

    end = date.today()
    start = end - timedelta(days=args.days)
    settings = get_settings()

    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        n = ingest_gdacs(conn, start, end, args.event_type)
        print(f"{n} GDACS uyarısı yüklendi ({start} -> {end}, tür: {args.event_type})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
