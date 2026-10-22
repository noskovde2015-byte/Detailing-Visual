from pathlib import Path

from pydantic import BaseModel, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class RunConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8001


class ApiPrefix(BaseModel):
    api_prefix: str = "/api"


class DataBaseConfig(BaseModel):
    url: PostgresDsn
    echo: bool = False
    echo_pool: bool = False
    pool_size: int = 10
    max_overflow: int = 10


class GeminiConfig(BaseModel):
    api_key: SecretStr | None = None
    model: str = "gemini-3-pro-image"
    timeout_seconds: int = 120


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="APP_CONFIG__",
        env_nested_delimiter="__",
    )

    app_name: str = "Detailing.Visual"
    run: RunConfig = RunConfig()
    prefix: ApiPrefix = ApiPrefix()
    db: DataBaseConfig
    gemini: GeminiConfig = GeminiConfig()


settings = Settings()
