import httpx
import pytest
from pydantic import ValidationError

from app.core.config import StorageConfig
from app.services.storage import (
    IMMUTABLE_CACHE_CONTROL,
    S3Storage,
    StorageError,
    StorageFileNotFoundError,
)
from tests.s3_server import raw_client, s3_config

pytestmark = pytest.mark.anyio

KEY = "generations/abc/car.jpg"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_save_and_read(s3_storage: S3Storage) -> None:
    await s3_storage.save(KEY, b"jpeg-bytes", "image/jpeg")
    assert await s3_storage.read(KEY) == b"jpeg-bytes"


async def test_object_metadata(
    s3_storage: S3Storage, s3_endpoint: str, s3_bucket: str
) -> None:
    await s3_storage.save(KEY, b"jpeg-bytes", "image/jpeg")
    async with raw_client(s3_endpoint) as client:
        head = await client.head_object(Bucket=s3_bucket, Key=KEY)
    assert head["ContentType"] == "image/jpeg"
    assert head["CacheControl"] == IMMUTABLE_CACHE_CONTROL


async def test_key_prefix(s3_endpoint: str, s3_bucket: str) -> None:
    storage = S3Storage(s3_config(s3_endpoint, s3_bucket, key_prefix="/prod/"))
    try:
        await storage.save(KEY, b"data", "image/jpeg")
        assert await storage.read(KEY) == b"data"
    finally:
        await storage.close()

    async with raw_client(s3_endpoint) as client:
        listed = await client.list_objects_v2(Bucket=s3_bucket)
    assert [item["Key"] for item in listed["Contents"]] == [f"prod/{KEY}"]


async def test_missing_file(s3_storage: S3Storage) -> None:
    with pytest.raises(StorageFileNotFoundError):
        await s3_storage.read("generations/nope/car.jpg")


async def test_delete_is_idempotent(s3_storage: S3Storage) -> None:
    await s3_storage.save(KEY, b"data", "image/jpeg")
    await s3_storage.delete(KEY)
    await s3_storage.delete(KEY)
    with pytest.raises(StorageFileNotFoundError):
        await s3_storage.read(KEY)


@pytest.mark.parametrize("key", ["", "/abs/key", "a/../b", "../escape"])
async def test_invalid_key_rejected(s3_storage: S3Storage, key: str) -> None:
    with pytest.raises(StorageError):
        await s3_storage.save(key, b"data", "image/jpeg")


async def test_presigned_url_serves_file_with_headers(s3_storage: S3Storage) -> None:
    await s3_storage.save(KEY, b"jpeg-bytes", "image/jpeg")
    url = await s3_storage.download_url(
        KEY,
        content_type="image/jpeg",
        content_disposition='attachment; filename="detailing-abc-car.jpg"',
    )
    assert url is not None
    assert "X-Amz-Expires=300" in url

    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["content-disposition"] == (
        'attachment; filename="detailing-abc-car.jpg"'
    )


async def test_client_is_recreated_after_close(s3_storage: S3Storage) -> None:
    await s3_storage.save(KEY, b"data", "image/jpeg")
    await s3_storage.close()
    assert await s3_storage.read(KEY) == b"data"


def test_s3_backend_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="BUCKET"):
        StorageConfig(backend="s3")
