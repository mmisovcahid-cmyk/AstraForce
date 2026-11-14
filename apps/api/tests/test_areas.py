"""Bölge (ROI) harmonizasyonu: saf hesap + gerçek veritabanında bölge oluşturma."""

from datetime import date

import pandas as pd
import psycopg
import pytest

from app.areas import (
    AreaError,
    _heartbeat,
    _Superseded,
    claim_roi,
    create_roi,
    harmonize_roi,
    parse_area,
    retry_roi,
    roi_info,
)
from app.config import get_settings


def test_parse_area():
    assert parse_area("tr").code == "TR"
    assert parse_area("roi:AbC123def").code == "roi:abc123def"
    for bad in ("XX", "roi:../etc", "roi:x"):
        with pytest.raises(AreaError):
            parse_area(bad)


def _factors(rows):
    return pd.DataFrame(
        rows,
        columns=["country", "day", "basis", "v_n", "f_evt", "f_det", "f_frp", "provisional"],
    )


def test_harmonize_roi_applies_country_day_factors_and_sums_countries():
    d1, d2 = date(2020, 8, 1), date(2005, 8, 1)
    raw = pd.DataFrame(
        [
            (d1, "TR", "VIIRS_SNPP", 10, 4, 100.0),
            (d1, "TR", "VIIRS_NOAA20", 6, 2, 50.0),
            (d1, "TR", "MODIS", 3, 2, 80.0),  # VIIRS gününde MODIS kullanılmaz
            (d1, "AZ", "VIIRS_SNPP", 4, 2, 10.0),
            (d2, "TR", "MODIS", 5, 3, 40.0),
        ],
        columns=["day", "country", "source", "det", "evt", "frp"],
    )
    factors = _factors(
        [
            ("TR", d1, "viirs_calibrated", 2, 0.5, 0.25, 1.0, False),
            ("AZ", d1, "viirs_calibrated", 1, 1.0, 0.5, 1.0, True),
            ("TR", d2, "modis", 0, 1.0, 1.0, 1.0, False),
        ]
    )
    out = harmonize_roi(raw, factors).set_index("day")
    # TR: det (10+6)/2 × 0.25 = 2 ; AZ: 4/1 × 0.5 = 2  → 4
    assert out.loc[d1, "hotspots"] == 4.0
    # TR: evt (4+2)/2 × 0.5 = 1.5 ; AZ: 2 × 1.0 = 2 → 3.5
    assert out.loc[d1, "events"] == 3.5
    assert bool(out.loc[d1, "provisional"])
    assert (out.loc[d2, "hotspots"], out.loc[d2, "modis_det"]) == (5.0, 5)
    assert harmonize_roi(None, factors).empty


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(get_settings().database_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostGIS çalışmıyor")
    with c, c.transaction(force_rollback=True):
        if not c.execute("SELECT 1 FROM country_boundary WHERE iso2 = 'TR'").fetchone():
            pytest.skip("Ülke sınırları yüklü değil")
        yield c


@pytest.mark.db
def test_create_roi_circle_is_idempotent_and_reports_coverage(conn):
    a = create_roi(conn, circle=(36.78, 31.44, 30))  # Manavgat
    b = create_roi(conn, circle=(36.78, 31.44, 30))
    assert a["id"] == b["id"] and a["countries"] == ["TR"]
    assert 2500 < a["area_km2"] < 2900  # π·30²≈2827 km² (bir kısmı denizde)
    assert 0 < a["covered_pct"] < 100


@pytest.mark.db
def test_create_roi_rejects_bad_input(conn):
    with pytest.raises(AreaError):
        create_roi(conn, circle=(0.0, -30.0, 50))  # Atlantik: veri yok
    with pytest.raises(AreaError):
        create_roi(conn, geojson={"type": "Point", "coordinates": [30, 40]})
    poly = {"type": "Polygon", "coordinates": [[[30, 38], [33, 38], [33, 40], [30, 40], [30, 38]]]}
    roi = create_roi(conn, geojson={"type": "Feature", "geometry": poly})
    assert roi["countries"] == ["TR"] and roi["covered_pct"] == 100.0


def _fresh_roi(conn, lon: float = 35.0) -> str:
    rid = create_roi(conn, circle=(39.0, lon, 12.3))["id"]  # İç Anadolu
    conn.execute("UPDATE roi SET status = 'pending', heartbeat_at = NULL WHERE id = %s", (rid,))
    return rid


@pytest.mark.db
def test_roi_claim_is_exclusive_until_heartbeat_goes_stale(conn):
    rid = _fresh_roi(conn)
    assert claim_roi(conn, rid) is True
    assert claim_roi(conn, rid) is False  # ikinci worker / yoklama aynı işi almaz
    assert roi_info(conn, rid)["stale"] is False
    # Hesaplayan worker düştü: heartbeat eskidi → devralınabilir
    conn.execute("UPDATE roi SET heartbeat_at = now() - interval '1 hour' WHERE id = %s", (rid,))
    assert roi_info(conn, rid)["stale"] is True
    assert claim_roi(conn, rid) is True


@pytest.mark.db
def test_roi_computations_are_capped(conn):
    conn.execute("UPDATE roi SET status = 'ready' WHERE status = 'running'")  # temiz başlangıç
    ids = [_fresh_roi(conn, lon) for lon in (34.0, 35.0, 36.0)]
    assert [claim_roi(conn, r) for r in ids] == [True, True, False]  # MAX_CONCURRENT_ROI = 2
    assert roi_info(conn, ids[2])["status"] == "pending"  # sırada bekler
    conn.execute("UPDATE roi SET status = 'ready' WHERE id = %s", (ids[0],))
    assert claim_roi(conn, ids[2]) is True


@pytest.mark.db
def test_roi_error_is_not_retried_automatically(conn):
    rid = _fresh_roi(conn)
    conn.execute("UPDATE roi SET status = 'error', error = 'x' WHERE id = %s", (rid,))
    assert claim_roi(conn, rid) is False
    assert retry_roi(conn, rid) is True and roi_info(conn, rid)["status"] == "pending"
    assert claim_roi(conn, rid) is True


@pytest.mark.db
def test_roi_computation_is_dropped_when_harmonization_resets_it(conn):
    rid = _fresh_roi(conn)
    assert claim_roi(conn, rid)
    _heartbeat(conn, rid, 10.0)
    # harmonize run (apply.py) bölgeyi yeniden kuyruğa aldı
    conn.execute("UPDATE roi SET status = 'pending' WHERE id = %s", (rid,))
    with pytest.raises(_Superseded):
        _heartbeat(conn, rid, 20.0)
    assert roi_info(conn, rid)["status"] == "pending"
