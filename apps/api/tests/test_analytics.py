from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analytics import (
    anomaly_class,
    anomaly_pct,
    climatology,
    current_status,
    full_series,
    levels,
    month_matrix,
    season_dates,
    thresholds,
    trend,
)


def test_levels_zero_only_for_no_fire_and_capped_at_four():
    th = [2.0, 6.0, 15.0]
    assert list(levels([0, 0.5, 2.0, 2.1, 6.5, 15.0, 999], th)) == [0, 1, 1, 2, 3, 3, 4]


def test_full_series_fills_missing_days_with_zero():
    s = pd.Series([5.0], index=[date(2024, 2, 28)])
    out = full_series(s, date(2024, 2, 27), date(2024, 3, 1))
    assert list(out) == [0.0, 5.0, 0.0, 0.0]  # 29 Şubat dahil


def test_season_dates_and_peak_week():
    idx = pd.date_range("2021-01-01", "2021-12-31", freq="D")
    s = pd.Series(0.0, index=idx)
    s["2021-07-28":"2021-08-03"] = 100.0  # tek büyük yangın haftası
    s["2021-04-10"] = 10.0
    info = season_dates(s)
    assert info["peak_week_start"] == "2021-07-28"
    assert info["start"] <= info["mid"] <= info["end"]
    assert info["mid"].startswith("2021-07") or info["mid"].startswith("2021-08")
    assert season_dates(pd.Series(0.0, index=idx))["start"] is None


def test_trend_detects_increase_and_flat():
    years = list(range(2001, 2026))
    rising = trend(years, [100 + 5 * i for i in range(len(years))])
    assert rising["slope_per_year"] == pytest.approx(5.0)
    assert rising["p_value"] < 0.001 and rising["pct_per_decade"] > 0
    rng = np.random.default_rng(1)
    flat = trend(years, list(100 + rng.normal(0, 5, len(years))))
    assert flat["p_value"] > 0.05
    assert trend([2020, 2021], [1.0, 2.0]) is None


def test_climatology_covers_leap_day_and_band_contains_mean():
    s = pd.Series(1.0, index=pd.date_range("2020-01-01", "2023-12-31", freq="D"))
    clim = climatology(s, [2020, 2021, 2022, 2023])
    assert len(clim) == 366
    assert all(c["p10"] <= c["mean"] <= c["p90"] for c in clim)


def test_thresholds_use_only_complete_base_years():
    idx = pd.date_range("2001-01-01", "2026-06-30", freq="D")
    s = pd.Series(0.0, index=idx)
    s["2010-07-01":"2010-07-10"] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    s["2026-06-01"] = 1000.0  # içinde bulunulan yıl eşiklere girmemeli
    th = thresholds(s, today=date(2026, 6, 30))
    assert th[0] == pytest.approx(5.5) and th[-1] < 1000


def _monthly_series():
    idx = pd.date_range("2000-11-01", "2026-03-15", freq="D")
    s = pd.Series(0.0, index=idx)
    for y in range(2001, 2026):
        s[f"{y}-08-01" : f"{y}-08-10"] = 1.0  # her Ağustos 10 sıcak nokta
        s[f"{y}-03-01" : f"{y}-03-15"] = 1.0  # her Mart ilk 15 gün
    s["2024-08-01":"2024-08-30"] = 1.0  # 2024 Ağustos: 30 (medyanın 3 katı)
    s["2026-03-01":"2026-03-15"] = 2.0  # bu ay şimdiye kadar medyanın 2 katı
    return s


def test_month_matrix_anomaly_against_median_and_partial_month():
    m = month_matrix(_monthly_series(), date(2000, 11, 1), today=date(2026, 3, 15))
    by = {(c["year"], c["month"]): c for c in m["cells"]}
    assert m["monthly_median"][7] == 10.0
    aug24 = by[(2024, 8)]
    assert aug24["value"] == 30.0 and aug24["anomaly_pct"] == 200.0
    assert aug24["anomaly_class"] == "much_above"
    mar26 = by[(2026, 3)]
    assert mar26["partial"] and mar26["median"] == 15.0 and mar26["anomaly_pct"] == 100.0
    assert (2026, 4) not in by and (2000, 10) not in by
    assert {c["level"] for c in m["cells"]} <= {0, 1, 2, 3, 4}


def test_current_status_month_to_date_and_last7():
    st = current_status(_monthly_series(), today=date(2026, 3, 15))
    assert st["month_to_date"] == 30.0 and st["month_to_date_median"] == 15.0
    assert st["month_anomaly_pct"] == 100.0 and st["month_anomaly_class"] == "above"
    assert st["last7"] == 14.0 and st["last7_median"] == 7.0


def test_anomaly_class_when_median_is_zero():
    assert anomaly_class(None, 0.0, 0.0) == "normal"
    assert anomaly_class(None, 3.0, 0.0) == "much_above"
    assert anomaly_pct(0.0, 0.2) is None  # küçük medyanda yüzde yok
    assert anomaly_class(None, 1.0, 0.2) == "normal"
    assert anomaly_class(anomaly_pct(80, 100), 80, 100) == "below"


def _stub_series(monkeypatch, as_of: date):
    """Her gün 10 sıcak noktalı sentetik seri; veri as_of'ta bitiyor (FIRMS gecikmesi)."""
    from app.routes import analytics as routes

    idx = pd.date_range("2000-11-01", as_of, freq="D")
    df = pd.DataFrame(
        {"hotspots": 10.0, "events": 1.0, "frp": 5.0, "provisional": False}, index=idx
    )
    monkeypatch.setattr(routes, "load_series", lambda area: (df, as_of))


@pytest.fixture
def stub_client():
    from app import main

    with TestClient(main.app) as c:
        yield c


def test_status_is_measured_at_last_data_day_not_today(monkeypatch, stub_client):
    # Veri 12 Kasım'da bitiyor: son 7 gün ve ay başından beri, eksik günler sayılmadan normal çıkmalı
    _stub_series(monkeypatch, date(2026, 11, 12))
    body = stub_client.get("/analytics/status", params={"area": "TR"}).json()
    assert body["as_of"] == body["latest_data_day"] == "2026-11-12"
    assert body["month_to_date"] == body["month_to_date_median"] == 120.0
    assert body["month_anomaly_pct"] == 0.0 and body["last7_anomaly_pct"] == 0.0


def test_range_ignores_days_without_data_yet(monkeypatch, stub_client):
    _stub_series(monkeypatch, date(2026, 11, 12))
    body = stub_client.get(
        "/analytics/range",
        params={"area": "TR", "date_from": "2026-11-08", "date_to": "2026-11-14"},
    ).json()
    assert body["effective_date_to"] == "2026-11-12"
    assert body["total"] == body["median"] == 50.0 and body["anomaly_pct"] == 0.0

    future = stub_client.get(
        "/analytics/range",
        params={"area": "TR", "date_from": "2026-11-13", "date_to": "2026-11-14"},
    ).json()
    assert future["effective_date_to"] is None and future["total"] is None


@pytest.fixture
def client():
    from app import main

    with TestClient(main.app) as c:
        if c.get("/health").json()["status"] != "ok":
            pytest.skip("PostGIS çalışmıyor")
        yield c


@pytest.mark.db
def test_calendar_endpoint_shape(client):
    res = client.get("/analytics/calendar", params={"area": "AZ", "year": 2024})
    if res.status_code == 404:
        pytest.skip("AZ harmonize edilmemiş")
    body = res.json()
    assert len(body["days"]) == 366 and set(body["thresholds"]) == {"hotspots", "events", "frp"}
    assert {d["level_hotspots"] for d in body["days"]} <= {0, 1, 2, 3, 4}


@pytest.mark.db
def test_unknown_area_is_rejected(client):
    assert client.get("/analytics/calendar", params={"area": "XX", "year": 2024}).status_code == 400
    assert client.get("/analytics/matrix", params={"area": "roi:../x"}).status_code == 400
