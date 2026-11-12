"""Basit SQL migration aracı: db/migrations/NNN_*.sql dosyalarını sırayla bir kez uygular.

Kullanım: `pnpm db:migrate` (veya apps/api içinde `uv run python -m app.migrate`).
"""

from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"


def pending_migrations(applied: set[str]) -> list[Path]:
    return [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in applied]


def migrate(database_url: str | None = None) -> list[str]:
    url = database_url or get_settings().database_url
    done: list[str] = []
    with psycopg.connect(url) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.commit()
        applied = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in pending_migrations(applied):
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            done.append(path.name)
    return done


if __name__ == "__main__":
    applied_now = migrate()
    if applied_now:
        for name in applied_now:
            print(f"uygulandı: {name}")
    else:
        print("Veritabanı güncel, uygulanacak migration yok.")
