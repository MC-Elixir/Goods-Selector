"""Strict, filesystem-only observation of SellerSprite export downloads.

The browser layer snapshots a directory before it clicks Export.  This module
then accepts exactly one *new* completed export, rather than guessing which
file in a user's download directory belongs to the current browser action.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from time import monotonic, sleep

from agent.sellersprite_policy import normalize_sellersprite_error_code


ALLOWED_EXPORT_SUFFIXES = frozenset({".csv", ".xlsx", ".xls"})
_TEMPORARY_DOWNLOAD_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp")
_POLL_INTERVAL_SECONDS = 0.25
_STABILITY_INTERVAL_SECONDS = 0.25
_HASH_CHUNK_SIZE = 64 * 1024


class DownloadError(RuntimeError):
    """A terminal, safe-to-report download error."""

    def __init__(self, error_code: str) -> None:
        self.error_code = normalize_sellersprite_error_code(error_code)
        super().__init__(self.error_code)


@dataclass(frozen=True)
class DownloadSnapshot:
    """The completed directory entries present before the export click."""

    directory: Path
    names: frozenset[str]
    observed_at: str
    observed_at_ns: int


@dataclass(frozen=True)
class DownloadedArtifact:
    """A hash-addressed export file observed after one browser action."""

    path: Path
    sha256: str
    size_bytes: int
    observed_at: str

    @classmethod
    def from_path(cls, path: Path) -> "DownloadedArtifact":
        candidate = Path(path)
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or candidate.suffix.lower() not in ALLOWED_EXPORT_SUFFIXES
        ):
            raise DownloadError("INVALID_EXPORT")

        try:
            before = candidate.stat()
            digest = _sha256_file(candidate)
            after = candidate.stat()
        except OSError as exc:
            raise DownloadError("INVALID_EXPORT") from exc

        # A file that changes while it is being hashed is not an immutable
        # artifact for this run.  The caller can wait for a later stable file.
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise DownloadError("INVALID_EXPORT")

        return cls(
            path=candidate,
            sha256=digest,
            size_bytes=after.st_size,
            observed_at=datetime.now(UTC).isoformat(),
        )


def snapshot_download_dir(path: Path) -> DownloadSnapshot:
    """Record existing entries so a later observer cannot select old files."""

    directory = Path(path)
    if not directory.is_dir():
        raise DownloadError("INVALID_EXPORT")

    try:
        names = frozenset(entry.name for entry in directory.iterdir())
        observed_at_ns = directory.stat().st_mtime_ns
    except OSError as exc:
        raise DownloadError("INVALID_EXPORT") from exc

    return DownloadSnapshot(
        directory=directory,
        names=names,
        observed_at=datetime.now(UTC).isoformat(),
        # File mtimes are set by the download filesystem.  Use that same
        # filesystem's directory clock rather than this process's clock so
        # host/container clock skew cannot reject a real fresh download.
        observed_at_ns=observed_at_ns,
    )


def wait_for_new_download(
    path: Path,
    snapshot: DownloadSnapshot,
    timeout_seconds: int,
) -> DownloadedArtifact:
    """Return one newly-created, stable, nonempty allowed export.

    Temporary browser files are ignored.  Existing names are never re-used as
    evidence for the current run, even if an external process overwrites one.
    """

    directory = Path(path)
    if not directory.is_dir() or directory != snapshot.directory:
        raise DownloadError("INVALID_EXPORT")

    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise DownloadError("DOWNLOAD_TIMEOUT") from exc
    if not isfinite(timeout) or timeout <= 0:
        raise DownloadError("DOWNLOAD_TIMEOUT")

    deadline = monotonic() + timeout
    while True:
        candidates = _new_export_candidates(directory, snapshot)
        if len(candidates) > 1:
            raise DownloadError("AMBIGUOUS_DOWNLOAD")

        remaining = deadline - monotonic()
        if len(candidates) == 1 and remaining >= _STABILITY_INTERVAL_SECONDS:
            candidate = candidates[0]
            if _size_is_stable(candidate):
                try:
                    artifact = DownloadedArtifact.from_path(candidate)
                except DownloadError:
                    # A writer can finish, replace, or remove a file between
                    # the stability check and hashing.  Keep observing only
                    # while the configured budget remains.
                    artifact = None
                if artifact is not None and artifact.size_bytes > 0:
                    return artifact

        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DownloadError("DOWNLOAD_TIMEOUT")
        sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def _new_export_candidates(directory: Path, snapshot: DownloadSnapshot) -> list[Path]:
    try:
        candidates = [
            entry
            for entry in directory.iterdir()
            if _is_new_completed_export(entry, snapshot)
        ]
    except OSError as exc:
        raise DownloadError("INVALID_EXPORT") from exc
    return sorted(candidates, key=lambda candidate: candidate.name)


def _is_new_completed_export(path: Path, snapshot: DownloadSnapshot) -> bool:
    if path.name in snapshot.names or path.name.lower().endswith(_TEMPORARY_DOWNLOAD_SUFFIXES):
        return False
    if path.suffix.lower() not in ALLOWED_EXPORT_SUFFIXES:
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        state = path.stat()
        # A stale export can be copied into the directory after the snapshot
        # under a new name.  It is still not evidence of this export action.
        return state.st_size > 0 and state.st_mtime_ns >= snapshot.observed_at_ns
    except OSError:
        return False


def _size_is_stable(path: Path) -> bool:
    try:
        before = path.stat()
        if before.st_size <= 0:
            return False
        sleep(_STABILITY_INTERVAL_SECONDS)
        after = path.stat()
    except OSError:
        return False
    return before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
