"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when a command requires configuration that is not available."""


class Settings(BaseSettings):
    """Environment-backed settings with no private path defaults."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./.private/app.db"
    identity_hash_salt: SecretStr | None = None
    discord_bot_token: SecretStr | None = None
    discord_channel_allowlist: str = ""
    discord_support_role_ids: str = ""
    discord_approved_bot_ids: str = ""
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str | None = None
    openrouter_model: str | None = None
    classifier_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    classifier_retry_limit: int = Field(default=2, ge=0, le=5)
    classifier_schema_retry_limit: int = Field(default=1, ge=0, le=2)
    classifier_confidence_threshold: float = Field(default=0.70, ge=0, le=1)
    classifier_context_limit: int = Field(default=3, ge=0, le=3)
    classifier_context_window_minutes: int = Field(default=30, ge=1, le=240)
    classifier_payload_max_chars: int = Field(default=6000, ge=500, le=20000)
    classifier_concurrency: int = Field(default=3, ge=1, le=10)
    private_messages_csv: Path | None = None
    private_labels_csv: Path | None = None
    private_train_csv: Path | None = None
    private_golden_csv: Path | None = None

    def require_paths(self, *field_names: str) -> tuple[Path, ...]:
        """Return configured, existing paths or raise one actionable error."""

        missing: list[str] = []
        invalid: list[str] = []
        paths: list[Path] = []

        for field_name in field_names:
            value = getattr(self, field_name, None)
            env_name = field_name.upper()
            if value is None:
                missing.append(env_name)
                continue

            path = value.expanduser().resolve()
            if not path.is_file():
                invalid.append(f"{env_name}={path}")
                continue
            paths.append(path)

        messages: list[str] = []
        if missing:
            messages.append("missing: " + ", ".join(missing))
        if invalid:
            messages.append("not a readable file: " + ", ".join(invalid))
        if messages:
            raise ConfigurationError(
                "Private dataset configuration is invalid (" + "; ".join(messages) + "). "
                "Set the variables in the environment or in a local .env file."
            )
        return tuple(paths)

    def require_identity_hash_salt(self) -> str:
        """Return the local hashing salt or fail before private data is ingested."""

        if self.identity_hash_salt is None:
            raise ConfigurationError(
                "IDENTITY_HASH_SALT is required for ingestion. "
                "Set a private, stable value in the local environment or .env file."
            )
        value = self.identity_hash_salt.get_secret_value().strip()
        if len(value) < 16:
            raise ConfigurationError("IDENTITY_HASH_SALT must contain at least 16 characters.")
        return value

    def require_classifier_config(self) -> tuple[str, str, str]:
        """Return API key, base URL, and model without exposing the key in errors."""

        missing: list[str] = []
        if self.openrouter_api_key is None:
            missing.append("OPENROUTER_API_KEY")
        if not self.openrouter_base_url:
            missing.append("OPENROUTER_BASE_URL")
        if not self.openrouter_model:
            missing.append("OPENROUTER_MODEL")
        if missing:
            raise ConfigurationError(
                "Classifier configuration is missing: " + ", ".join(missing)
            )
        api_key = self.openrouter_api_key.get_secret_value().strip()
        base_url = self.openrouter_base_url.strip().rstrip("/")
        model = self.openrouter_model.strip()
        if not api_key:
            raise ConfigurationError("OPENROUTER_API_KEY must not be blank")
        if not base_url.startswith(("http://", "https://")):
            raise ConfigurationError("OPENROUTER_BASE_URL must be an HTTP(S) URL")
        if not model:
            raise ConfigurationError("OPENROUTER_MODEL must not be blank")
        return api_key, base_url, model

    @property
    def allowed_discord_channels(self) -> frozenset[str]:
        """Parse the comma-separated Discord channel allowlist."""

        return frozenset(
            channel.strip()
            for channel in self.discord_channel_allowlist.split(",")
            if channel.strip()
        )

    @staticmethod
    def _parse_id_set(value: str) -> frozenset[str]:
        return frozenset(item.strip() for item in value.split(",") if item.strip())

    @property
    def support_role_ids(self) -> frozenset[str]:
        return self._parse_id_set(self.discord_support_role_ids)

    @property
    def approved_bot_ids(self) -> frozenset[str]:
        return self._parse_id_set(self.discord_approved_bot_ids)


def _find_env_file(start: Path | None = None) -> Path | None:
    """Find the nearest .env without assuming the command working directory."""

    current = (start or Path.cwd()).resolve()
    candidates: Iterable[Path] = (current, *current.parents)
    for directory in candidates:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once, optionally from the nearest local .env file."""

    env_file = _find_env_file()
    return Settings(_env_file=env_file, _env_file_encoding="utf-8")
