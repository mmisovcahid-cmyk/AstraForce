"""Günlük otomatik güncelleme: yeni FIRMS verisini çeker ve harmonizasyonu yeniler.

  python -m app.update                  # günlük: bu yılın SP/NRT verisi + olaylar + kalibrasyon
  python -m app.update --bootstrap      # boş veritabanı: sınırlar + 25 yıllık arşiv + her şey
  python -m app.update --optimize       # sonunda CLUSTER (diskte tablo kadar boş yer gerekir)
  python -m app.update --country TR,AZ  # yalnızca bazı ülkeler

Render'da Cron Job olarak (render.yaml), yerelde `pnpm update:daily` ile çalışır.
Her çalıştırma update_run tablosuna yazılır; arayüz "son güncelleme" bilgisini oradan alır.
Pazartesileri sabit kaynak maskesi de yeniden hesaplanır (yeni NRT verisiyle değişebilir).
"""

import argparse
import sys
import time
from collections.abc import Callable
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
    p.add_argument(
        "--optimize",
        action="store_true",
        help="sonunda CLUSTER çalıştır (tablo boyutu kadar ek disk ister; Render 20 GB'a sığmaz)",
    )
    args = p.parse_args(argv)
    countries = [c.strip().upper() for c in args.country.replace(" ", ",").split(",") if c.strip()]

    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        run_id = conn.execute(
            "INSERT INTO update_run (countries) VALUES (%s) RETURNING id", (countries,)
        ).fetchone()[0]
        t0 = time.perf_counter()
        try:
            failures = _run(countries, args.bootstrap, args.optimize)
        except BaseException as e:  # Ctrl+C dahil: kayıt "running"de takılı kalmasın
            _log(conn, run_id, "error", f"beklenmeyen hata: {type(e).__name__}: {e}")
            raise
        elapsed = time.perf_counter() - t0
        if failures:
            _log(conn, run_id, "error", "; ".join(failures))
            print(f"\nGüncelleme hatalarla bitti: {'; '.join(failures)}", file=sys.stderr)
            return 1
        _log(conn, run_id, "ok", f"{len(countries)} ülke, {elapsed:.0f} sn")
        print(f"\nGüncelleme tamam ({elapsed / 60:.1f} dk)", flush=True)
    return 0


StepFn = Callable[[list[str]], int]


def _step(name: str, fn: StepFn, step_args: list[str]) -> str | None:
    """Bir adımı çalıştırır; başarısızsa kısa hata metni döner (istisnalar da yakalanır)."""
    print(f"\n=== {name}: {' '.join(step_args)}", flush=True)
    try:
        code = fn(step_args)
    except Exception as e:  # noqa: BLE001 - ör. FIRMS'e ulaşılamadı (httpx hatası)
        print(f"Hata: {name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return f"{name}: {type(e).__name__}"
    if code != 0:
        print(f"Hata: {name} başarısız (çıkış kodu {code})", file=sys.stderr, flush=True)
        return f"{name}: çıkış kodu {code}"
    return None


def _run(countries: list[str], bootstrap: bool, optimize: bool) -> list[str]:
    """Adımları çalıştırır, hataları toplar.

    Ülkeler ayrı ayrı yüklenir: bir ülkenin FIRMS hatası diğerlerinin güncellenmesini
    engellemez; yalnızca verisi başarıyla gelen ülkeler harmonize edilir.
    """
    failures: list[str] = []
    today = date.today()
    if bootstrap:
        ingest_args = ["all"]
        harm_args = ["run"]
    else:
        # Bu yılın başından: SP pencereleri kayıtlıysa atlanır, NRT her seferinde tazelenir.
        # Ocak ayında geçen yılın sonu henüz SP olmayabilir → 1 Aralık'tan başla.
        start = date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, 1, 1)
        ingest_args = ["api", "--from", start.isoformat()]
        harm_steps = "mask,events,calibrate" if today.weekday() == 0 else "events,calibrate"
        harm_args = ["run", "--steps", harm_steps]

    loaded = []
    for cc in countries:
        err = _step(f"ingest {cc}", ingest_main, [*ingest_args, "--country", cc])
        if err:
            failures.append(err)
        else:
            loaded.append(cc)
    if loaded:
        err = _step("harmonize", harmonize_main, [*harm_args, "--country", ",".join(loaded)])
        if err:
            failures.append(err)
    if optimize and not failures:
        err = _step("optimize", lambda _a: optimize_main(), [])
        if err:
            failures.append(err)
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
