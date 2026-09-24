from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo-root .env is read for local (non-Docker) runs. In containers it resolves to a
# path that does not exist, so configuration comes only from real environment variables.
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    cors_origins: str = "http://localhost:5173"
    # HS256 needs a key of at least 32 bytes (RFC 7518). SecretStr keeps it out of reprs/logs.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = Field(default=1440, gt=0)

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS is a comma-separated list of allowed frontend origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
