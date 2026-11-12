"""FIRMS area API: arşiv dosyası olmayan dönem (içinde bulunulan yıl + son günler)."""

import csv
import io
import time
from datetime import date

import httpx
import psycopg

from app.ingest.http import get_with_retry
from app.ingest.load import delete_nrt, is_done, load_rows, log_ingest
from app.ingest.parse import ParseStats, iter_rows
from app.ingest.sources import API_BASE, Country, Source, Window, plan_windows

# Limit 5000 işlem / 10 dk; büyük kutular (ABD) istek başına birden çok işlem sayılır.
REQUEST_PAUSE_S = 0.25
# Limit aşılınca: 2 dk bekle, en fazla 8 kez (toplam 16 dk > 10 dk'lık pencere)
LIMIT_WAIT_S = 120
LIMIT_RETRIES = 8


class FirmsApiError(RuntimeError):
    pass


def availability(client: httpx.Client, key: str) -> dict[str, tuple[date, date]]:
    res = get_with_retry(client, f"{API_BASE}/data_availability/csv/{key}/all")
    if res.status_code != 200 or not res.text.startswith("data_id"):
        raise FirmsApiError(f"data_availability başarısız: {res.text[:120]!r}")
    out: dict[str, tuple[date, date]] = {}
    for row in csv.DictReader(io.StringIO(res.text)):
        out[row["data_id"]] = (
            date.fromisoformat(row["min_date"]),
            date.fromisoformat(row["max_date"]),
        )
    return out


def fetch_area_csv(
    client: httpx.Client, key: str, api_source: str, bbox: tuple[float, ...], window: Window
) -> str:
    area = ",".join(f"{v:g}" for v in bbox)
    url = f"{API_BASE}/area/csv/{key}/{api_source}/{area}/{window.days}/{window.start.isoformat()}"
    for attempt in range(LIMIT_RETRIES + 1):
        res = get_with_retry(client, url)
        text = res.text
        if res.status_code == 200 and text.startswith("latitude"):
            return text
        # 10 dakikalık işlem limiti doldu: pencere boşalana kadar bekle, aynı isteği tekrarla
        if "transaction limit" in text.lower() and attempt < LIMIT_RETRIES:
            print(
                f"  FIRMS işlem limiti doldu; {LIMIT_WAIT_S // 60} dk bekleniyor"
                f" ({attempt + 1}/{LIMIT_RETRIES})…",
                flush=True,
            )
            time.sleep(LIMIT_WAIT_S)
            continue
        break
    # Hata mesajında anahtar geçmesin.
    raise FirmsApiError(f"{api_source} {window.start}: {text[:120].replace(key, '<KEY>')!r}")


def ingest_api(
    conn: psycopg.Connection,
    client: httpx.Client,
    key: str,
    country: Country,
    sources: list[Source],
    start: date,
    end: date,
    force: bool = False,
) -> None:
    avail = availability(client, key)
    for source in sources:
        windows = plan_windows(start, end, avail.get(source.api_sp), avail.get(source.api_nrt))
        for w in windows:
            api_source = source.api_sp if w.product == "SP" else source.api_nrt
            log_key = f"api:{api_source}:{country.iso2}:{w.start.isoformat()}:{w.days}"
            label = f"[{country.iso2}] {api_source} {w.start}..{w.end}"
            # NRT pencereleri her seferinde tazelenir; SP pencereleri bir kez yüklenir.
            if w.product == "SP" and not force and is_done(conn, log_key):
                continue

            stats = ParseStats()
            rows: list[tuple] = []
            for bbox in country.api_bboxes:
                text = fetch_area_csv(client, key, api_source, bbox, w)
                rows += iter_rows(io.StringIO(text), source.code, w.product, country.iso2, stats)
                time.sleep(REQUEST_PAUSE_S)

            with conn.transaction():
                removed = 0
                if w.product == "SP":
                    removed = delete_nrt(conn, source.code, country.iso2, w.start, w.end)
                inserted = load_rows(conn, rows, clip_to_country=True)
                log_ingest(
                    conn,
                    log_key,
                    "api",
                    "ok",
                    source=source.code,
                    product=w.product,
                    country=country.iso2,
                    period=(w.start, w.end),
                    rows_read=stats.read,
                    rows_inserted=inserted,
                )
            extra = f", {removed} NRT kaydı SP ile değişti" if removed else ""
            print(f"{label}: {stats.read} okundu, {inserted} yeni (ülke içi){extra}", flush=True)
