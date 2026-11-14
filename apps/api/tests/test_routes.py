"""Rota davranışları: önbellek, dışa aktarma sınırları, ROI yeniden deneme."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.routes import data


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_data_status_is_cached(monkeypatch, client):
    calls = []
    monkeypatch.setattr(data, "_status_cache", None)
    monkeypatch.setattr(data, "_load_status", lambda: calls.append(1) or {"rows": []})
    assert client.get("/data/status").json() == {"rows": []}
    assert client.get("/data/status").json() == {"rows": []}
    assert calls == [1]


@pytest.fixture
def db_client(client):
    if client.get("/health").json()["status"] != "ok":
        pytest.skip("PostGIS çalışmıyor")
    return client


@pytest.mark.db
def test_unknown_roi_export_and_retry_return_404(db_client):
    res = db_client.get(
        "/export/hotspots.csv",
        params={"area": "roi:000000000000", "date_from": "2024-01-01", "date_to": "2024-01-02"},
    )
    assert res.status_code == 404
    assert db_client.post("/roi/000000000000/retry").status_code == 404


@pytest.mark.db
def test_country_export_streams_csv_with_row_limit_header(db_client):
    res = db_client.get(
        "/export/hotspots.csv",
        params={"area": "AZ", "date_from": "2024-08-01", "date_to": "2024-08-02"},
    )
    assert res.status_code == 200 and res.headers["x-row-limit"] == "2000000"
    assert res.text.startswith("date,time_utc,latitude")
