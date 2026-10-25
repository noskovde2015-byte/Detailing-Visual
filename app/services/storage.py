import asyncio
import logging
import os
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from aiobotocore.client import AioBaseClient
from aiobotocore.session import get_session
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import S3Config, settings
from app.models.generation_image import ImageRole

logger = logging.getLogger(__name__)

EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# Файлы по ключу никогда не меняются: новый результат всегда пишется под новым ключом.
IMMUTABLE_CACHE_CONTROL = "private, max-age=86400, immutable"

_NOT_FOUND_CODES = {"NoSuchKey", "404", "NotFound"}


class StorageError(Exception):
    """Ошибка хранилища файлов."""


class StorageFileNotFoundError(StorageError):
    """Файла с таким ключом нет."""


class Storage(ABC):
    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def read(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    async def download_url(
        self, key: str, *, content_type: str, content_disposition: str
    ) -> str | None:
        """Временная прямая ссылка на файл или None, если хранилище так не умеет.

        Если ссылка есть, API отдаёт клиенту редирект на неё и не гоняет файл
        через себя. Права доступа проверяются до выдачи ссылки.
        """
        return None

    async def close(self) -> None:
        """Освобождает соединения. Вызывается при остановке API и воркера."""


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):
            raise StorageError("Недопустимый ключ файла")
        return path

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(self._write, path, data)

    async def read(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise StorageFileNotFoundError(key) from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)


class S3Storage(Storage):
    """Хранилище в S3-совместимом сервисе.

    Клиент создаётся при первом обращении и живёт до close(): держит пул
    соединений, чтобы не открывать TLS-соединение на каждый файл.
    """

    def __init__(self, config: S3Config) -> None:
        if (
            config.bucket is None
            or config.access_key_id is None
            or config.secret_access_key is None
        ):
            raise RuntimeError("Не заданы bucket и ключи доступа S3")
        self._config = config
        self._bucket = config.bucket
        self._prefix = config.key_prefix.strip("/")
        self._client: AioBaseClient | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()

    def _full_key(self, key: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise StorageError("Недопустимый ключ файла")
        return f"{self._prefix}/{key}" if self._prefix else key

    async def _get_client(self) -> AioBaseClient:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                config = self._config
                assert config.access_key_id is not None
                assert config.secret_access_key is not None
                boto_config = BotoConfig(
                    region_name=config.region,
                    signature_version="s3v4",
                    s3={"addressing_style": config.addressing_style},
                    retries={"max_attempts": config.max_attempts, "mode": "standard"},
                    connect_timeout=config.connect_timeout_seconds,
                    read_timeout=config.read_timeout_seconds,
                    max_pool_connections=config.max_pool_connections,
                    # Новые версии botocore по умолчанию считают CRC-суммы, которые
                    # многие S3-совместимые сервисы не понимают и отвечают ошибкой.
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                )
                stack = AsyncExitStack()
                self._client = await stack.enter_async_context(
                    get_session().create_client(
                        "s3",
                        endpoint_url=config.endpoint_url,
                        aws_access_key_id=config.access_key_id.get_secret_value(),
                        aws_secret_access_key=config.secret_access_key.get_secret_value(),
                        config=boto_config,
                    )
                )
                self._exit_stack = stack
        return self._client

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        client = await self._get_client()
        await client.put_object(
            Bucket=self._bucket,
            Key=self._full_key(key),
            Body=data,
            ContentType=content_type,
            CacheControl=IMMUTABLE_CACHE_CONTROL,
        )

    async def read(self, key: str) -> bytes:
        client = await self._get_client()
        try:
            response = await client.get_object(
                Bucket=self._bucket, Key=self._full_key(key)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                raise StorageFileNotFoundError(key) from exc
            raise
        async with response["Body"] as stream:
            return await stream.read()

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        # S3 не считает ошибкой удаление несуществующего ключа.
        await client.delete_object(Bucket=self._bucket, Key=self._full_key(key))

    async def download_url(
        self, key: str, *, content_type: str, content_disposition: str
    ) -> str | None:
        client = await self._get_client()
        return await client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": self._full_key(key),
                "ResponseContentType": content_type,
                "ResponseContentDisposition": content_disposition,
            },
            ExpiresIn=self._config.presigned_url_ttl_seconds,
        )

    async def close(self) -> None:
        async with self._lock:
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
            self._exit_stack = None
            self._client = None


def build_image_key(generation_id: UUID, role: ImageRole, content_type: str) -> str:
    extension = EXTENSIONS.get(content_type)
    if extension is None:
        raise StorageError(f"Неподдерживаемый тип изображения: {content_type}")
    return f"generations/{generation_id}/{role.value}{extension}"


@lru_cache
def get_storage() -> Storage:
    match settings.storage.backend:
        case "local":
            return LocalStorage(settings.storage.local_path)
        case "s3":
            return S3Storage(settings.storage.s3)
        case backend:
            raise RuntimeError(f"Неизвестный бэкенд хранилища: {backend}")
