"""Выгружает OpenAPI-схему API в frontend/openapi.json.

По ней фронт генерирует типы (npm run gen:api), поэтому изменение API сразу
видно в TypeScript. После изменения схем бэкенда:

    poetry run python -m scripts.export_openapi
    cd frontend && npm run gen:api
"""

import json
from pathlib import Path

from app.core.config import BASE_DIR
from app.main import app

OUTPUT = BASE_DIR / "frontend" / "openapi.json"


def main() -> None:
    schema = app.openapi()
    text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    Path(OUTPUT).write_text(text, encoding="utf-8")
    print(f"OpenAPI-схема записана в {OUTPUT}")


if __name__ == "__main__":
    main()
