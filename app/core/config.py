from pathlib import Path
from typing import Literal

from pydantic import BaseModel, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class RunConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8001


class ApiPrefix(BaseModel):
    api_prefix: str = "/api"
    auth_prefix: str = "/auth"
    users_prefix: str = "/users"


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
    prefix: ApiPrefix = ApiPrefix()
    db: DataBaseConfig
    gemini: GeminiConfig = GeminiConfig()
    storage: StorageConfig = StorageConfig()
    google: GoogleOAuthConfig
    auth: AuthConfig


settings = Settings()
