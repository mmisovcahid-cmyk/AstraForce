# AstraForce API (FastAPI) — üretim imajı
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /srv/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/app ./app
# Migration dosyaları (app/migrate.py kök dizindeki db/migrations'ı okur)
COPY db/migrations /srv/db/migrations

ENV PATH="/srv/apps/api/.venv/bin:$PATH"
EXPOSE 8000
# Açılışta şemayı güncelle, sonra API'yi başlat (Render PORT verir; yoksa 8000)
CMD ["sh", "-c", "python -m app.migrate && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --proxy-headers"]
