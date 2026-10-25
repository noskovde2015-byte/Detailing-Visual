# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.13

# ---------- сборка зависимостей ----------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Poetry ставим отдельно от приложения: в итоговый образ он не попадёт.
RUN pip install "poetry==2.5.1" \
    && python -m venv /opt/venv

WORKDIR /build
# Сначала только файлы зависимостей: этот слой пересобирается лишь при их
# изменении, а не при каждой правке кода.
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --only main --no-root


# ---------- итоговый образ ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# Код принадлежит root и только читается: процесс приложения не может его изменить.
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# Единственная папка, куда приложение пишет. Владелец задаётся здесь, и именованный
# том Docker при первом создании унаследует его.
RUN mkdir -p /app/storage && chown app:app /app/storage

USER app

EXPOSE 8000

# Одна копия API на контейнер: масштабируемся числом контейнеров.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
