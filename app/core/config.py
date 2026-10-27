from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    model_validator,
)
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
    # Размер результата. 1K и 2K у Nano Banana Pro стоят одинаково, 4K — дороже.
    image_size: Literal["1K", "2K", "4K"] = "2K"


class GenerationConfig(BaseModel):
    backend: Literal["gemini", "fake"] = "gemini"
    fake_delay_seconds: float = 2.0
    welcome_credits: int = Field(default=1, ge=0)
    """Сколько генераций подарить при регистрации."""
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, gt=0)
    max_image_side: int = Field(default=2048, ge=256)
    max_image_pixels: int = Field(default=50_000_000, gt=0)
    preview_max_side: int = Field(default=512, ge=64)
    preview_quality: int = Field(default=80, ge=30, le=95)
    aspect_crop_tolerance: float = Field(default=0.05, ge=0, le=0.2)
    """Насколько (в долях) пропорции результата могут отличаться от исходного
    фото, чтобы их ещё можно было подрезать до точных. Больше — оставляем как есть."""


class CleanupConfig(BaseModel):
    """Уборка файлов в хранилище (раз в час, воркером).
    Успешные генерации хранятся бессрочно."""

    failed_files_retention_days: int = Field(default=7, ge=0)
    """Сколько дней хранить фото неудачных генераций (чтобы разобрать жалобу)."""
    batch_size: int = Field(default=200, ge=1)


class RedisConfig(BaseModel):
    url: RedisDsn = RedisDsn("redis://localhost:6379/0")


class QueueConfig(BaseModel):
    """Очередь генераций.

    arq — задачи уходят в Redis и выполняются отдельным процессом-воркером
    (`arq app.worker.WorkerSettings`). Так в продакшене.
    background — задачи выполняются внутри процесса API, Redis не нужен.
    Только для разработки и тестов: при перезапуске API задачи теряются.
    """

    backend: Literal["arq", "background"] = "arq"
    name: str = "detailing:generations"
    max_concurrent_generations: int = Field(default=4, ge=1)
    job_timeout_seconds: int = Field(default=480, ge=30)
    max_tries: int = Field(default=3, ge=1)
    retry_delay_seconds: int = Field(default=60, ge=1)
    stale_check_interval_minutes: int = Field(default=5, ge=1, le=59)
    stale_pending_minutes: int = Field(default=60, ge=1)
    stale_processing_minutes: int = Field(default=15, ge=1)

    @model_validator(mode="after")
    def _check_stale_thresholds(self) -> Self:
        # Иначе уборщик пометит неудачной генерацию, которая ещё честно выполняется.
        if self.stale_processing_minutes * 60 <= self.job_timeout_seconds:
            raise ValueError(
                "stale_processing_minutes должен быть больше job_timeout_seconds"
            )
        return self


class S3Config(BaseModel):
    """Любое S3-совместимое хранилище: Yandex Object Storage, Selectel, VK Cloud,
    Timeweb, MinIO, AWS. Отличаются только endpoint_url и region."""

    endpoint_url: str | None = None
    region: str = "us-east-1"
    bucket: str | None = None
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    addressing_style: Literal["auto", "virtual", "path"] = "auto"
    key_prefix: str = ""
    """Общий префикс ключей, чтобы в одном бакете жили разные окружения (prod/, stage/)."""
    presigned_url_ttl_seconds: int = Field(default=300, ge=30, le=7 * 24 * 3600)
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    max_attempts: int = Field(default=5, ge=1)
    max_pool_connections: int = Field(default=20, ge=1)


class StorageConfig(BaseModel):
    backend: Literal["local", "s3"] = "local"
    local_path: Path = BASE_DIR / "storage"
    s3: S3Config = S3Config()

    @model_validator(mode="after")
    def _check_s3(self) -> Self:
        if self.backend == "s3":
            missing = [
                name
                for name in ("bucket", "access_key_id", "secret_access_key")
                if getattr(self.s3, name) is None
            ]
            if missing:
                raise ValueError(
                    "Для storage.backend=s3 не заданы: "
                    + ", ".join(
                        f"APP_CONFIG__STORAGE__S3__{n.upper()}" for n in missing
                    )
                )
        return self


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
        # .env общий с Docker Compose: там есть POSTGRES_* и другие переменные
        # без нашего префикса, их нужно пропускать, а не падать.
        extra="ignore",
    )

    app_name: str = "Detailing.Visual"
    run: RunConfig = RunConfig()
    logging: LoggingConfig = LoggingConfig()
    prefix: ApiPrefix = ApiPrefix()
    db: DataBaseConfig
    gemini: GeminiConfig = GeminiConfig()
    generation: GenerationConfig = GenerationConfig()
    storage: StorageConfig = StorageConfig()
    redis: RedisConfig = RedisConfig()
    queue: QueueConfig = QueueConfig()
    cleanup: CleanupConfig = CleanupConfig()
    google: GoogleOAuthConfig
    auth: AuthConfig


settings = Settings()
