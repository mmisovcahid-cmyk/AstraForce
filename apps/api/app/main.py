from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import close_pool, get_pool, open_pool
from app.routes import analytics, data, export, harmonized, roi


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    open_pool()
    _reset_interrupted_rois()
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


def _reset_interrupted_rois() -> None:
    """Yeniden başlatmada yarıda kalan bölge hesaplamaları, bir sonraki istekte yeniden başlar."""
    try:
        with get_pool().connection() as conn:
            conn.execute("UPDATE roi SET status = 'pending' WHERE status = 'running'")
    except Exception:  # noqa: BLE001 - veritabanı kapalıysa API yine de açılmalı
        pass


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


@app.get("/health")
def health() -> dict:
    db = check_database()
    return {
        "status": "ok" if db["ok"] else "degraded",
        "database": db,
        "firms_key_configured": bool(get_settings().firms_map_key),
    }
