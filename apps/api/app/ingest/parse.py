"""FIRMS CSV satırlarını fire_detection formatına çevirir.

MODIS ve VIIRS CSV'leri aynı sütun sırasına sahiptir ama bazı sütun adları farklıdır
(brightness/bright_ti4, bright_t31/bright_ti5). NRT API çıktısında `type` sütunu yoktur
ve acq_time başındaki sıfırlar olmadan gelebilir ("944" = 09:44).
"""

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

# load.py'deki staging tablosunun sütun sırası ile aynı olmalı.
STAGE_COLUMNS = (
    "source",
    "product",
    "country",
    "acq_ts",
    "lat",
    "lon",
    "bright_main",
    "bright_aux",
    "scan",
    "track",
    "frp",
    "confidence_raw",
    "confidence_level",
    "daynight",
    "fire_type",
    "satellite",
    "version",
)

_VIIRS_LEVELS = {"l": 0, "low": 0, "n": 1, "nominal": 1, "h": 2, "high": 2}


def confidence_level(raw: str) -> int:
    """MODIS 0-100 yüzdesini veya VIIRS l/n/h değerini 0/1/2 düzeyine çevirir.

    MODIS eşikleri FIRMS belgelerinden: 0-29 düşük, 30-79 nominal, 80-100 yüksek.
    """
    value = raw.strip().lower()
    if value in _VIIRS_LEVELS:
        return _VIIRS_LEVELS[value]
    pct = int(float(value))
    if pct < 30:
        return 0
    if pct < 80:
        return 1
    return 2


def parse_acq_ts(acq_date: str, acq_time: str) -> datetime:
    hhmm = acq_time.strip().zfill(4)
    return datetime.strptime(f"{acq_date.strip()} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=UTC)


def _num(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    return int(float(value))


def normalize(row: dict[str, str], source: str, product: str, country: str) -> tuple:
    """Tek CSV satırını STAGE_COLUMNS sırasında bir demete çevirir. Hatalı satırda ValueError."""
    raw_conf = row["confidence"]
    return (
        source,
        product,
        country,
        parse_acq_ts(row["acq_date"], row["acq_time"]),
        float(row["latitude"]),
        float(row["longitude"]),
        _num(row.get("brightness") or row.get("bright_ti4")),
        _num(row.get("bright_t31") or row.get("bright_ti5")),
        _num(row.get("scan")),
        _num(row.get("track")),
        _num(row.get("frp")),
        raw_conf.strip(),
        confidence_level(raw_conf),
        (row.get("daynight") or "").strip() or None,
        _int(row.get("type")),
        (row.get("satellite") or "").strip() or None,
        (row.get("version") or "").strip() or None,
    )


@dataclass
class ParseStats:
    read: int = 0
    skipped: int = 0


def iter_rows(
    lines: Iterable[str], source: str, product: str, country: str, stats: ParseStats
) -> Iterator[tuple]:
    for row in csv.DictReader(lines):
        stats.read += 1
        try:
            yield normalize(row, source, product, country)
        except (KeyError, ValueError, TypeError):
            stats.skipped += 1
