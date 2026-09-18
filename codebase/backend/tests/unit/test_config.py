from pathlib import Path

import pytest

from app.config import ConfigurationError, Settings


def test_require_paths_reports_missing_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRIVATE_MESSAGES_CSV", raising=False)
    settings = Settings(_env_file=None)

    with pytest.raises(ConfigurationError, match="PRIVATE_MESSAGES_CSV"):
        settings.require_paths("private_messages_csv")


def test_require_paths_resolves_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "messages.csv"
    source.write_text("header\n", encoding="utf-8")
    settings = Settings(_env_file=None, private_messages_csv=source)

    assert settings.require_paths("private_messages_csv") == (source.resolve(),)


def test_ingestion_requires_a_nontrivial_private_hash_salt() -> None:
    with pytest.raises(ConfigurationError, match="IDENTITY_HASH_SALT is required"):
        Settings(_env_file=None, identity_hash_salt=None).require_identity_hash_salt()

    with pytest.raises(ConfigurationError, match="at least 16"):
        Settings(_env_file=None, identity_hash_salt="too-short").require_identity_hash_salt()

    settings = Settings(_env_file=None, identity_hash_salt="long-enough-private-value")
    assert settings.require_identity_hash_salt() == "long-enough-private-value"


def test_discord_allowlist_is_trimmed_and_deduplicated() -> None:
    settings = Settings(
        _env_file=None,
        discord_channel_allowlist=" 123,456,123, ",
    )

    assert settings.allowed_discord_channels == frozenset({"123", "456"})


def test_role_and_approved_bot_ids_are_parsed() -> None:
    settings = Settings(
        _env_file=None,
        discord_support_role_ids="ta, coach,ta",
        discord_approved_bot_ids=" helper-bot ",
    )

    assert settings.support_role_ids == frozenset({"ta", "coach"})
    assert settings.approved_bot_ids == frozenset({"helper-bot"})


def test_classifier_config_is_validated_without_leaking_key() -> None:
    settings = Settings(
        _env_file=None,
        openrouter_api_key="very-private-test-key",
        openrouter_base_url="http://localhost:20128/v1/",
        openrouter_model="cx/test-model",
    )

    assert settings.require_classifier_config() == (
        "very-private-test-key",
        "http://localhost:20128/v1",
        "cx/test-model",
    )

    invalid = Settings(
        _env_file=None,
        openrouter_api_key="very-private-test-key",
        openrouter_base_url="localhost:20128/v1",
        openrouter_model="cx/test-model",
    )
    with pytest.raises(ConfigurationError) as caught:
        invalid.require_classifier_config()
    assert "very-private-test-key" not in str(caught.value)
