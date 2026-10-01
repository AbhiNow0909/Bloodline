from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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
    max_upload_mb: int = Field(default=10, gt=0, le=50)
    # HS256 needs a key of at least 32 bytes (RFC 7518). SecretStr keeps it out of reprs/logs.
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = Field(default=1440, gt=0)

    # Optional so the app and tests run without it; LLM features fail clearly if it is unset.
    groq_api_key: SecretStr | None = None
    structuring_model: str = "openai/gpt-oss-20b"
    agent_model: str = "openai/gpt-oss-120b"

    # Local embeddings for searching report text (fastembed, ONNX; nothing leaves the server).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Where the model files live. The Docker image bakes them into /opt/models at build time.
    # A factory, so the home directory is only looked up when no directory is configured.
    embedding_cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "fastembed")
    # True in the image: never download at runtime (Render has no persistent disk).
    embedding_offline: bool = False
    # One thread keeps memory and CPU use predictable on a small instance.
    embedding_threads: int = Field(default=1, ge=1, le=8)

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def blank_key_is_unset(cls, value: object) -> object:
        """`GROQ_API_KEY=` (as in .env.example) means "not configured"."""
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS is a comma-separated list of allowed frontend origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
