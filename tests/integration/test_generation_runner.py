import asyncio
import io
import uuid
from collections.abc import Sequence
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import update

from app.db.db_helper import db_helper
from app.models.generation import Generation, GenerationStatus
from app.models.generation_image import ImageRole
from app.schemas.generation import GenerationParams
from app.services.generation_runner import (
    INTERRUPTED_ERROR,
    TIMEOUT_ERROR,
    GenerationOutcome,
    fail_stale_generations,
    run_generation,
)
from app.services.generations import create_generation
from app.services.image_generator import (
    GenerationTemporaryError,
    ImageData,
    ImageGenerator,
)
from app.services.images import process_upload
from app.services.storage import LocalStorage

pytestmark = pytest.mark.anyio


class TemporaryFailure(ImageGenerator):
    name = "temporary-failure"

    async def generate(
        self,
        prompt: str,
        images: Sequence[ImageData],
        *,
        aspect_ratio: str | None = None,
    ) -> ImageData:
        raise GenerationTemporaryError("Сервис генерации временно перегружен.")


class Slow(ImageGenerator):
    name = "slow"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(
        self,
        prompt: str,
        images: Sequence[ImageData],
        *,
        aspect_ratio: str | None = None,
    ) -> ImageData:
        self.started.set()
        await asyncio.sleep(30)
        return images[0]


@pytest.fixture
async def generation_id(make_user, storage: LocalStorage) -> uuid.UUID:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 20, 30)).save(buffer, format="JPEG")
    user = await make_user()
    async with db_helper.session_factory() as session:
        generation = await create_generation(
            session,
            storage,
            user,
            GenerationParams(antichrome=True),
            {ImageRole.CAR: process_upload(buffer.getvalue())},
            model_name="test",
        )
    return generation.id


async def _get(generation_id: uuid.UUID) -> Generation:
    async with db_helper.session_factory() as session:
        generation = await session.get(Generation, generation_id)
        assert generation is not None
        return generation


async def _run(generation_id, generator, storage, **kwargs) -> GenerationOutcome:
    return await run_generation(
        generation_id,
        session_factory=db_helper.session_factory,
        generator=generator,
        storage=storage,
        **kwargs,
    )


async def test_temporary_error_is_released_for_retry(
    generation_id: uuid.UUID, storage: LocalStorage
) -> None:
    outcome = await _run(generation_id, TemporaryFailure(), storage, allow_retry=True)

    assert outcome is GenerationOutcome.RETRY
    generation = await _get(generation_id)
    assert generation.status == GenerationStatus.PENDING
    assert generation.started_at is None
    assert generation.error is None


async def test_temporary_error_on_last_try_fails(
    generation_id: uuid.UUID, storage: LocalStorage
) -> None:
    outcome = await _run(generation_id, TemporaryFailure(), storage, allow_retry=False)

    assert outcome is GenerationOutcome.FAILED
    generation = await _get(generation_id)
    assert generation.status == GenerationStatus.FAILED
    assert generation.error == "Сервис генерации временно перегружен."


async def test_timeout_marks_failed(
    generation_id: uuid.UUID, storage: LocalStorage
) -> None:
    outcome = await _run(generation_id, Slow(), storage, timeout_seconds=0.05)

    assert outcome is GenerationOutcome.FAILED
    generation = await _get(generation_id)
    assert generation.status == GenerationStatus.FAILED
    assert generation.error == TIMEOUT_ERROR


async def test_cancellation_returns_job_to_pending(
    generation_id: uuid.UUID, storage: LocalStorage
) -> None:
    generator = Slow()
    task = asyncio.create_task(_run(generation_id, generator, storage))
    await generator.started.wait()
    assert (await _get(generation_id)).status == GenerationStatus.PROCESSING

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    generation = await _get(generation_id)
    assert generation.status == GenerationStatus.PENDING
    assert generation.started_at is None


async def test_second_run_is_skipped(
    generation_id: uuid.UUID, storage: LocalStorage
) -> None:
    from app.services.fake_generator import FakeImageGenerator

    generator = FakeImageGenerator(delay_seconds=0)
    assert await _run(generation_id, generator, storage) is GenerationOutcome.DONE
    assert await _run(generation_id, generator, storage) is GenerationOutcome.SKIPPED


async def test_stale_thresholds_differ_for_pending_and_processing(
    generation_id: uuid.UUID,
) -> None:
    async def sweep() -> int:
        return await fail_stale_generations(
            db_helper.session_factory,
            pending_older_than=timedelta(minutes=60),
            processing_older_than=timedelta(minutes=15),
        )

    async def shift_back(**values: object) -> None:
        async with db_helper.session_factory() as session:
            await session.execute(
                update(Generation)
                .where(Generation.id == generation_id)
                .values(**values)
            )
            await session.commit()

    # pending 30 минут: ещё ждёт своей очереди, трогать нельзя.
    await shift_back(created_at=Generation.created_at - timedelta(minutes=30))
    assert await sweep() == 0

    # processing 30 минут: исполнитель явно умер.
    await shift_back(
        status=GenerationStatus.PROCESSING.value,
        started_at=Generation.created_at,
    )
    assert await sweep() == 1
    generation = await _get(generation_id)
    assert generation.status == GenerationStatus.FAILED
    assert generation.error == INTERRUPTED_ERROR
