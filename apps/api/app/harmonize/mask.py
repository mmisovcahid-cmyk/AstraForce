"""Sabit ısı kaynakları maskesi (endüstri tesisleri, gaz meşaleleri, ...).

Kaynak: (1) NASA'nın SP verisindeki type=2 işareti, (2) çok gün ve çok yıl boyunca
tekrar eden tespitler. MODIS pikseli (~1 km) komşu r8 hücresine düşebildiği için
maskelenen hücrelerin 1 halkalık komşuları da maskelenir.
"""

import psycopg

from app.harmonize.settings import PERSISTENT_MIN_DAYS, PERSISTENT_MIN_YEARS


def build_static_mask(conn: psycopg.Connection) -> dict[str, int]:
    with conn.transaction():
        conn.execute("TRUNCATE static_mask")
        conn.execute(
            """
            INSERT INTO static_mask (h3_r8, reason)
            SELECT DISTINCT h3_r8, 'nasa_type2' FROM fire_detection WHERE fire_type = 2
            """
        )
        conn.execute(
            """
            INSERT INTO static_mask (h3_r8, reason)
            SELECT h3_r8, 'persistent' FROM fire_detection
            WHERE coalesce(fire_type, 0) = 0
            GROUP BY h3_r8
            HAVING count(DISTINCT acq_date) >= %s
               AND count(DISTINCT extract(year FROM acq_date)) >= %s
            ON CONFLICT DO NOTHING
            """,
            (PERSISTENT_MIN_DAYS, PERSISTENT_MIN_YEARS),
        )
        conn.execute(
            """
            INSERT INTO static_mask (h3_r8, reason)
            SELECT DISTINCT n, 'neighbor'
            FROM static_mask m, LATERAL h3_grid_disk(m.h3_r8, 1) AS n
            ON CONFLICT DO NOTHING
            """
        )
        rows = conn.execute("SELECT reason, count(*) FROM static_mask GROUP BY 1").fetchall()
    return dict(rows)
