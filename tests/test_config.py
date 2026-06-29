import pytest

from content_archiver_telegram.config import Settings


def test_allowed_user_ids_parse_commas_spaces_and_semicolons(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "1, 2;3 1")

    assert Settings.from_env().telegram_allowed_user_ids == {1, 2, 3}


def test_telegram_security_requires_allowlist() -> None:
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS"):
        Settings().validate_telegram_security()

    Settings(telegram_allowed_user_ids={1}).validate_telegram_security()
    Settings(telegram_allow_all_users=True).validate_telegram_security()
