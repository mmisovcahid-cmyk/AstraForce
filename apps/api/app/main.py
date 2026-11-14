from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import close_pool, get_pool, open_pool
from app.routes import (
    analytics,
    burned_area,
    data,
    emergency,
    export,
    harmonized,
    roi,
    static_sources,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Yarıda kalan ROI hesaplamaları açılışta sıfırlanmaz (birden çok worker varken diğerinin
    # sürmekte olan işini bozardı); heartbeat'i eskiyen bölge sonraki istekte devralınır.
    open_pool()
    yield
    close_pool()


app = FastAPI(title="AstraForce API", version="0.5.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(data.router)
app.include_router(harmonized.router)
app.include_router(analytics.router)
app.include_router(roi.router)
app.include_router(export.router)
app.include_router(static_sources.router)
app.include_router(burned_area.router)
app.include_router(emergency.router)


def check_database() -> dict:
    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                "SELECT postgis_lib_version(),"
                " (SELECT extversion FROM pg_extension WHERE extname = 'h3')"
            ).fetchone()
        return {"ok": True, "postgis": row[0], "h3": row[1]}
    except Exception as exc:  # noqa: BLE001 - sağlık kontrolü hatayı raporlar, fırlatmaz
        return {"ok": False, "error": type(exc).__name__}


def last_update() -> dict | None:
    """Son başarılı otomatik güncelleme ve en yeni veri günü (arayüz alt bilgisi için)."""
    try:
        with get_pool().connection() as conn:
            row = conn.execute(
                """
                SELECT (SELECT max(finished_at) FROM update_run WHERE status = 'ok'),
                       (SELECT max(day) FROM harmonized_factor)
                """
            ).fetchone()
        return {
            "finished_at": row[0].isoformat() if row[0] else None,
            "latest_data_day": row[1].isoformat() if row[1] else None,
        }
    except Exception:  # noqa: BLE001 - sağlık kontrolü hata fırlatmaz
        return None


@app.get("/health")
def health() -> dict:
    db = check_database()
    return {
        "status": "ok" if db["ok"] else "degraded",
        "database": db,
        "firms_key_configured": bool(get_settings().firms_map_key),
        "last_update": last_update() if db["ok"] else None,
    }
