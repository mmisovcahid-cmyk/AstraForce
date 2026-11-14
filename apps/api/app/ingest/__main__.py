"""Veri yükleme aracı.

Örnekler (kökten):
  pnpm ingest all --country AZ                 # sınırlar + 2000..geçen yıl arşivi + bu yıl API
  pnpm ingest archive --country TR --years 2010-2015 --sources modis,snpp
  pnpm ingest api --country AZ --from 2026-10-01
  pnpm ingest status
"""

import argparse
import sys
from datetime import date

import psycopg

from app.config import get_settings
from app.ingest.archive import ingest_archive
from app.ingest.boundaries import has_boundaries, ingest_boundaries
from app.ingest.burned_area import ingest_burned_area
from app.ingest.firms_api import FirmsApiError, ingest_api
from app.ingest.http import make_client
from app.ingest.sources import SOURCES, parse_countries, parse_sources, parse_years

DEFAULT_SOURCES = ",".join(SOURCES)
INGEST_LOCK_ID = 0x41535452  # "ASTR": pg advisory lock anahtarı


def _build_parser() -> argparse.ArgumentParser:
    today = date.today()
    p = argparse.ArgumentParser(prog="ingest", description="NASA FIRMS verisini PostGIS'e yükler")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--country", required=True, help="AZ,TR,US (virgülle birden çok)")
        sp.add_argument("--sources", default=DEFAULT_SOURCES, help=f"varsayılan: {DEFAULT_SOURCES}")
        sp.add_argument("--force", action="store_true", help="yüklenmiş olanları da yeniden yükle")

    sub.add_parser("boundaries", help="ülke sınırlarını yükle (Natural Earth)")

    a = sub.add_parser("archive", help="yıllık ülke CSV arşivleri (SP)")
    common(a)
    a.add_argument("--years", default=f"2000-{today.year - 1}")

    api = sub.add_parser("api", help="FIRMS API: bu yıl ve son günler (SP + NRT)")
    common(api)
    api.add_argument("--from", dest="date_from", default=f"{today.year}-01-01")
    api.add_argument("--to", dest="date_to", default=today.isoformat())

    al = sub.add_parser("all", help="sınırlar + arşiv + API")
    common(al)

    sub.add_parser("status", help="yüklenen veri özeti")

    ba = sub.add_parser("burned_area", help="NASA MCD64A1 / VNP64A1 yanık alan verisi")
    common(ba)
    ba.add_argument("--year", type=int, required=True, help="Yıl (ör. 2021)")
    ba.add_argument("--month", type=int, required=True, help="Ay (1-12)")
    ba.add_argument(
        "--sensor",
        default="MODIS_MCD64A1",
        choices=["MODIS_MCD64A1", "VIIRS_VNP64A1"],
        help="Sensör ürünü (varsayılan: MODIS_MCD64A1)",
    )
    return p


def _status(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        SELECT country, source, product, count(*), min(acq_date), max(acq_date)
        FROM fire_detection GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
        """
    ).fetchall()
    if not rows:
        print("Henüz veri yok. Örnek: pnpm ingest all --country AZ")
        return
    print(f"{'ülke':4} {'kaynak':13} {'ürün':4} {'kayıt':>12}  ilk tarih    son tarih")
    for c, s, p, n, d0, d1 in rows:
        print(f"{c:4} {s:13} {p:4} {n:>12,}  {d0}  {d1}")
    errors = conn.execute(
        "SELECT key, error FROM ingest_log WHERE status = 'error' ORDER BY finished_at DESC LIMIT 5"
    ).fetchall()
    for key, err in errors:
        print(f"! hata: {key}: {err}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv)
    settings = get_settings()

    # autocommit: her `conn.transaction()` bloğu (bir dosya / bir API penceresi) ayrı commit
    # edilir; yarıda kesilen yükleme kaldığı yerden devam edebilir.
    with psycopg.connect(settings.database_url, autocommit=True) as conn, make_client() as client:
        if args.cmd == "status":
            _status(conn)
            return 0
        # Aynı anda tek yükleme: ikinci süreç aynı dosyaları indirip aynı işi tekrarlamasın.
        # Oturum düzeyinde kilit; süreç bitince/çökünce bağlantıyla birlikte bırakılır.
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (INGEST_LOCK_ID,)).fetchone()[0]:
            print(
                "Başka bir yükleme zaten çalışıyor. Bitmesini bekleyin;"
                " ilerleme için: pnpm ingest status",
                file=sys.stderr,
            )
            return 3
        if args.cmd == "boundaries":
            print(f"{ingest_boundaries(conn, client)} ülke sınırı yüklendi")
            return 0

        if args.cmd == "burned_area":
            try:
                countries = parse_countries(args.country)
            except ValueError as e:
                print(f"Hata: {e}", file=sys.stderr)
                return 2
            n = ingest_burned_area(
                conn,
                [c.iso2 for c in countries],
                args.year,
                args.month,
                args.sensor,
                args.force,
            )
            print(f"{n} yanık alan kaydı yüklendi ({args.sensor}, {args.year}-{args.month:02d})")
            return 0

        try:
            countries = parse_countries(args.country)
            sources = parse_sources(args.sources)
        except ValueError as e:
            print(f"Hata: {e}", file=sys.stderr)
            return 2

        needs_api = args.cmd in ("api", "all")
        if needs_api and not settings.firms_map_key:
            print("Hata: .env içinde FIRMS_MAP_KEY boş.", file=sys.stderr)
            return 2
        if needs_api and not all(has_boundaries(conn, c.iso2) for c in countries):
            print(f"{ingest_boundaries(conn, client)} ülke sınırı yüklendi", flush=True)

        today = date.today()
        for country in countries:
            if args.cmd in ("archive", "all"):
                years = parse_years(args.years) if args.cmd == "archive" else (2000, today.year - 1)
                ingest_archive(conn, client, country, sources, years, args.force)
            if needs_api:
                start = (
                    date.fromisoformat(args.date_from)
                    if args.cmd == "api"
                    else date(today.year, 1, 1)
                )
                # Arşivi olmayan kaynaklar (NOAA-21) "all" ile ilk yılından itibaren API'den gelir
                api_only = [s for s in sources if s.archive_dir is None]
                if args.cmd == "all" and api_only:
                    try:
                        ingest_api(
                            conn,
                            client,
                            settings.firms_map_key,
                            country,
                            api_only,
                            date(min(s.archive_first_year for s in api_only), 1, 1),
                            date(today.year - 1, 12, 31),
                            args.force,
                        )
                    except FirmsApiError as e:
                        print(f"Hata (FIRMS API): {e}", file=sys.stderr)
                        return 1
                end = date.fromisoformat(args.date_to) if args.cmd == "api" else today
                try:
                    ingest_api(
                        conn,
                        client,
                        settings.firms_map_key,
                        country,
                        sources,
                        start,
                        end,
                        args.force,
                    )
                except FirmsApiError as e:
                    print(f"Hata (FIRMS API): {e}", file=sys.stderr)
                    return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
