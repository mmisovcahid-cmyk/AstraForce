from fastapi.testclient import TestClient

from app import main


def test_health_ok_when_database_reachable(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda: {"ok": True, "postgis": "3.5", "h3": "4.2"})
    with TestClient(main.app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"]["postgis"] == "3.5"


def test_health_degraded_when_database_down(monkeypatch):
    monkeypatch.setattr(main, "check_database", lambda: {"ok": False, "error": "OperationalError"})
    with TestClient(main.app) as client:
        res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "degraded"


def test_cors_allows_web_origin():
    with TestClient(main.app) as client:
        res = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
