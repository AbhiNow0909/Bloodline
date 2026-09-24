from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings

VALID: dict[str, Any] = {
    "database_url": "postgresql+psycopg://user:pass@localhost:5432/db",
    "jwt_secret": "s" * 32,
}


def test_cors_origins_split_on_commas_and_trimmed() -> None:
    settings = Settings(**VALID, cors_origins=" http://localhost:5173, https://bloodline.example ,")

    assert settings.cors_origin_list == ["http://localhost:5173", "https://bloodline.example"]


@pytest.mark.parametrize("missing", ["DATABASE_URL", "JWT_SECRET"])
def test_required_settings(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.delenv(missing, raising=False)
    others = {k: v for k, v in VALID.items() if k != missing.lower()}

    with pytest.raises(ValidationError, match=missing.lower()):
        Settings(_env_file=None, **others)


def test_jwt_secret_must_be_at_least_32_characters() -> None:
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None, **(VALID | {"jwt_secret": "too-short"}))


def test_jwt_secret_is_hidden_in_repr() -> None:
    settings = Settings(_env_file=None, **VALID)

    assert "s" * 32 not in repr(settings)
    assert settings.jwt_secret.get_secret_value() == "s" * 32
