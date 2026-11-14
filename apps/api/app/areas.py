"""Alanlar: hazır ülkeler (ör. "TR") ve kullanıcı bölgeleri (ROI, "roi:<id>").

Her alan için aynı biçimde bir günlük harmonize seri üretilir:
    hotspots  harmonize sıcak nokta sayısı (MODIS eşdeğeri)  ← ana gösterge
    events    harmonize olay-gün
    frp       harmonize yangın gücü (MW)
Ülke serisi harmonized_daily'den, ROI serisi ROI'nin içindeki temiz tespitlerden ve
ülke × gün katsayılarından (harmonized_factor) gelir.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd
import psycopg

from app.harmonize.settings import MODIS, VIIRS_SOURCES
from app.ingest.sources import COUNTRIES

log = logging.getLogger(__name__)

FIRST_DAY = date(2000, 11, 1)
MAX_ROI_AREA_KM2 = 3_500_000  # Arjantin (~2,8 milyon km²) sığsın
MIN_ROI_AREA_KM2 = 1.0
METRICS = ("hotspots", "events", "frp")


class AreaError(ValueError):
    """Kullanıcıya gösterilecek alan hatası (HTTP 400)."""


class AreaNotReady(Exception):
    def __init__(self, status: str, progress: float):
        super().__init__(status)
        self.status, self.progress = status, progress


@dataclass(frozen=True)
class Area:
    kind: str  # "country" | "roi"
    key: str  # "TR" ya da ROI kimliği

    @property
    def code(self) -> str:
        return self.key if self.kind == "country" else f"roi:{self.key}"


def parse_area(value: str) -> Area:
    v = value.strip()
    if v.lower().startswith("roi:"):
        rid = v[4:]
        if not rid.isalnum() or not 6 <= len(rid) <= 32:
            raise AreaError("Geçersiz bölge kimliği")
        return Area("roi", rid.lower())
    code = v.upper()
    if code not in COUNTRIES:
        raise AreaError(f"Bilinmeyen alan: {v}")
    return Area("country", code)


# --------------------------------------------------------------------------- seriler


def daily_series(conn: psycopg.Connection, area: Area) -> pd.DataFrame:
    """Alanın günlük serisi (yalnızca yangınlı günler): hotspots, events, frp, provisional."""
    if area.kind == "country":
        rows = conn.execute(
            """
            SELECT day, sum(hfi_det), sum(hfi), sum(hfi_frp), bool_or(provisional)
            FROM harmonized_daily WHERE country = %s GROUP BY day
            """,
            (area.key,),
        ).fetchall()
    else:
        status, progress = roi_status(conn, area.key)
        if status != "ready":
            raise AreaNotReady(status, progress)
        rows = conn.execute(
            "SELECT day, hotspots, events, frp, provisional FROM roi_daily WHERE roi_id = %s",
            (area.key,),
        ).fetchall()
    df = pd.DataFrame(rows, columns=["day", "hotspots", "events", "frp", "provisional"])
    df.index = pd.to_datetime(df.pop("day"))
    return df.sort_index()


def data_until(conn: psycopg.Connection, area: Area) -> date | None:
    """Alanın verisinin kesin olarak bulunduğu son gün (harmonize katsayısı olan son gün).

    FIRMS verisi 1–2 gün gecikmeli gelir; bu günden sonrası "yangın yok" değil "veri yok"tur.
    ROI birden çok ülkeye düşüyorsa en geride kalan ülkenin son günü alınır.
    """
    if area.kind == "country":
        row = conn.execute(
            "SELECT max(day) FROM harmonized_factor WHERE country = %s", (area.key,)
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT min(last_day) FROM (
                SELECT max(hf.day) AS last_day FROM harmonized_factor hf
                WHERE hf.country = ANY((SELECT countries FROM roi WHERE id = %s)::char(2)[])
                GROUP BY hf.country
            ) t
            """,
            (area.key,),
        ).fetchone()
    return row[0] if row else None


def raw_counts(conn: psycopg.Connection, area: Area, first: date, last: date) -> dict:
    """Takvim ipucu için gün × kaynak temizlenmiş tespit sayıları."""
    if area.kind == "country":
        rows = conn.execute(
            """
            SELECT day, source, sum(n_det) FROM daily_cell_stats
            WHERE country = %s AND day BETWEEN %s AND %s GROUP BY 1, 2
            """,
            (area.key, first, last),
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for d, src, n in rows:
            out.setdefault(d.isoformat(), {})[src] = int(n)
        return out
    rows = conn.execute(
        """
        SELECT day, modis_det, snpp_det, noaa20_det, noaa21_det FROM roi_daily
        WHERE roi_id = %s AND day BETWEEN %s AND %s
        """,
        (area.key, first, last),
    ).fetchall()
    return {
        d.isoformat(): {MODIS: m, VIIRS_SOURCES[0]: s, VIIRS_SOURCES[1]: n, VIIRS_SOURCES[2]: n21}
        for d, m, s, n, n21 in rows
    }


# --------------------------------------------------------------------------- ROI


def _roi_id(wkb: bytes) -> str:
    # Aynı geometri → aynı kimlik: aynı bölge tekrar seçilince önbellek yeniden kullanılır
    return hashlib.sha1(wkb).hexdigest()[:12]


def create_roi(
    conn: psycopg.Connection,
    geojson: dict | None = None,
    circle: tuple[float, float, float] | None = None,
    name: str | None = None,
) -> dict:
    """GeoJSON (Geometry/Feature/FeatureCollection) ya da daire (enlem, boylam, km) → ROI."""
    if circle is not None:
        lat, lon, radius_km = circle
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0.5 <= radius_km <= 1000):
            raise AreaError("Daire: enlem −90..90, boylam −180..180, yarıçap 0,5..1000 km olmalı")
        geom_sql = "ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)::geometry"
        params: tuple = (lon, lat, radius_km * 1000)
    elif geojson is not None:
        geom_sql = "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
        params = (json.dumps(_geometry_of(geojson)),)
    else:
        raise AreaError("geojson ya da circle gerekli")

    try:
        row = conn.execute(
            f"""
            WITH g AS (
                SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid({geom_sql}), 3)) AS geom
            ),
            cov AS (
                SELECT array_agg(b.iso2 ORDER BY b.iso2) AS countries,
                       ST_Area(ST_Intersection(g.geom, ST_Union(b.geom))::geography) AS covered
                FROM g JOIN country_boundary b
                  ON b.iso2 = ANY(%s) AND ST_Intersects(b.geom, g.geom)
                GROUP BY g.geom
            )
            SELECT ST_AsBinary(g.geom), ST_Area(g.geom::geography) / 1e6,
                   coalesce(cov.countries, '{{}}'),
                   coalesce(cov.covered / nullif(ST_Area(g.geom::geography), 0), 0)
            FROM g LEFT JOIN cov ON true
            """,
            (*params, list(COUNTRIES)),
        ).fetchone()
    except psycopg.errors.DataException as e:  # geçersiz GeoJSON
        raise AreaError(f"Geçersiz geometri: {e.diag.message_primary}") from e

    wkb, area_km2, countries, covered = row
    if wkb is None or not area_km2:
        raise AreaError("Geometri bir alan (çokgen) içermiyor")
    if area_km2 < MIN_ROI_AREA_KM2:
        raise AreaError(f"Bölge çok küçük (< {MIN_ROI_AREA_KM2} km²)")
    if area_km2 > MAX_ROI_AREA_KM2:
        raise AreaError(f"Bölge çok büyük (> {MAX_ROI_AREA_KM2:,} km²)")
    if not countries:
        raise AreaError("Bu bölge için veri yok. Yüklü ülkeler: " + ", ".join(sorted(COUNTRIES)))

    rid = _roi_id(bytes(wkb))
    conn.execute(
        """
        INSERT INTO roi (id, name, geom, area_km2, countries, covered_pct)
        VALUES (%s, %s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET name = coalesce(EXCLUDED.name, roi.name)
        """,
        (rid, name, wkb, area_km2, countries, round(covered * 100, 1)),
    )
    return roi_info(conn, rid)


def _geometry_of(obj: dict) -> dict:
    t = obj.get("type") if isinstance(obj, dict) else None
    if t == "Feature":
        return _geometry_of(obj.get("geometry") or {})
    if t == "FeatureCollection":
        geoms = [_geometry_of(f) for f in obj.get("features", [])]
        if not geoms:
            raise AreaError("FeatureCollection boş")
        return {"type": "GeometryCollection", "geometries": geoms}
    if t in ("Polygon", "MultiPolygon", "GeometryCollection"):
        return obj
    raise AreaError("GeoJSON bir Polygon/MultiPolygon (ya da onları içeren Feature) olmalı")


def roi_status(conn: psycopg.Connection, rid: str) -> tuple[str, float]:
    row = conn.execute("SELECT status, progress FROM roi WHERE id = %s", (rid,)).fetchone()
    if not row:
        raise AreaError("Bölge bulunamadı")
    return row[0], float(row[1])


def roi_info(conn: psycopg.Connection, rid: str) -> dict:
    row = conn.execute(
        f"""
        SELECT id, name, area_km2, countries, covered_pct, status, progress, error,
               model_version, computed_at, status = 'running' AND {_STALE_SQL} AS stale,
               ST_AsGeoJSON(geom, 5)::json,
               ST_Y(ST_Centroid(geom)), ST_X(ST_Centroid(geom)),
               ARRAY[ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)]
        FROM roi WHERE id = %s
        """,
        (rid,),
    ).fetchone()
    if not row:
        raise AreaError("Bölge bulunamadı")
    keys = (
        "id",
        "name",
        "area_km2",
        "countries",
        "covered_pct",
        "status",
        "progress",
        "error",
        "model_version",
        "computed_at",
        "stale",
        "geometry",
        "center_lat",
        "center_lon",
        "bbox",
    )
    info = dict(zip(keys, row, strict=True))
    info["area"] = f"roi:{info['id']}"
    info["computed_at"] = info["computed_at"].isoformat() if info["computed_at"] else None
    info["area_km2"] = round(info["area_km2"], 1)
    return info


# Hesaplayan worker her yılda heartbeat_at'i yeniler. Bundan eski heartbeat'li "running" bölge
# sahipsiz sayılır (worker çöktü / yeniden başladı) ve yeniden sahiplenilebilir.
ROI_STALE_AFTER = "10 minutes"
# Aynı anda en fazla bu kadar bölge hesaplanır (her biri 26 yıl tarar). Fazlası 'pending'
# bekler ve istemcinin bir sonraki yoklamasında sıraya girer: herkese açık POST /roi ile
# veritabanı boğulamaz. (İstekler web vekilinden geldiği için IP başına sınır işe yaramaz.)
MAX_CONCURRENT_ROI = 2
# "running" ama sahipsiz mi? (roi_info.stale ve sahiplenme koşulu aynı tanımı kullanır)
_STALE_SQL = f"(heartbeat_at IS NULL OR heartbeat_at < now() - interval '{ROI_STALE_AFTER}')"


class _Superseded(Exception):
    """Hesaplama sürerken harmonizasyon bölgeyi yeniden 'pending' yaptı: sonuç eskidi."""


def claim_roi(conn: psycopg.Connection, rid: str) -> bool:
    """Bölgeyi bu worker için atomik olarak sahiplenir; başka worker hesaplıyorsa False.

    Yalnızca 'pending' ya da sahipsiz kalmış 'running' bölgeler sahiplenilir. 'error' otomatik
    yeniden denenmez (her yoklamada aynı ağır sorgu tekrar çalışmasın): bkz. retry_roi.
    """
    row = conn.execute(
        f"""
        UPDATE roi SET status = 'running', progress = 0, error = NULL, heartbeat_at = now()
        WHERE id = %s AND (status = 'pending' OR (status = 'running' AND {_STALE_SQL}))
          AND (SELECT count(*) FROM roi r2
               WHERE r2.status = 'running' AND r2.id <> %s
                 AND NOT (r2.heartbeat_at IS NULL
                          OR r2.heartbeat_at < now() - interval '{ROI_STALE_AFTER}')) < %s
        RETURNING id
        """,
        (rid, rid, MAX_CONCURRENT_ROI),
    ).fetchone()
    return row is not None


def retry_roi(conn: psycopg.Connection, rid: str) -> bool:
    """Hata vermiş bölgeyi yeniden kuyruğa alır ('error' → 'pending')."""
    row = conn.execute(
        "UPDATE roi SET status = 'pending', progress = 0, error = NULL"
        " WHERE id = %s AND status = 'error' RETURNING id",
        (rid,),
    ).fetchone()
    return row is not None


def compute_roi(pool, rid: str) -> None:
    """ROI günlük serisini yıl yıl hesaplar (ilerleme roi.progress'te). Arka planda çalışır."""
    try:
        with pool.connection() as conn:
            conn.autocommit = True
            if not claim_roi(conn, rid):
                return  # başka bir istek / worker hesaplıyor ya da hesaplanacak bir şey yok
            _compute(conn, rid)
    except _Superseded:
        log.info("ROI %s: harmonizasyon değişti, sonuç atıldı (yeniden hesaplanacak)", rid)
    except Exception as e:  # noqa: BLE001 - hata kullanıcıya roi.error ile gösterilir
        log.exception("ROI %s hesaplanamadı", rid)
        with pool.connection() as conn:
            conn.execute(
                "UPDATE roi SET status = 'error', error = %s WHERE id = %s AND status = 'running'",
                (str(e)[:500], rid),
            )
            conn.commit()


def _heartbeat(conn: psycopg.Connection, rid: str, progress: float) -> None:
    cur = conn.execute(
        "UPDATE roi SET progress = %s, heartbeat_at = now() WHERE id = %s AND status = 'running'",
        (progress, rid),
    )
    if cur.rowcount == 0:
        raise _Superseded(rid)


def _compute(conn: psycopg.Connection, rid: str) -> None:
    today = date.today()
    years = list(range(FIRST_DAY.year, today.year + 1))
    factors = pd.DataFrame(
        conn.execute(
            """
            SELECT country, day, basis, v_n, f_evt, f_det, f_frp, provisional
            FROM harmonized_factor
            WHERE country = ANY((SELECT countries FROM roi WHERE id = %s)::char(2)[])
            """,
            (rid,),
        ).fetchall(),
        columns=["country", "day", "basis", "v_n", "f_evt", "f_det", "f_frp", "provisional"],
    )
    if factors.empty:
        raise RuntimeError("Bu bölgenin ülkeleri henüz harmonize edilmemiş (pnpm harmonize run)")
    version = conn.execute(
        "SELECT min(model_version) FROM harmonized_daily WHERE country = ANY("
        "(SELECT countries FROM roi WHERE id = %s)::char(2)[])",
        (rid,),
    ).fetchone()[0]

    parts = []
    for i, y in enumerate(years):
        # Yalnızca temizlenmiş tespitler (detection_event'te eşlemesi olanlar)
        rows = conn.execute(
            """
            SELECT f.acq_date, f.country, f.source, count(*),
                   count(DISTINCT (de.event_no, h3_cell_to_parent(f.h3_r8, 5))),
                   coalesce(sum(f.frp), 0)
            FROM roi r
            JOIN fire_detection f ON f.geom && r.geom AND ST_Intersects(f.geom, r.geom)
            JOIN detection_event de ON de.detection_id = f.id
            WHERE r.id = %s AND f.acq_date BETWEEN make_date(%s, 1, 1) AND make_date(%s, 12, 31)
            GROUP BY 1, 2, 3
            """,
            (rid, y, y),
        ).fetchall()
        if rows:
            parts.append(
                pd.DataFrame(rows, columns=["day", "country", "source", "det", "evt", "frp"])
            )
        _heartbeat(conn, rid, round((i + 1) / len(years) * 100, 1))

    daily = harmonize_roi(pd.concat(parts) if parts else None, factors)
    # Seri ve 'ready' birlikte yazılır; arada harmonizasyon bölgeyi 'pending' yaptıysa
    # (eski katsayılarla hesaplandı) hiçbiri kalıcı olmaz.
    with conn.transaction():
        _write_daily(conn, rid, daily)
        cur = conn.execute(
            "UPDATE roi SET status = 'ready', progress = 100, computed_at = now(),"
            " model_version = %s, heartbeat_at = now() WHERE id = %s AND status = 'running'",
            (version, rid),
        )
        if cur.rowcount == 0:
            raise _Superseded(rid)


def _write_daily(conn: psycopg.Connection, rid: str, daily: pd.DataFrame) -> None:
    conn.execute("DELETE FROM roi_daily WHERE roi_id = %s", (rid,))
    if not daily.empty:
        block = daily.assign(roi_id=rid)[
            [
                "roi_id",
                "day",
                "hotspots",
                "events",
                "frp",
                "provisional",
                "modis_det",
                "snpp_det",
                "noaa20_det",
                "noaa21_det",
            ]
        ].to_csv(index=False, header=False)
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY roi_daily (roi_id, day, hotspots, events, frp, provisional, modis_det,"
                " snpp_det, noaa20_det, noaa21_det) FROM STDIN WITH (FORMAT csv)"
            ) as copy,
        ):
            copy.write(block)


def harmonize_roi(raw: pd.DataFrame | None, factors: pd.DataFrame) -> pd.DataFrame:
    """ROI tespit sayıları (gün × ülke × kaynak) + ülke × gün katsayıları → günlük seri.

    VIIRS günü: değer = katsayı × (VIIRS kaynakları toplamı / o gün veri veren uydu sayısı)
    MODIS günü: değer = katsayı × MODIS değeri. Birden çok ülke kesişiyorsa toplanır.
    """
    cols = [
        "day",
        "hotspots",
        "events",
        "frp",
        "provisional",
        "modis_det",
        "snpp_det",
        "noaa20_det",
        "noaa21_det",
    ]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    piv = raw.pivot_table(
        index=["day", "country"],
        columns="source",
        values=["det", "evt", "frp"],
        aggfunc="sum",
        fill_value=0,
    )
    piv.columns = [f"{v}_{s}" for v, s in piv.columns]
    for v in ("det", "evt", "frp"):
        for s in (MODIS, *VIIRS_SOURCES):
            if f"{v}_{s}" not in piv.columns:
                piv[f"{v}_{s}"] = 0
    piv = piv.reset_index()
    f = factors.set_index(["day", "country"])
    j = piv.join(f, on=["day", "country"], how="inner")
    viirs = j["basis"] == "viirs_calibrated"
    v_n = j["v_n"].clip(lower=1)
    out = pd.DataFrame({"day": j["day"], "provisional": j["provisional"]})
    for v, fcol, name in (
        ("det", "f_det", "hotspots"),
        ("evt", "f_evt", "events"),
        ("frp", "f_frp", "frp"),
    ):
        viirs_val = sum(j[f"{v}_{s}"] for s in VIIRS_SOURCES) / v_n
        base = viirs_val.where(viirs, j[f"{v}_{MODIS}"])
        out[name] = base * j[fcol]
    out["modis_det"] = j[f"det_{MODIS}"]
    out["snpp_det"] = j[f"det_{VIIRS_SOURCES[0]}"]
    out["noaa20_det"] = j[f"det_{VIIRS_SOURCES[1]}"]
    out["noaa21_det"] = j[f"det_{VIIRS_SOURCES[2]}"]
    daily = out.groupby("day", as_index=False).agg(
        hotspots=("hotspots", "sum"),
        events=("events", "sum"),
        frp=("frp", "sum"),
        provisional=("provisional", "max"),
        modis_det=("modis_det", "sum"),
        snpp_det=("snpp_det", "sum"),
        noaa20_det=("noaa20_det", "sum"),
        noaa21_det=("noaa21_det", "sum"),
    )
    daily = daily[(daily["hotspots"] > 0) | (daily["events"] > 0)]
    return daily.round({"hotspots": 4, "events": 4, "frp": 2})[cols]
