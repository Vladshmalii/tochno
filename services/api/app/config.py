from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    secret_key: str = _DEFAULT_SECRET
    access_token_minutes: int = 60 * 12

    database_url: str = "sqlite:///./tochno.db"
    storage_dir: str = "./storage"
    max_upload_mb: int = 25
    storage_backend: str = "local"  # local | s3
    s3_bucket: str = ""
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    llm_provider: str = "mock"  # mock | openai
    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4o"

    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:5175"
    allow_signup: bool = True
    trial_days: int = 14
    public_api_url: str = ""  # для реєстрації вебхука Telegram, напр. https://api.example.com
    impersonation_minutes: int = 30

    worker_enabled: bool = True
    worker_poll_seconds: float = 1.0
    allow_private_webhooks: bool = False  # SSRF-захист: у dev/тестах можна вимкнути
    login_max_attempts: int = 8

    bootstrap_admin_email: str = "admin@tochno.app"
    bootstrap_admin_password: str = ""

    @property
    def cors_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_runtime(self) -> None:
        if self.app_env == "prod" and self.secret_key == _DEFAULT_SECRET:
            raise RuntimeError("SECRET_KEY must be set in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
