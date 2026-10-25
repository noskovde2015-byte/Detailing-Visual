"""Тестовый S3 на базе moto: настоящий HTTP-сервер с API S3 в отдельном потоке."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from aiobotocore.session import get_session
from pydantic import SecretStr

from app.core.config import S3Config
from app.services.storage import S3Storage

ACCESS_KEY = "testing"
SECRET_KEY = "testing"
REGION = "us-east-1"


@pytest.fixture(scope="session")
def s3_endpoint() -> Iterator[str]:
    moto_server = pytest.importorskip("moto.server")
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@asynccontextmanager
async def raw_client(endpoint: str) -> AsyncIterator:
    async with get_session().create_client(
        "s3",
        endpoint_url=endpoint,
        region_name=REGION,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    ) as client:
        yield client


def s3_config(endpoint: str, bucket: str, **overrides: object) -> S3Config:
    return S3Config(
        endpoint_url=endpoint,
        region=REGION,
        bucket=bucket,
        access_key_id=SecretStr(ACCESS_KEY),
        secret_access_key=SecretStr(SECRET_KEY),
        addressing_style="path",
        **overrides,
    )


@pytest.fixture
async def s3_bucket(s3_endpoint: str) -> str:
    bucket = f"test-{uuid4().hex[:12]}"
    async with raw_client(s3_endpoint) as client:
        await client.create_bucket(Bucket=bucket)
    return bucket


@pytest.fixture
async def s3_storage(s3_endpoint: str, s3_bucket: str) -> AsyncIterator[S3Storage]:
    storage = S3Storage(s3_config(s3_endpoint, s3_bucket))
    yield storage
    await storage.close()
