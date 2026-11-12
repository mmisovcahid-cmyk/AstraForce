from app.config import LOCAL_DB, Settings


def test_database_url_built_from_render_parts(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None, db_hostport="astraforce-db:5432", postgres_password="s3cret")
    assert s.database_url == "postgresql://astra:s3cret@astraforce-db:5432/astraforce"


def test_explicit_database_url_wins_and_local_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings(_env_file=None, database_url="postgresql://x@h/db").database_url.endswith(
        "h/db"
    )
    assert Settings(_env_file=None).database_url == LOCAL_DB
