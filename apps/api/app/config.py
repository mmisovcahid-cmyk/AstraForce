from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Tüm uygulamalar monorepo kökündeki tek .env dosyasını paylaşır.
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
LOCAL_DB = "postgresql://astra:astra_local_dev@localhost:5433/astraforce"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    database_url: str = ""
    # Render: veritabanı "private service" olarak çalışır; adresi DB_HOSTPORT ile gelir ve
    # bağlantı dizesi bu parçalardan kurulur (render.yaml'da değişken birleştirme yok).
    db_hostport: str = ""
    postgres_user: str = "astra"
    postgres_password: str = ""
    postgres_db: str = "astraforce"
    cors_origins: str = "http://localhost:3000"
    firms_map_key: str = ""

    @model_validator(mode="after")
    def _build_database_url(self) -> "Settings":
        if not self.database_url:
            if self.db_hostport:
                self.database_url = (
                    f"postgresql://{self.postgres_user}:{self.postgres_password}"
                    f"@{self.db_hostport}/{self.postgres_db}"
                )
            else:
                self.database_url = LOCAL_DB
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
