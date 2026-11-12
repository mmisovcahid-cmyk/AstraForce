"""Kullanıcı bölgeleri: çizilen çokgen, GeoJSON yükleme ya da enlem/boylam + yarıçap."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.areas import AreaError, compute_roi, create_roi, roi_info
from app.db import get_pool

router = APIRouter(prefix="/roi")


class Circle(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(ge=0.5, le=1000)


class RoiIn(BaseModel):
    geojson: dict[str, Any] | None = None
    circle: Circle | None = None
    name: str | None = Field(default=None, max_length=120)


def _schedule_if_needed(info: dict, background: BackgroundTasks) -> dict:
    if info["status"] in ("pending", "error"):
        background.add_task(compute_roi, get_pool(), info["id"])
        info = {**info, "status": "running" if info["status"] == "pending" else info["status"]}
    return info


@router.post("")
def create(body: RoiIn, background: BackgroundTasks) -> dict:
    """Bölgeyi kaydeder ve günlük harmonize serisini arka planda hesaplamaya başlar.

    Aynı geometri aynı kimliği alır; daha önce hesaplandıysa sonuç hemen hazırdır.
    """
    if (body.geojson is None) == (body.circle is None):
        raise HTTPException(400, "geojson ya da circle'dan tam olarak biri gerekli")
    circle = (body.circle.lat, body.circle.lon, body.circle.radius_km) if body.circle else None
    with get_pool().connection() as conn:
        try:
            info = create_roi(conn, geojson=body.geojson, circle=circle, name=body.name)
        except AreaError as e:
            raise HTTPException(400, str(e)) from e
    return _schedule_if_needed(info, background)


@router.get("/{rid}")
def get(rid: str, background: BackgroundTasks) -> dict:
    """Bölge bilgisi, geometrisi ve hesaplama durumu (status, progress)."""
    with get_pool().connection() as conn:
        try:
            info = roi_info(conn, rid.lower())
        except AreaError as e:
            raise HTTPException(404, str(e)) from e
    # Harmonizasyon yenilendiyse (status=pending) ya da önceki deneme hata verdiyse yeniden hesapla
    return _schedule_if_needed(info, background)
