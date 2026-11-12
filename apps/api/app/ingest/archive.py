"""FIRMS yıllık ülke CSV arşivleri (anahtar gerektirmez, SP verisi)."""

from datetime import date

import httpx
import psycopg

from app.ingest.http import download
from app.ingest.load import is_done, load_rows, log_ingest
from app.ingest.parse import ParseStats, iter_rows
from app.ingest.sources import Country, Source, archive_path, archive_url


def ingest_archive(
    conn: psycopg.Connection,
    client: httpx.Client,
    country: Country,
    sources: list[Source],
    years: tuple[int, int],
    force: bool = False,
) -> None:
    for source in sources:
        if source.archive_dir is None:  # yalnızca API'den gelen kaynak (NOAA-21)
            continue
        first = max(years[0], source.archive_first_year)
        for year in range(first, years[1] + 1):
            key = f"archive:{source.code}:{country.iso2}:{year}"
            label = f"[{country.iso2}] {source.code} {year}"
            if not force and is_done(conn, key):
                print(f"{label}: zaten yüklü, atlandı", flush=True)
                continue

            path = archive_path(source, year, country)
            if not download(client, archive_url(source, year, country), path):
                with conn.transaction():
                    log_ingest(
                        conn,
                        key,
                        "archive",
                        "missing",
                        source=source.code,
                        product="SP",
                        country=country.iso2,
                    )
                print(f"{label}: NASA'da dosya yok (henüz yayınlanmamış olabilir)", flush=True)
                continue

            stats = ParseStats()
            with conn.transaction():
                with path.open(encoding="utf-8", newline="") as f:
                    inserted = load_rows(conn, iter_rows(f, source.code, "SP", country.iso2, stats))
                log_ingest(
                    conn,
                    key,
                    "archive",
                    "ok",
                    source=source.code,
                    product="SP",
                    country=country.iso2,
                    period=(date(year, 1, 1), date(year, 12, 31)),
                    rows_read=stats.read,
                    rows_inserted=inserted,
                )
            skipped = f", {stats.skipped} hatalı satır atlandı" if stats.skipped else ""
            print(f"{label}: {stats.read:,} satır okundu, {inserted:,} yeni{skipped}", flush=True)
