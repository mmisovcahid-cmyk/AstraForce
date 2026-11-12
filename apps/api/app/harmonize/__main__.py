"""Harmonizasyon aracı.

pnpm harmonize run --country AZ,TR            # maske + olaylar + kalibrasyon + HFI
pnpm harmonize run --country TR --steps calibrate
pnpm harmonize status
"""

import argparse
import sys
import time

import psycopg

from app.config import get_settings
from app.harmonize.apply import run_calibration
from app.harmonize.events import build_events
from app.harmonize.mask import build_static_mask
from app.harmonize.settings import ALL_SOURCES, HFI_VERSION
from app.ingest.sources import parse_countries

STEPS = ("mask", "events", "calibrate")
TARGET_LABELS = {"evt": "olay-gün", "det": "sıcak nokta sayısı"}
LOCK_ID = 0x48464931  # "HFI1"


def _status(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        SELECT country, target, method, selected,
               metrics->>'mean_abs_annual_bias_pct', metrics->>'daily_r', metrics->>'weekly_r',
               metrics->>'mean_season_shift_days'
        FROM calibration_model ORDER BY country, target, selected DESC, method
        """
    ).fetchall()
    if not rows:
        print("Henüz harmonizasyon yok. Örnek: pnpm harmonize run --country AZ")
        return
    print(
        f"{'ülke':4} {'hedef':5} {'yöntem':14} {'seçili':6} {'|yıllık sapma| %':>16}"
        f" {'günlük r':>9} {'haftalık r':>10} {'sezon kayması (gün)':>18}"
    )
    for c, tg, m, sel, bias, r, wr, shift in rows:
        print(
            f"{c:4} {tg:5} {m:14} {'✔' if sel else '':6} {bias:>16} {r:>9} {wr:>10}"
            f" {shift or '–':>18}"
        )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="harmonize", description="MODIS/VIIRS harmonizasyonu")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--country", required=True)
    run.add_argument("--steps", default=",".join(STEPS), help=f"varsayılan: {','.join(STEPS)}")
    sub.add_parser("status")
    args = p.parse_args(argv)

    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        if args.cmd == "status":
            _status(conn)
            return 0
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
            print("Başka bir harmonizasyon zaten çalışıyor.", file=sys.stderr)
            return 3
        try:
            countries = parse_countries(args.country)
        except ValueError as e:
            print(f"Hata: {e}", file=sys.stderr)
            return 2
        steps = [s for s in STEPS if s in args.steps.replace(" ", ",").split(",")]

        if "mask" in steps:
            t = time.perf_counter()
            mask = build_static_mask(conn)
            print(f"Sabit kaynak maskesi: {mask} ({time.perf_counter() - t:.0f} sn)", flush=True)
        for country in countries:
            if "events" in steps:
                for source in ALL_SOURCES:
                    t = time.perf_counter()
                    r = build_events(conn, country.iso2, source)
                    print(
                        f"[{country.iso2}] {source}: {r['detections']:,} tespit →"
                        f" {r['events']:,} olay, {r['cell_days']:,} hücre-gün"
                        f" ({time.perf_counter() - t:.0f} sn)",
                        flush=True,
                    )
            if "calibrate" in steps:
                t = time.perf_counter()
                r = run_calibration(conn, country.iso2)
                print(
                    f"[{country.iso2}] kalibrasyon ({HFI_VERSION}), Terra katsayısı"
                    f" {r['terra_factor']}, {r['cell_days']:,} HFI hücre-günü"
                    f" ({time.perf_counter() - t:.0f} sn)",
                    flush=True,
                )
                for target, by_method in r["metrics"].items():
                    print(f"   hedef: {TARGET_LABELS[target]}", flush=True)
                    for name, met in by_method.items():
                        mark = "✔" if name == r["selected"][target] else " "
                        print(
                            f"   {mark} {name:14}"
                            f" |yıllık sapma| {met['mean_abs_annual_bias_pct']:6}%"
                            f"  günlük r {met['daily_r']}  haftalık r {met['weekly_r']}"
                            f"  sezon kayması {met['mean_season_shift_days']} gün",
                            flush=True,
                        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
