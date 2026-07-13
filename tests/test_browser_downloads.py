from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.tools.browser_downloads import (
    DownloadError,
    DownloadedArtifact,
    snapshot_download_dir,
    wait_for_new_download,
)


def test_wait_for_new_download_ignores_crdownload_and_hashes_stable_csv(tmp_path):
    before = snapshot_download_dir(tmp_path)
    (tmp_path / "keywords.csv.crdownload").write_text("partial", encoding="utf-8")
    completed = tmp_path / "keywords.csv"
    completed.write_text("Keyword,Search Volume\numbrella,10K+\n", encoding="utf-8")

    artifact = wait_for_new_download(tmp_path, before, timeout_seconds=1)

    assert artifact.path == completed
    assert artifact.size_bytes == completed.stat().st_size
    assert len(artifact.sha256) == 64
    assert artifact.sha256 == DownloadedArtifact.from_path(completed).sha256


def test_wait_for_new_download_does_not_select_an_old_preexisting_file(tmp_path):
    old_file = tmp_path / "old.csv"
    old_file.write_text("Keyword\numbrella\n", encoding="utf-8")
    before = snapshot_download_dir(tmp_path)

    with pytest.raises(DownloadError, match="DOWNLOAD_TIMEOUT") as error:
        wait_for_new_download(tmp_path, before, timeout_seconds=0)

    assert error.value.error_code == "DOWNLOAD_TIMEOUT"


def test_wait_for_new_download_rejects_new_name_with_predating_mtime(tmp_path):
    before = snapshot_download_dir(tmp_path)
    stale = tmp_path / "late-appearing-stale.csv"
    stale.write_text("Keyword\numbrella\n", encoding="utf-8")
    stale_mtime_ns = before.observed_at_ns - 1_000_000_000
    os.utime(stale, ns=(stale_mtime_ns, stale_mtime_ns))

    with pytest.raises(DownloadError, match="DOWNLOAD_TIMEOUT") as error:
        wait_for_new_download(tmp_path, before, timeout_seconds=0.3)

    assert error.value.error_code == "DOWNLOAD_TIMEOUT"


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("nan"), float("inf")])
def test_wait_for_new_download_rejects_non_bounded_timeouts(tmp_path, timeout_seconds):
    before = snapshot_download_dir(tmp_path)

    with pytest.raises(DownloadError, match="DOWNLOAD_TIMEOUT"):
        wait_for_new_download(tmp_path, before, timeout_seconds=timeout_seconds)


def test_wait_for_new_download_rejects_multiple_new_final_exports(tmp_path):
    before = snapshot_download_dir(tmp_path)
    (tmp_path / "first.csv").write_text("Keyword\numbrella\n", encoding="utf-8")
    (tmp_path / "second.csv").write_text("Keyword\npatio umbrella\n", encoding="utf-8")

    with pytest.raises(DownloadError, match="AMBIGUOUS_DOWNLOAD") as error:
        wait_for_new_download(tmp_path, before, timeout_seconds=1)

    assert error.value.error_code == "AMBIGUOUS_DOWNLOAD"


def test_snapshot_records_only_existing_names_and_uses_path_objects(tmp_path):
    existing = tmp_path / "before.xlsx"
    existing.write_bytes(b"not parsed by the observer")

    snapshot = snapshot_download_dir(tmp_path)

    assert snapshot.directory == tmp_path
    assert snapshot.names == frozenset({"before.xlsx"})


def test_downloaded_artifact_rejects_missing_or_non_file_paths(tmp_path):
    with pytest.raises(DownloadError, match="INVALID_EXPORT"):
        DownloadedArtifact.from_path(tmp_path / "missing.csv")

    with pytest.raises(DownloadError, match="INVALID_EXPORT"):
        DownloadedArtifact.from_path(tmp_path)
