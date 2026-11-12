"""Natural Earth 10m ülke sınırlarını country_boundary tablosuna yükler (kamu malı veri)."""

import json

import httpx
import psycopg

from app.ingest.http import download
from app.ingest.load import log_ingest
from app.ingest.sources import RAW_DIR

NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_admin_0_countries.geojson"
)


def ingest_boundaries(conn: psycopg.Connection, client: httpx.Client) -> int:
    path = RAW_DIR / "boundaries" / "ne_10m_admin_0_countries.geojson"
    if not download(client, NE_URL, path):
        raise RuntimeError("Natural Earth sınır dosyası indirilemedi")
    features = json.loads(path.read_text(encoding="utf-8"))["features"]

    count = 0
    with conn.transaction():
        for feat in features:
            props = feat["properties"]
            # ISO_A2 bazı ülkelerde -99; ISO_A2_EH daha eksiksiz.
            iso2 = props.get("ISO_A2_EH") or props.get("ISO_A2")
            if not iso2 or len(iso2) != 2 or not iso2.isalpha():
                continue
            conn.execute(
                """
                INSERT INTO country_boundary (iso2, name, geom)
                VALUES (%s, %s, ST_Multi(ST_CollectionExtract(
                    ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), 3)))
                ON CONFLICT (iso2) DO UPDATE SET name = EXCLUDED.name, geom = EXCLUDED.geom
                """,
                (iso2, props.get("NAME_EN") or props.get("NAME"), json.dumps(feat["geometry"])),
            )
            count += 1
        log_ingest(
            conn,
            "boundaries:ne_10m",
            "boundaries",
            "ok",
            rows_read=len(features),
            rows_inserted=count,
        )
    return count


def has_boundaries(conn: psycopg.Connection, iso2: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM country_boundary WHERE iso2 = %s", (iso2,)).fetchone()
        is not None
    )
