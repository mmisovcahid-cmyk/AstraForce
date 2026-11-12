"""Gerçek PostGIS'e karşı yükleme testleri. Her test kendi transaction'ında çalışır ve geri alınır."""

import io
from datetime import date

import psycopg
import pytest

from app.config import get_settings
from app.ingest.load import delete_nrt, load_rows
from app.ingest.parse import ParseStats, iter_rows

pytestmark = pytest.mark.db

CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight,type
40.19473,49.462,338.08,0.36,0.57,1999-01-01,1023,N,VIIRS,n,2,279.69,4.21,D,0
40.19724,49.46228,344.28,0.36,0.58,1999-01-01,1023,N,VIIRS,n,2,279.47,3.65,D,2
"""


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(get_settings().database_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostGIS çalışmıyor (pnpm db:up)")
    with c, c.transaction(force_rollback=True):
        yield c


def _rows(product: str = "SP"):
    return iter_rows(io.StringIO(CSV), "TEST_SRC", product, "AZ", ParseStats())


def test_loading_same_rows_twice_inserts_once(conn):
    assert load_rows(conn, _rows()) == 2
    assert load_rows(conn, _rows()) == 0
    h3, d = conn.execute(
        "SELECT h3_get_resolution(h3_r8), acq_date FROM fire_detection WHERE source = 'TEST_SRC'"
        " LIMIT 1"
    ).fetchone()
    assert (h3, d) == (8, date(1999, 1, 1))


def test_delete_nrt_only_touches_nrt_rows(conn):
    load_rows(conn, _rows("NRT"))
    assert delete_nrt(conn, "TEST_SRC", "AZ", date(1999, 1, 1), date(1999, 1, 1)) == 2
    assert delete_nrt(conn, "TEST_SRC", "AZ", date(1999, 1, 1), date(1999, 1, 1)) == 0


def test_clip_drops_points_outside_country(conn):
    if not conn.execute("SELECT 1 FROM country_boundary WHERE iso2 = 'AZ'").fetchone():
        pytest.skip("Ülke sınırları yüklü değil (pnpm ingest boundaries)")
    outside = CSV.replace("40.19473,49.462", "0.5,0.5")  # Gine Körfezi, Azerbaycan dışı
    rows = iter_rows(io.StringIO(outside), "TEST_SRC", "SP", "AZ", ParseStats())
    assert load_rows(conn, rows, clip_to_country=True) == 1
