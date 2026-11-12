from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    if _pool is None:
        # open=False + wait=False: veritabanı kapalıyken de API ayağa kalkar,
        # /health bunu "degraded" olarak raporlar.
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=10,
            open=False,
            timeout=3,
            kwargs={"connect_timeout": 3},
        )
        _pool.open(wait=False)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        # Kısa zaman aşımı: `uvicorn --reload` kapanışta havuz iş parçacıklarını uzun
        # süre beklerse (Windows'ta görüldü) yeniden yükleme takılır, eski kod çalışmaya
        # devam eder.
        _pool.close(timeout=1.0)
        _pool = None


def get_pool() -> ConnectionPool:
    if _pool is None:
        open_pool()
    assert _pool is not None
    return _pool
