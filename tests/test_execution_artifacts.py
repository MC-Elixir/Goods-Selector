from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.migrate import install_sqlite_foreign_keys
from db.models import ArtifactManifest, Base, RunLog
from execution.artifacts import ArtifactFile, ArtifactSetManager
from execution.models import StageContext
from execution.repository import ExecutionRepository
from pipeline.recoverable import _artifact_result_valid


@pytest.fixture
def artifact_store(tmp_path):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    install_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    @contextmanager
    def session_scope():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with session_scope() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US")
        session.add(run)
        session.flush()
        run_id = run.id
    repo = ExecutionRepository(session_context=session_scope)
    node_id = repo.ensure_node(
        run_id=run_id,
        scope_type="run",
        scope_key="run",
        stage="export",
        input_snapshot={"records": ["A"]},
    )
    claim = repo.claim(node_id, worker_id="artifact-worker")
    context = StageContext(
        node_id=claim.node_id,
        attempt_id=claim.attempt_id,
        run_id=claim.run_id,
        asin=None,
        attempt_no=claim.attempt_no,
        generation=claim.generation,
        lease_token=claim.lease_token,
        worker_id=claim.worker_id,
        deadline=None,
        cancel_check=None,
        heartbeat=lambda: None,
        input_snapshot=claim.input_snapshot,
    )
    return ArtifactSetManager(session_context=session_scope), session_scope, context, tmp_path


def test_artifact_set_publishes_all_files_and_verifies_hashes(artifact_store):
    manager, _session_scope, context, tmp_path = artifact_store
    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    first = staging / "data.json"
    second = staging / "data.xlsx"
    first.write_text('{"ok": true}', encoding="utf-8")
    second.write_bytes(b"xlsx-content")

    manifests = manager.publish(
        context=context,
        artifact_set_id="set-1",
        files=[
            ArtifactFile("json", "json", first, final / "data.json"),
            ArtifactFile("excel", "xlsx", second, final / "data.xlsx"),
        ],
    )
    assert {row["status"] for row in manifests} == {"committed"}
    assert (final / "data.json").read_text(encoding="utf-8") == '{"ok": true}'
    assert manager.reconcile("set-1") is not None
    node = {
        "output_snapshot": {
            "artifact_set_id": "set-1",
            "manifests": manifests,
        }
    }
    assert _artifact_result_valid(manager, node) is True
    (final / "data.json").unlink()
    assert _artifact_result_valid(manager, node) is False
    assert {row["status"] for row in manager.list_set("set-1")} == {"invalid"}


def test_partial_artifact_set_never_commits(artifact_store):
    manager, _session_scope, context, tmp_path = artifact_store
    staging = tmp_path / "partial"
    staging.mkdir()
    first = staging / "only.json"
    first.write_text("[]", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        manager.publish(
            context=context,
            artifact_set_id="partial-set",
            files=[
                ArtifactFile("json", "json", first, tmp_path / "final" / "data.json"),
                ArtifactFile(
                    "excel", "xlsx", staging / "missing.xlsx", tmp_path / "final" / "data.xlsx"
                ),
            ],
        )
    assert {row["status"] for row in manager.list_set("partial-set")} == {"writing"}
    assert manager.reconcile("partial-set") is None
    assert {row["status"] for row in manager.list_set("partial-set")} == {"invalid"}


def test_reconcile_finishes_rename_before_manifest_commit(artifact_store):
    manager, session_scope, context, tmp_path = artifact_store
    final = tmp_path / "published.json"
    final.write_text("stable", encoding="utf-8")
    digest = sha256(b"stable").hexdigest()
    with session_scope() as session:
        session.add(ArtifactManifest(
            run_id=context.run_id,
            node_id=context.node_id,
            attempt_id=context.attempt_id,
            artifact_set_id="crash-set",
            logical_name="json",
            artifact_type="json",
            final_path=str(final),
            size_bytes=6,
            sha256=digest,
            status="writing",
            created_at=datetime.utcnow(),
        ))
    reconciled = manager.reconcile("crash-set")
    assert reconciled[0]["status"] == "committed"
    assert reconciled[0]["committed_at"] is not None
