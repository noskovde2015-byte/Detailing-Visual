import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.db.db_helper import db_helper
from app.models.generation import Generation
from app.models.generation_image import ImageRole
from app.schemas.generation import (
    GenerationList,
    GenerationParams,
    GenerationQuota,
    GenerationRead,
)
from app.services.generation_limits import GenerationLimitExceededError, get_quota
from app.services.generation_queue import (
    BackgroundGenerationQueue,
    GenerationQueue,
    QueueUnavailableError,
)
from app.services.generation_rules import (
    GenerationInputError,
    validate_generation_input,
)
from app.services.generation_runner import (
    QUEUE_UNAVAILABLE_ERROR,
    mark_failed,
    run_generation,
)
from app.services.generations import (
    create_generation,
    get_user_generation,
    list_user_generations,
    quota_to_schema,
    to_read,
)
from app.services.image_generator import (
    configured_model_name,
    get_image_generator,
)
from app.services.images import InvalidImageError, ProcessedImage, process_upload
from app.services.storage import StorageFileNotFoundError, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.prefix.generations_prefix, tags=["generations"])

READ_CHUNK_SIZE = 1024 * 1024


async def _read_limited(upload: UploadFile, field: str) -> bytes:
    """Читает файл кусками и прерывается, как только превышен лимит,
    чтобы не держать в памяти гигабайтный файл целиком."""
    max_bytes = settings.generation.max_upload_bytes
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(READ_CHUNK_SIZE):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(f"Файл «{field}» больше {max_bytes // (1024 * 1024)} МБ"),
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _process(upload: UploadFile, field: str) -> ProcessedImage:
    raw = await _read_limited(upload, field)
    try:
        return await asyncio.to_thread(process_upload, raw)
    except InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Файл «{field}»: {exc}",
        ) from None


def _parse_params(raw: str) -> GenerationParams:
    try:
        return GenerationParams.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False, include_context=False),
        ) from None


async def _execute(generation_id: uuid.UUID) -> None:
    await run_generation(
        generation_id,
        session_factory=db_helper.session_factory,
        generator=get_image_generator(),
        storage=get_storage(),
        timeout_seconds=settings.queue.job_timeout_seconds,
    )


def get_generation_queue(
    request: Request, background_tasks: BackgroundTasks
) -> GenerationQueue:
    if settings.queue.backend == "background":
        return BackgroundGenerationQueue(background_tasks, _execute)
    return request.app.state.generation_queue


QueueDep = Annotated[GenerationQueue, Depends(get_generation_queue)]


@router.post(
    "",
    response_model=GenerationRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Создать генерацию",
)
async def create(
    user: CurrentUser,
    session: SessionDep,
    queue: QueueDep,
    response: Response,
    car: Annotated[UploadFile, File(description="Фото автомобиля")],
    params: Annotated[
        str,
        Form(description="JSON с параметрами (GenerationParams)"),
    ] = "{}",
    film: Annotated[
        UploadFile | None,
        File(description="Образец плёнки. Не вместе с film_color в params"),
    ] = None,
    wheel: Annotated[UploadFile | None, File(description="Фото дисков")] = None,
) -> GenerationRead:
    parsed = _parse_params(params)

    uploads: dict[ImageRole, UploadFile] = {ImageRole.CAR: car}
    if film is not None:
        uploads[ImageRole.FILM] = film
    if wheel is not None:
        uploads[ImageRole.WHEEL] = wheel

    try:
        validate_generation_input(parsed, uploads.keys())
    except GenerationInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None

    processed = dict(
        zip(
            uploads.keys(),
            await asyncio.gather(
                *(_process(upload, role.value) for role, upload in uploads.items())
            ),
            strict=True,
        )
    )

    try:
        generation = await create_generation(
            session,
            get_storage(),
            user,
            parsed,
            processed,
            model_name=configured_model_name(),
        )
    except GenerationLimitExceededError as exc:
        headers = {}
        if exc.quota.resets_at is not None:
            seconds = max(
                int((exc.quota.resets_at - datetime.now(UTC)).total_seconds()), 1
            )
            headers["Retry-After"] = str(seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Лимит генераций исчерпан",
                "quota": quota_to_schema(exc.quota).model_dump(mode="json"),
            },
            headers=headers,
        ) from None

    try:
        await queue.enqueue(generation.id)
    except QueueUnavailableError:
        logger.exception("Не удалось поставить генерацию %s в очередь", generation.id)
        # Генерация уже сохранена и заняла лимит. Помечаем её неудачной,
        # чтобы лимит вернулся, а не висел pending до уборщика.
        await mark_failed(
            db_helper.session_factory, generation.id, QUEUE_UNAVAILABLE_ERROR
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=QUEUE_UNAVAILABLE_ERROR,
        ) from None

    response.headers["Location"] = (
        f"{settings.prefix.api_prefix}{settings.prefix.generations_prefix}"
        f"/{generation.id}"
    )
    return to_read(generation)


@router.get("", response_model=GenerationList, summary="История генераций")
async def list_generations(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> GenerationList:
    rows, total = await list_user_generations(session, user.id, limit, offset)
    return GenerationList(
        items=[to_read(row) for row in rows], total=total, limit=limit, offset=offset
    )


@router.get("/quota", response_model=GenerationQuota, summary="Оставшийся лимит")
async def quota(user: CurrentUser, session: SessionDep) -> GenerationQuota:
    return quota_to_schema(await get_quota(session, user.id, user.plan))


@router.get("/{generation_id}", response_model=GenerationRead, summary="Статус")
async def read(
    generation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> GenerationRead:
    generation = await get_user_generation(session, user.id, generation_id)
    if generation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Генерация не найдена")
    return to_read(generation)


@router.get(
    "/{generation_id}/images/{role}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
    summary="Изображение генерации (вход или результат)",
)
async def image(
    generation_id: uuid.UUID,
    role: ImageRole,
    user: CurrentUser,
    session: SessionDep,
    download: bool = False,
) -> Response:
    generation = await get_user_generation(session, user.id, generation_id)
    if generation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Генерация не найдена")
    return await generation_image_response(generation, role, download=download)


async def generation_image_response(
    generation: Generation, role: ImageRole, *, download: bool
) -> Response:
    stored = next((img for img in generation.images if img.role == role), None)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")

    try:
        data = await get_storage().read(stored.storage_key)
    except StorageFileNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Изображение не найдено"
        ) from None

    extension = stored.storage_key.rsplit(".", 1)[-1]
    disposition = "attachment" if download else "inline"
    filename = f"detailing-{generation.id}-{role.value}.{extension}"
    return Response(
        content=data,
        media_type=stored.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=86400, immutable",
        },
    )
