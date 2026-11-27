import os

# Must be set before the app is imported: tests run on an in-memory SQLite database.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["STT_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
