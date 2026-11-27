import pytest

from app.config import normalize_database_url


@pytest.mark.parametrize("given, expected", [
    # Neon
    ("postgresql://user:pw@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
     "postgresql+psycopg://user:pw@ep-x-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"),
    # Render / Heroku style
    ("postgres://user:pw@dpg-abc.singapore-postgres.render.com/vaani",
     "postgresql+psycopg://user:pw@dpg-abc.singapore-postgres.render.com/vaani"),
    # Already explicit, or another database: unchanged
    ("postgresql+psycopg://vaani:vaani@localhost:5432/vaani", "postgresql+psycopg://vaani:vaani@localhost:5432/vaani"),
    ("sqlite+pysqlite:///:memory:", "sqlite+pysqlite:///:memory:"),
    ("  postgresql://a:b@h/d  ", "postgresql+psycopg://a:b@h/d"),
])
def test_normalize_database_url(given, expected):
    assert normalize_database_url(given) == expected
