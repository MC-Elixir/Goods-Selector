"""Crash-recoverable publication for export artifact sets."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session

from db.models import ArtifactManifest
from execution.models import StageContext


@dataclass(frozen=True)
class ArtifactFile:
    logical_name: str
    artifact_type: str
    temporary_path: Path
    final_path: Path


class ArtifactSetManager:
    def __init__(self, session_factory=None, *, session_context=None) -> None:
        if session_factory is None and session_context is None:
            from db.session import SessionLocal
            session_factory = SessionLocal
        self._session_factory = session_factory
        self._session_context = session_context

    @contextmanager
    def _session(self) -> Iterator[Session]:
        if self._session_context is not None:
            with self._session_context() as session:
                yield session
            return
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def reconcile(self, artifact_set_id: str) -> list[dict] | None:
        """Commit a publish-after-rename crash, or reject an invalid set."""
        with self._session() as session:
            rows = session.query(ArtifactManifest).filter_by(
                artifact_set_id=artifact_set_id
            ).order_by(ArtifactManifest.id).all()
            if not rows:
                return None
            valid = all(self._row_is_valid(row) for row in rows)
            if valid:
                committed_at = datetime.utcnow()
                for row in rows:
                    row.status = "committed"
                    row.committed_at = row.committed_at or committed_at
                session.flush()
                return [self._manifest_dict(row) for row in rows]
            for row in rows:
                row.status = "invalid"
                row.committed_at = None
            return None

    def publish(
        self,
        *,
        context: StageContext,
        artifact_set_id: str,
        files: list[ArtifactFile],
    ) -> list[dict]:
        if not files:
            raise ValueError("artifact set must contain at least one file")
        logical_names = [item.logical_name for item in files]
        if len(set(logical_names)) != len(logical_names):
            raise ValueError("artifact logical names must be unique within a set")

        # Register intent before touching final paths.
        with self._session() as session:
            existing = {
                row.logical_name: row
                for row in session.query(ArtifactManifest).filter_by(
                    artifact_set_id=artifact_set_id
                ).all()
            }
            for item in files:
                row = existing.get(item.logical_name)
                if row is None:
                    row = ArtifactManifest(
                        run_id=context.run_id,
                        node_id=context.node_id,
                        attempt_id=context.attempt_id,
                        artifact_set_id=artifact_set_id,
                        logical_name=item.logical_name,
                        artifact_type=item.artifact_type,
                        final_path=str(item.final_path),
                    )
                    session.add(row)
                row.run_id = context.run_id
                row.node_id = context.node_id
                row.attempt_id = context.attempt_id
                row.artifact_type = item.artifact_type
                row.temporary_path = str(item.temporary_path)
                row.final_path = str(item.final_path)
                row.size_bytes = None
                row.sha256 = None
                row.status = "writing"
                row.committed_at = None
            for logical_name, row in existing.items():
                if logical_name not in set(logical_names):
                    row.status = "invalid"

        measurements: dict[str, tuple[int, str]] = {}
        for item in files:
            if not item.temporary_path.is_file():
                raise FileNotFoundError(item.temporary_path)
            self._fsync_file(item.temporary_path)
            measurements[item.logical_name] = (
                item.temporary_path.stat().st_size,
                self._sha256(item.temporary_path),
            )

        # Persist expected hashes before rename. A crash after rename can now be
        # reconciled without regenerating or guessing whether the set is valid.
        with self._session() as session:
            rows = session.query(ArtifactManifest).filter_by(
                artifact_set_id=artifact_set_id, status="writing"
            ).all()
            by_name = {row.logical_name: row for row in rows}
            for item in files:
                row = by_name[item.logical_name]
                row.size_bytes, row.sha256 = measurements[item.logical_name]

        touched_dirs: set[Path] = set()
        for item in files:
            item.final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(item.temporary_path, item.final_path)
            touched_dirs.add(item.final_path.parent)
        for directory in touched_dirs:
            self._fsync_directory(directory)

        manifests = self.reconcile(artifact_set_id)
        if manifests is None:
            raise RuntimeError(f"artifact set failed integrity verification: {artifact_set_id}")
        return manifests

    def list_set(self, artifact_set_id: str) -> list[dict]:
        with self._session() as session:
            rows = session.query(ArtifactManifest).filter_by(
                artifact_set_id=artifact_set_id
            ).order_by(ArtifactManifest.id).all()
            return [self._manifest_dict(row) for row in rows]

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _row_is_valid(self, row: ArtifactManifest) -> bool:
        if row.size_bytes is None or not row.sha256:
            return False
        path = Path(row.final_path)
        return (
            path.is_file()
            and path.stat().st_size == row.size_bytes
            and self._sha256(path) == row.sha256
        )

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _manifest_dict(row: ArtifactManifest) -> dict:
        return {
            column.name: getattr(row, column.name)
            for column in ArtifactManifest.__table__.columns
        }
