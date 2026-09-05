from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    gemini_api_key: str = "changeme"
    gemini_model: str = "gemini-1.5-flash"
    gemini_timeout_seconds: int = 30
    database_url: str = "sqlite:///./data/sqlite/student_life_os.db"
    upload_dir: str = "./data/uploads"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_mock_mode: bool = True
    telegram_polling_enabled: bool = True
    google_client_secrets_file: str = "credentials.json"
    google_token_file: str = "data/google_token.json"
    leetcode_username: str | None = None
    leetcode_poll_interval_seconds: int = 60
    leetcode_enabled: bool = True
    featherless_api_key: str = "changeme"
    featherless_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    featherless_api_url: str = "https://api.featherless.ai/v1/chat/completions"
    featherless_timeout_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / "data"
SQLITE_DIR = DATA_DIR / "sqlite"
UPLOAD_DIR = DATA_DIR / "uploads"


def ensure_data_directories() -> None:
    """Create the local directories required by the application."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLITE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
