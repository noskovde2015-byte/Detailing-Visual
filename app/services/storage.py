import asyncio
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import settings
from app.models.generation_image import ImageRole

EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


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
        case backend:
            raise RuntimeError(f"Неизвестный бэкенд хранилища: {backend}")
