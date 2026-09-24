import pytest
from pydantic import ValidationError

from app.config import Settings


def test_cors_origins_split_on_commas_and_trimmed() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        cors_origins=" http://localhost:5173, https://bloodline.example ,",
    )

    assert settings.cors_origin_list == ["http://localhost:5173", "https://bloodline.example"]


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)
