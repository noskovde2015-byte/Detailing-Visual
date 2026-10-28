"""Пауза генераций при сбое, который касается всех задач сразу.

Если Google отвечает «регион не поддерживается», «нет оплаты» или недоступны оба
выходных узла, следующая задача упадёт так же. Поэтому вместо того чтобы
проваливать задачи одну за другой (и слать в Google заведомо отклоняемые
запросы), воркер ставит генерации на паузу:

- задачи остаются в pending и ждут; новые API не принимает (баланс не занимается);
- администратор видит причину в админке и после исправления жмёт «Возобновить»;
- при обрыве связи воркер сам проверяет её раз в минуту и возобновляет сам;
- если пауза затянулась, ждущие задачи завершит уборщик зависших
  (stale_pending_minutes) — генерации вернутся пользователям на баланс.

Состояние паузы хранится в Redis: его видят и все воркеры, и API.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.generation import Generation, GenerationStatus
from app.services.generation_queue import GenerationQueue
from app.services.image_generator import OutageReason

logger = logging.getLogger(__name__)

PAUSED_MESSAGE = (
    "Генерация временно недоступна: мы уже разбираемся. "
    "Баланс не списан, попробуйте чуть позже."
)


@dataclass(frozen=True, slots=True)
class OutageText:
    title: str
    hint: str


OUTAGE_TEXTS: dict[OutageReason, OutageText] = {
    OutageReason.REGION: OutageText(
        "Google отклоняет запросы из нашей страны",
        "Запрос ушёл не через зарубежный узел или узел в стране, где Gemini API "
        'не работает. Проверьте: docker compose exec worker python -c "import '
        "httpx; print(httpx.get('https://ipinfo.io/country').text)\" — должно быть "
        "не RU. Исправьте узлы в deploy/xray/client.json и нажмите «Возобновить».",
    ),
    OutageReason.BILLING: OutageText(
        "Закончились деньги на счёте Google",
        "Пополните предоплату в AI Studio → Billing (заходить только через VPN "
        "в той же стране, что и узлы) и нажмите «Возобновить».",
    ),
    OutageReason.QUOTA: OutageText(
        "Исчерпана квота или лимит расходов Google",
        "Проверьте Spend cap и лимиты в AI Studio. Достигнутый месячный лимит "
        "расходов держится до следующего месяца, если его не поднять. "
        "После исправления нажмите «Возобновить».",
    ),
    OutageReason.AUTH: OutageText(
        "Google не принимает ключ API",
        "Проверьте APP_CONFIG__GEMINI__API_KEY и почту Google-аккаунта: проект "
        "или ключ могли заблокировать. После замены ключа перезапустите воркер "
        "(docker compose up -d worker) и нажмите «Возобновить».",
    ),
    OutageReason.MODEL: OutageText(
        "Модель не найдена",
        "Проверьте APP_CONFIG__GEMINI__MODEL: модель могли переименовать или "
        "отключить. После исправления перезапустите воркер и нажмите «Возобновить».",
    ),
    OutageReason.NETWORK: OutageText(
        "Нет связи с Google: недоступны оба узла",
        "Связь проверяется раз в минуту, генерации продолжатся сами. Если долго не "
        "восстанавливается: docker compose logs xray-client, на узлах — "
        "systemctl status xray.",
    ),
    OutageReason.MANUAL: OutageText(
        "Приостановлено администратором",
        "Новые генерации не принимаются, ждущие — ждут. Нажмите «Возобновить», "
        "когда будете готовы.",
    ),
}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PauseState:
    reason: OutageReason
    detail: str
    since: datetime
    """Когда генерации встали."""
    last_error_at: datetime
    """Когда причина подтвердилась последний раз."""
    paused_by: str | None = None
    """Кто поставил паузу вручную (email администратора)."""

    def to_json(self) -> str:
        return json.dumps(
            {
                "reason": self.reason.value,
                "detail": self.detail,
                "since": self.since.isoformat(),
                "last_error_at": self.last_error_at.isoformat(),
                "paused_by": self.paused_by,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "PauseState":
        data = json.loads(raw)
        return cls(
            reason=OutageReason(data["reason"]),
            detail=data.get("detail") or "",
            since=datetime.fromisoformat(data["since"]),
            last_error_at=datetime.fromisoformat(data["last_error_at"]),
            paused_by=data.get("paused_by"),
        )


class GenerationPause:
    def __init__(self, redis: Redis, queue_name: str) -> None:
        self._redis = redis
        self._key = f"{queue_name}:pause"

    async def get(self) -> PauseState | None:
        raw = await self._redis.get(self._key)
        if raw is None:
            return None
        try:
            return PauseState.from_json(raw)
        except (ValueError, KeyError, TypeError):
            # Битое значение не должно навсегда остановить генерации,
            # но и молча продолжать нельзя: считаем паузой с понятной причиной.
            logger.exception("Не разобрал состояние паузы: %r", raw)
            now = _now()
            return PauseState(OutageReason.MANUAL, "повреждённое состояние", now, now)

    async def is_paused(self) -> bool:
        return bool(await self._redis.exists(self._key))

    async def pause(
        self, reason: OutageReason, detail: str = "", *, paused_by: str | None = None
    ) -> PauseState:
        """Ставит паузу или обновляет причину уже стоящей.

        Время начала сохраняется от первого сбоя: по нему видно, сколько
        генерации уже стоят.
        """
        now = _now()
        state = PauseState(reason, detail, now, now, paused_by)
        if await self._redis.set(self._key, state.to_json(), nx=True):
            logger.error(
                "ГЕНЕРАЦИИ ПРИОСТАНОВЛЕНЫ: причина %s. %s", reason, detail or ""
            )
            return state

        current = await self.get()
        if current is not None:
            state = PauseState(reason, detail, current.since, now, paused_by)
            if current.reason != reason:
                logger.error(
                    "Пауза генераций: причина сменилась %s → %s. %s",
                    current.reason,
                    reason,
                    detail,
                )
        await self._redis.set(self._key, state.to_json())
        return state

    async def resume(self) -> bool:
        """Снимает паузу. False — паузы и не было."""
        removed = await self._redis.delete(self._key)
        if removed:
            logger.warning("Генерации возобновлены")
        return bool(removed)


async def pending_generation_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(Generation.id)
        .where(Generation.status == GenerationStatus.PENDING.value)
        .order_by(Generation.created_at)
    )
    return list(rows)


async def pending_summary(session: AsyncSession) -> tuple[int, datetime | None]:
    """Сколько генераций ждёт и с какого времени ждёт самая старая."""
    count, oldest = (
        await session.execute(
            select(func.count(), func.min(Generation.created_at)).where(
                Generation.status == GenerationStatus.PENDING.value
            )
        )
    ).one()
    return count, oldest


async def resume_generations(
    pause: GenerationPause,
    session_factory: async_sessionmaker[AsyncSession],
    queue: GenerationQueue,
) -> int:
    """Снимает паузу и заново ставит в очередь все ждущие генерации.

    Пока стояла пауза, воркер завершал их задачи в arq, не выполняя, так что
    в очереди их больше нет. Повторная постановка безопасна: генерацию
    выполнит только тот, кто первым переведёт её из pending в processing.
    """
    await pause.resume()
    async with session_factory() as session:
        ids = await pending_generation_ids(session)

    tag = _now().strftime("%Y%m%d%H%M%S%f")
    requeued = 0
    for generation_id in ids:
        try:
            await queue.enqueue(generation_id, tag=f"resume-{tag}")
        except Exception:
            # Не поставили — подберёт уборщик зависших и вернёт на баланс.
            logger.exception("Не удалось вернуть в очередь генерацию %s", generation_id)
        else:
            requeued += 1
    if ids:
        logger.warning("Возвращено в очередь генераций: %d из %d", requeued, len(ids))
    return requeued
