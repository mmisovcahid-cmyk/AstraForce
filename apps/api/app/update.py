"""Günlük otomatik güncelleme: yeni FIRMS verisini çeker ve harmonizasyonu yeniler.

  python -m app.update                  # günlük: bu yılın SP/NRT verisi + olaylar + kalibrasyon
  python -m app.update --bootstrap      # boş veritabanı: sınırlar + 25 yıllık arşiv + her şey
  python -m app.update --country TR,AZ  # yalnızca bazı ülkeler

Render'da Cron Job olarak (render.yaml), yerelde `pnpm update:daily` ile çalışır.
Her çalıştırma update_run tablosuna yazılır; arayüz "son güncelleme" bilgisini oradan alır.
Pazartesileri sabit kaynak maskesi de yeniden hesaplanır (yeni NRT verisiyle değişebilir).
"""

import argparse
import sys
import time
from datetime import date

import psycopg

from app.config import get_settings
from app.harmonize.__main__ import main as harmonize_main
from app.ingest.__main__ import main as ingest_main
from app.ingest.sources import COUNTRIES
from app.optimize import main as optimize_main


def _log(conn: psycopg.Connection, run_id: int, status: str, detail: str) -> None:
    conn.execute(
        "UPDATE update_run SET status = %s, detail = %s, finished_at = now() WHERE id = %s",
        (status, detail[:2000], run_id),
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        prog="update", description="Günlük veri + harmonizasyon güncellemesi"
    )
    p.add_argument("--country", default=",".join(COUNTRIES), help="varsayılan: tüm ülkeler")
    p.add_argument("--bootstrap", action="store_true", help="boş veritabanını baştan doldur")
    args = p.parse_args(argv)
    countries = args.country

    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        run_id = conn.execute(
            "INSERT INTO update_run (countries) VALUES (%s) RETURNING id",
            ([c.strip().upper() for c in countries.replace(" ", ",").split(",") if c.strip()],),
        ).fetchone()[0]

        t0 = time.perf_counter()
        steps: list[tuple[str, list[str], object]] = []
        if args.bootstrap:
            steps.append(("ingest all", ["all", "--country", countries], ingest_main))
            steps.append(("harmonize", ["run", "--country", countries], harmonize_main))
            steps.append(("optimize", [], lambda _args: optimize_main()))
        else:
            today = date.today()
            # Bu yılın başından: SP pencereleri kayıtlıysa atlanır, NRT her seferinde tazelenir.
            # Ocak ayında geçen yılın sonu henüz SP olmayabilir → 1 Aralık'tan başla.
            start = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, 1, 1)
            steps.append(
                (
                    "ingest api",
                    ["api", "--country", countries, "--from", start.isoformat()],
                    ingest_main,
                )
            )
            harm_steps = "mask,events,calibrate" if today.weekday() == 0 else "events,calibrate"
            steps.append(
                (
                    "harmonize",
                    ["run", "--country", countries, "--steps", harm_steps],
                    harmonize_main,
                )
            )

        for name, step_args, fn in steps:
            print(f"\n=== {name}: {' '.join(step_args)}", flush=True)
            code = fn(step_args)  # type: ignore[operator]
            if code != 0:
                _log(conn, run_id, "error", f"{name} çıkış kodu {code}")
                print(f"Hata: {name} başarısız (çıkış kodu {code})", file=sys.stderr)
                return code
        elapsed = time.perf_counter() - t0
        _log(conn, run_id, "ok", f"{len(steps)} adım, {elapsed:.0f} sn")
        print(f"\nGüncelleme tamam ({elapsed / 60:.1f} dk)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
