from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class RunConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8001


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class ApiPrefix(BaseModel):
    api_prefix: str = "/api"
    auth_prefix: str = "/auth"
    users_prefix: str = "/users"
    generations_prefix: str = "/generations"
    admin_prefix: str = "/admin"


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
    max_attempts: int = 3
    max_retry_delay_seconds: float = 30.0


class GenerationConfig(BaseModel):
    backend: Literal["gemini", "fake"] = "gemini"
    fake_delay_seconds: float = 2.0
    free_daily_limit: int = Field(default=3, ge=0)
    pro_daily_limit: int = Field(default=50, ge=0)
    limit_window_hours: int = Field(default=24, ge=1)
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, gt=0)
    max_image_side: int = Field(default=2048, ge=256)
    max_image_pixels: int = Field(default=50_000_000, gt=0)


class StorageConfig(BaseModel):
    backend: Literal["local"] = "local"
    local_path: Path = BASE_DIR / "storage"


class GoogleOAuthConfig(BaseModel):
    client_id: str
    client_secret: SecretStr
    redirect_uri: str = "http://localhost:8001/api/auth/google/callback"


class AuthConfig(BaseModel):
    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    refresh_reuse_grace_seconds: int = 10
    access_cookie_name: str = "access_token"
    refresh_cookie_name: str = "refresh_token"
    cookie_secure: bool = False
    frontend_url: str = "http://localhost:5173"


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
    logging: LoggingConfig = LoggingConfig()
    prefix: ApiPrefix = ApiPrefix()
    db: DataBaseConfig
    gemini: GeminiConfig = GeminiConfig()
    generation: GenerationConfig = GenerationConfig()
    storage: StorageConfig = StorageConfig()
    google: GoogleOAuthConfig
    auth: AuthConfig


settings = Settings()
