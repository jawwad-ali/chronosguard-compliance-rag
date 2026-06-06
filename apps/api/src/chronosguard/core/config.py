"""Application settings — the single configuration surface.

One ``Settings`` class; value source differs by environment (.env locally,
PaaS env vars in prod). ``ENV`` switches log rendering, CORS, and Sentry only —
never behavioral code branches.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_MARKER = "_dev_password"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["local", "prod"] = "local"
    log_level: str = "INFO"
    app_name: str = "ChronosGuard Compliance API"

    # Request path: least-privilege, RLS-bound role. (Host port 5433 locally —
    # see infra/docker-compose.yml — to avoid colliding with other Postgres installs.)
    database_url: str = (
        "postgresql+asyncpg://cg_app:cg_app_dev_password@localhost:5433/chronosguard"
    )
    # Worker/CLI path: corpus writes + per-job tenant context.
    database_url_worker: str = (
        "postgresql+asyncpg://cg_worker:cg_worker_dev_password@localhost:5433/chronosguard"
    )
    # Migrations only.
    database_url_owner: str = (
        "postgresql+asyncpg://cg_owner:cg_owner_dev_password@localhost:5433/chronosguard"
    )

    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 300

    cors_origins: list[str] = ["http://localhost:3000"]

    openai_api_key: str = ""
    openai_embed_model: str = "text-embedding-3-small"
    openai_audit_model: str = "gpt-4o-mini"

    api_key_pepper: str = "local_dev_pepper"

    sentry_dsn: str = ""

    @model_validator(mode="after")
    def _forbid_dev_defaults_in_prod(self) -> Self:
        """Fail fast if prod boots with local-dev credentials."""
        if self.env != "prod":
            return self
        problems = [
            name
            for name, value in (
                ("DATABASE_URL", self.database_url),
                ("DATABASE_URL_WORKER", self.database_url_worker),
                ("API_KEY_PEPPER", self.api_key_pepper),
            )
            if _DEV_MARKER in value or value == "local_dev_pepper"
        ]
        if problems:
            msg = f"Refusing to start in prod with dev-default values for: {', '.join(problems)}"
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
