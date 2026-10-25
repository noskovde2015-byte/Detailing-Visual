import os

_test_db_url = os.environ.get("TEST_DATABASE_URL")
if _test_db_url:
    os.environ["APP_CONFIG__DB__URL"] = _test_db_url

os.environ.setdefault(
    "APP_CONFIG__DB__URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("APP_CONFIG__GOOGLE__CLIENT_ID", "test-client-id")
os.environ.setdefault("APP_CONFIG__GOOGLE__CLIENT_SECRET", "test-client-secret")
os.environ.setdefault(
    "APP_CONFIG__AUTH__SECRET_KEY", "test-secret-key-not-for-production"
)
os.environ["APP_CONFIG__GENERATION__BACKEND"] = "fake"
os.environ["APP_CONFIG__GENERATION__FAKE_DELAY_SECONDS"] = "0"
os.environ["APP_CONFIG__QUEUE__BACKEND"] = "background"
