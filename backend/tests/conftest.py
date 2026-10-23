import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://radar:radar@localhost:5432/radar_test")


@pytest.fixture(scope="session")
def engine():
    from radar.models import Base

    try:
        eng = create_engine(TEST_DB)
        with eng.connect():
            pass
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test database unavailable: {exc}")
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    from radar.cli import seed_reference

    with engine.begin() as conn:
        tables = ", ".join(t for t in ("links", "evidence", "finding_events", "findings", "import_batches",
                                       "collector_runs", "keywords", "whitelist", "operators"))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_reference(s)
    s.commit()
    yield s
    s.rollback()
    s.close()
