from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent.run_events import list_run_events, record_run_event
from db.models import Base


def test_record_and_list_run_events(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'events.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    @contextmanager
    def temp_session_scope():
        session = session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("agent.run_events.session_scope", temp_session_scope)

    record_run_event(
        event="match",
        message="Matching B0EVENT001 (1/2)",
        run_id=42,
        job_id="job-42",
        stage="match",
        asin="B0EVENT001",
        index=1,
        total=2,
        payload={"source": "pipeline"},
    )

    events = list_run_events(run_id=42)

    assert len(events) == 1
    assert events[0]["run_id"] == 42
    assert events[0]["job_id"] == "job-42"
    assert events[0]["event"] == "match"
    assert events[0]["stage"] == "match"
    assert events[0]["asin"] == "B0EVENT001"
    assert events[0]["index"] == 1
    assert events[0]["total"] == 2
    assert events[0]["payload"]["source"] == "pipeline"
