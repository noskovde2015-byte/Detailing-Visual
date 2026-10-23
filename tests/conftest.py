import os

# Тесты не должны зависеть от личного .env: задаём безопасные значения по умолчанию
# до того, как какой-либо тест импортирует app.core.config.
os.environ.setdefault(
    "APP_CONFIG__DB__URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("APP_CONFIG__GOOGLE__CLIENT_ID", "test-client-id")
os.environ.setdefault("APP_CONFIG__GOOGLE__CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("APP_CONFIG__AUTH__SECRET_KEY", "test-secret-key-not-for-production")
