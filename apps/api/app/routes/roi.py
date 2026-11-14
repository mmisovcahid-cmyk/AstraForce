"""Kullanıcı bölgeleri: çizilen çokgen, GeoJSON yükleme ya da enlem/boylam + yarıçap."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.areas import AreaError, compute_roi, create_roi, retry_roi, roi_info
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
    """Bekleyen ya da sahipsiz kalmış bölgeyi arka planda hesaplatır.

    Asıl sahiplenme compute_roi içinde veritabanında atomik yapılır; aynı anda gelen yoklamalar
    ya da birden çok worker aynı bölgeyi iki kez hesaplamaz. 'error' burada yeniden denenmez:
    kullanıcı POST /roi/{id}/retry ile ister.
    """
    if info["status"] == "pending" or info.get("stale"):
        # Durum olduğu gibi döner: sıra doluysa bölge 'pending' kalır, sonraki yoklamada dener
        background.add_task(compute_roi, get_pool(), info["id"])
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
    # Harmonizasyon yenilendiyse (status=pending) ya da hesaplayan worker düştüyse yeniden hesapla
    return _schedule_if_needed(info, background)


@router.post("/{rid}/retry")
def retry(rid: str, background: BackgroundTasks) -> dict:
    """Hata vermiş bölgenin hesaplamasını yeniden başlatır."""
    with get_pool().connection() as conn:
        try:
            retry_roi(conn, rid.lower())
            info = roi_info(conn, rid.lower())
        except AreaError as e:
            raise HTTPException(404, str(e)) from e
    return _schedule_if_needed(info, background)
