import io
from datetime import UTC, date, datetime

import pytest

from app.ingest.parse import STAGE_COLUMNS, ParseStats, confidence_level, iter_rows, parse_acq_ts
from app.ingest.sources import (
    COUNTRIES,
    SOURCES,
    archive_url,
    parse_countries,
    parse_sources,
    parse_years,
    plan_windows,
)

MODIS_CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type
40.5697,47.7347,338.1,1,1,2020-01-14,0959,Aqua,MODIS,91,6.03,286.3,42.5,D,0
40.5208,47.8226,304.8,4.4,1.9,2020-01-22,1048,Aqua,MODIS,29,6.03,282.7,68.6,D,2
bad,row,,,,,,,,,,,,,
"""

# NRT API çıktısı: `type` sütunu yok, acq_time baştaki sıfır olmadan.
VIIRS_NRT_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
38.61398,44.98855,330.63,0.4,0.44,2026-11-01,944,N,VIIRS,h,2.0NRT,296.29,2.76,N
"""


def _row(values: tuple) -> dict:
    return dict(zip(STAGE_COLUMNS, values, strict=True))


def test_modis_rows_are_normalized_and_bad_rows_skipped():
    stats = ParseStats()
    rows = [_row(r) for r in iter_rows(io.StringIO(MODIS_CSV), "MODIS", "SP", "AZ", stats)]
    assert (stats.read, stats.skipped, len(rows)) == (3, 1, 2)
    first = rows[0]
    assert first["acq_ts"] == datetime(2020, 1, 14, 9, 59, tzinfo=UTC)
    assert (first["lat"], first["lon"]) == (40.5697, 47.7347)
    assert (first["bright_main"], first["bright_aux"], first["frp"]) == (338.1, 286.3, 42.5)
    assert (first["confidence_raw"], first["confidence_level"]) == ("91", 2)
    assert rows[1]["confidence_level"] == 0
    assert rows[1]["fire_type"] == 2


def test_viirs_nrt_row_without_type_column():
    stats = ParseStats()
    (row,) = [
        _row(r) for r in iter_rows(io.StringIO(VIIRS_NRT_CSV), "VIIRS_SNPP", "NRT", "AZ", stats)
    ]
    assert row["acq_ts"] == datetime(2026, 11, 1, 9, 44, tzinfo=UTC)
    assert row["bright_main"] == 330.63 and row["bright_aux"] == 296.29
    assert row["confidence_level"] == 2
    assert row["fire_type"] is None
    assert row["product"] == "NRT"


@pytest.mark.parametrize(
    ("raw", "level"),
    [
        ("0", 0),
        ("29", 0),
        ("30", 1),
        ("79", 1),
        ("80", 2),
        ("100", 2),
        ("l", 0),
        ("n", 1),
        ("h", 2),
    ],
)
def test_confidence_level(raw, level):
    assert confidence_level(raw) == level


def test_acq_time_padding():
    assert parse_acq_ts("2024-03-01", "5") == datetime(2024, 3, 1, 0, 5, tzinfo=UTC)


def test_archive_url():
    url = archive_url(SOURCES["noaa20"], 2021, COUNTRIES["US"])
    assert url.endswith("/data/country/viirs-jpss1/2021/viirs-jpss1_2021_United_States.csv")


def test_list_args_accept_powershell_spaces():
    # PowerShell `--country AZ,TR,US` -> "AZ TR US"
    for raw in ("AZ,TR,US", "AZ TR US", "az, tr ,us"):
        assert [c.iso2 for c in parse_countries(raw)] == ["AZ", "TR", "US"]
    assert [s.code for s in parse_sources("modis snpp")] == ["MODIS", "VIIRS_SNPP"]
    with pytest.raises(ValueError):
        parse_countries("AZ XX")


def test_parse_years():
    assert parse_years("2010-2012") == (2010, 2012)
    assert parse_years("2015") == (2015, 2015)
    with pytest.raises(ValueError):
        parse_years("2012-2010")


def test_plan_windows_splits_sp_then_nrt_without_overlap():
    windows = plan_windows(
        date(2026, 7, 25),
        date(2026, 8, 7),
        sp_range=(date(2012, 1, 20), date(2026, 7, 31)),
        nrt_range=(date(2026, 8, 1), date(2026, 11, 12)),
    )
    assert [(w.product, w.start, w.end) for w in windows] == [
        ("SP", date(2026, 7, 25), date(2026, 7, 29)),
        ("SP", date(2026, 7, 30), date(2026, 7, 31)),
        ("NRT", date(2026, 8, 1), date(2026, 8, 5)),
        ("NRT", date(2026, 8, 6), date(2026, 8, 7)),
    ]
    assert all(1 <= w.days <= 5 for w in windows)


def test_plan_windows_respects_availability():
    assert plan_windows(date(2026, 1, 1), date(2026, 1, 3), None, None) == []
    only_nrt = plan_windows(
        date(2026, 1, 1), date(2026, 1, 3), None, (date(2026, 1, 2), date(2026, 2, 1))
    )
    assert [(w.start, w.days) for w in only_nrt] == [(date(2026, 1, 2), 2)]
