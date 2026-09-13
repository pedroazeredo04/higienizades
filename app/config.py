"""Environment-backed configuration.

Values that a household might change day to day (household name, timezone,
join code) live in the `setting` DB table instead -- see `app.services.settings`.
Only deployment-level knobs belong here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Signs the session cookie. Changing it logs everybody out.
    secret_key: str = "dev-only-insecure-key-change-me"
    database_url: str = "sqlite:///./data/higienizades.db"

    # Seeds the household timezone on first boot; editable afterwards in Settings.
    default_timezone: str = "America/Sao_Paulo"

    # Phones should stay logged in more or less forever on a trusted LAN.
    session_max_age_days: int = 90

    backup_dir: str = "./data/backups"
    backup_keep: int = 14

    # Disabled in tests, where the scheduler would only add noise.
    enable_jobs: bool = True


@lru_cache
def get_config() -> Config:
    return Config()
