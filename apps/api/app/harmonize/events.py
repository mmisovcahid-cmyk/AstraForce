"""ST-DBSCAN: tespit noktalarını mekân-zaman yakınlığına göre yangın olaylarına birleştirir.

min_samples=1 kullanıldığı için ST-DBSCAN, "≤ EPS_KM ve ≤ EPS_DAYS uzaklıktaki noktalar
aynı olaydır" kuralının bağlantılı bileşenlerine indirgenir (gürültü noktası yoktur;
tek pikselli küçük yangın da bir olaydır).

Bellek için veri yıl yıl işlenir; önceki dilimin son EPS_DAYS günü "taşıma" olarak
yeni dilime eklenir, böylece yılbaşını aşan olaylar bölünmez.
"""

import io

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.neighbors import BallTree

from app.harmonize.settings import EPOCH, EVENT_EPS_DAYS, EVENT_EPS_KM, MIN_CONFIDENCE

EARTH_RADIUS_KM = 6371.0088


def _edges(
    day: np.ndarray, lat_r: np.ndarray, lon_r: np.ndarray, first: int, eps_rad: float, eps_days: int
) -> tuple[np.ndarray, np.ndarray]:
    """[first:] aralığındaki noktaların, kendilerinden önceki ≤eps_days gün içindeki
    (aynı gün dahil) komşularıyla kenarlarını döndürür. Dizi güne göre sıralı olmalı."""
    uniq, starts = np.unique(day, return_index=True)
    ends = np.append(starts[1:], len(day))
    rows, cols = [], []
    for k in range(np.searchsorted(uniq, day[first]) if first < len(day) else len(uniq), len(uniq)):
        s, e = starts[k], ends[k]
        ws = starts[np.searchsorted(uniq, uniq[k] - eps_days)]
        pts = np.column_stack([lat_r[ws:e], lon_r[ws:e]])
        nbrs = BallTree(pts, metric="haversine").query_radius(pts[s - ws :], r=eps_rad)
        lens = np.fromiter((len(a) for a in nbrs), dtype=np.int64, count=len(nbrs))
        rows.append(np.repeat(np.arange(s, e), lens))
        cols.append(np.concatenate(nbrs) + ws)
    if not rows:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    return np.concatenate(rows), np.concatenate(cols)


def _find(parent: np.ndarray, idx: np.ndarray) -> np.ndarray:
    r = parent[idx]
    while True:
        nxt = parent[r]
        if np.array_equal(nxt, r):
            return r
        r = nxt


def cluster_events(
    day: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    eps_km: float = EVENT_EPS_KM,
    eps_days: int = EVENT_EPS_DAYS,
    chunk_days: int = 366,
) -> np.ndarray:
    """Güne göre sıralı noktalar için olay etiketleri (0..k-1) döndürür."""
    n = len(day)
    if n == 0:
        return np.empty(0, np.int64)
    if np.any(np.diff(day) < 0):
        raise ValueError("day dizisi artan sırada olmalı")
    lat_r, lon_r = np.radians(lat), np.radians(lon)
    eps_rad = eps_km / EARTH_RADIUS_KM
    parent = np.arange(n, dtype=np.int64)

    chunk_start = 0
    while chunk_start < n:
        chunk_end = int(np.searchsorted(day, day[chunk_start] + chunk_days))
        carry = int(np.searchsorted(day, day[chunk_start] - eps_days))
        sl = slice(carry, chunk_end)
        r, c = _edges(day[sl], lat_r[sl], lon_r[sl], chunk_start - carry, eps_rad, eps_days)

        # Grafik düğümleri: dilim noktaları (yerel 0..m-1) + taşınan noktaların mevcut kökleri.
        m = chunk_end - carry
        carry_idx = np.arange(carry, chunk_start)
        roots = _find(parent, carry_idx) if len(carry_idx) else np.empty(0, np.int64)
        uniq_roots, root_local = np.unique(roots, return_inverse=True)
        extra_r = np.arange(len(carry_idx))
        extra_c = m + root_local
        g = coo_matrix(
            (np.ones(len(r) + len(extra_r)), (np.r_[r, extra_r], np.r_[c, extra_c])),
            shape=(m + len(uniq_roots), m + len(uniq_roots)),
        )
        _, comp = connected_components(g, directed=False)
        global_ids = np.r_[np.arange(carry, chunk_end), uniq_roots]
        # Her bileşenin temsilcisi: en küçük global indeks (eski olayların kökü her zaman öncedir).
        rep = pd.Series(global_ids).groupby(comp).transform("min").to_numpy()
        parent[global_ids] = rep
        chunk_start = chunk_end

    roots = _find(parent, np.arange(n))
    _, labels = np.unique(roots, return_inverse=True)
    return labels.astype(np.int64)


def load_clean_detections(conn: psycopg.Connection, country: str, source: str) -> pd.DataFrame:
    """Temizlenmiş tespitler: güven ≥ nominal, type 0 (ya da NRT'de boş), maske dışı."""
    query = sql.SQL(
        """
        COPY (
            SELECT f.id, (f.acq_date - DATE {epoch}) AS d, f.lat, f.lon, coalesce(f.frp, 0) AS frp,
                   h3_cell_to_parent(f.h3_r8, 5)::bigint AS h3, (f.product = 'NRT')::int AS nrt
            FROM fire_detection f
            WHERE f.country = {country} AND f.source = {source}
              AND f.confidence_level >= {min_conf}
              AND coalesce(f.fire_type, 0) = 0
              AND NOT EXISTS (SELECT 1 FROM static_mask m WHERE m.h3_r8 = f.h3_r8)
            ORDER BY f.acq_date
        ) TO STDOUT WITH (FORMAT csv, HEADER true)
        """
    ).format(
        epoch=sql.Literal(EPOCH.isoformat()),
        country=sql.Literal(country),
        source=sql.Literal(source),
        min_conf=sql.Literal(MIN_CONFIDENCE),
    )
    buf = io.BytesIO()
    with conn.cursor() as cur, cur.copy(query) as copy:
        for chunk in copy:
            buf.write(chunk)
    buf.seek(0)
    return pd.read_csv(
        buf,
        dtype={
            "id": "int64",
            "d": "int32",
            "lat": "float64",
            "lon": "float64",
            "frp": "float32",
            "h3": "int64",
            "nrt": "int8",
        },
    )


def summarize(df: pd.DataFrame, labels: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(olaylar, günlük hücre istatistikleri) tablolarını üretir."""
    df = df.assign(evt=labels)
    events = df.groupby("evt", sort=False).agg(
        start=("d", "min"),
        end=("d", "max"),
        lat=("lat", "mean"),
        lon=("lon", "mean"),
        h3=("h3", "first"),
        n_det=("d", "size"),
        frp_sum=("frp", "sum"),
        frp_max=("frp", "max"),
        has_nrt=("nrt", "max"),
    )
    daily = (
        df.groupby(["d", "h3"], sort=False)
        .agg(
            n_det=("evt", "size"),
            n_evt=("evt", "nunique"),
            frp_sum=("frp", "sum"),
            has_nrt=("nrt", "max"),
        )
        .reset_index()
    )
    return events, daily


def _copy_rows(conn: psycopg.Connection, statement: str, rows) -> None:
    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def build_events(conn: psycopg.Connection, country: str, source: str) -> dict[str, int]:
    df = load_clean_detections(conn, country, source)
    labels = cluster_events(df["d"].to_numpy(), df["lat"].to_numpy(), df["lon"].to_numpy())
    events, daily = summarize(df, labels)

    with conn.transaction():
        conn.execute("DELETE FROM fire_event WHERE country = %s AND source = %s", (country, source))
        conn.execute(
            "DELETE FROM daily_cell_stats WHERE country = %s AND source = %s", (country, source)
        )
        # Tespit → olay eşlemesi (bölge sorguları olay-gün sayabilsin diye)
        conn.execute(
            """
            DELETE FROM detection_event de USING fire_detection f
            WHERE de.detection_id = f.id AND f.country = %s AND f.source = %s
            """,
            (country, source),
        )
        # Milyonlarca satır: tek CSV bloğu olarak gönder (satır satır write_row'dan çok hızlı)
        csv_block = pd.DataFrame({"id": df["id"], "evt": labels}).to_csv(index=False, header=False)
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY detection_event (detection_id, event_no) FROM STDIN WITH (FORMAT csv)"
            ) as copy,
        ):
            copy.write(csv_block)
        conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS stage_event (start_d int, end_d int, lat float8,"
            " lon float8, h3 bigint, n_det int, frp_sum real, frp_max real, has_nrt bool)"
        )
        conn.execute("TRUNCATE stage_event")
        _copy_rows(
            conn,
            "COPY stage_event FROM STDIN",
            (
                (
                    int(r.start),
                    int(r.end),
                    float(r.lat),
                    float(r.lon),
                    int(r.h3),
                    int(r.n_det),
                    float(r.frp_sum),
                    float(r.frp_max),
                    bool(r.has_nrt),
                )
                for r in events.itertuples(index=False)
            ),
        )
        conn.execute(
            """
            INSERT INTO fire_event (country, source, start_date, end_date, lat, lon, h3_r5, n_det,
                                    frp_sum, frp_max, has_nrt)
            SELECT %s, %s, %s::date + start_d, %s::date + end_d, lat, lon, h3::h3index, n_det,
                   frp_sum, frp_max, has_nrt
            FROM stage_event
            """,
            (country, source, EPOCH, EPOCH),
        )
        conn.execute(
            "CREATE TEMP TABLE IF NOT EXISTS stage_daily (d int, h3 bigint, n_det int, n_evt int,"
            " frp_sum real, has_nrt bool)"
        )
        conn.execute("TRUNCATE stage_daily")
        _copy_rows(
            conn,
            "COPY stage_daily FROM STDIN",
            (
                (int(r.d), int(r.h3), int(r.n_det), int(r.n_evt), float(r.frp_sum), bool(r.has_nrt))
                for r in daily.itertuples(index=False)
            ),
        )
        conn.execute(
            """
            INSERT INTO daily_cell_stats (country, source, h3_r5, day, n_det, n_evt, frp_sum,
                                          has_nrt)
            SELECT %s, %s, h3::h3index, %s::date + d, n_det, n_evt, frp_sum, has_nrt
            FROM stage_daily
            """,
            (country, source, EPOCH),
        )
    return {"detections": len(df), "events": len(events), "cell_days": len(daily)}
