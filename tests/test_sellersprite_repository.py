from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, inspect, text

from agent.sellersprite_models import SellerSpriteContext
from agent.tools.browser_downloads import DownloadedArtifact
from agent.tools.sellersprite_importer import import_sellersprite_export
from db.migrate import run_migrations
from db.sellersprite_repository import (
    get_sellersprite_import,
    list_sellersprite_imports,
    save_sellersprite_import,
)


def _imported_export(tmp_path):
    path = tmp_path / "关键词.csv"
    path.write_text("关键词,搜索量,未映射字段\n雨伞,10K+,\n", encoding="utf-8")
    artifact = DownloadedArtifact.from_path(path)
    return import_sellersprite_export(
        SellerSpriteContext.create("B00Q7OAN50"), artifact
    )


def test_repository_persists_manifest_and_extracted_evidence(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'imports.db'}")
    run_migrations(engine)
    imported = _imported_export(tmp_path)

    saved = save_sellersprite_import(engine, imported)

    assert saved["source_type"] == "browser_extension_export"
    assert saved["measurement_kind"] == "vendor_estimate"
    assert saved["status"] == "imported"
    assert saved["file_sha256"] == imported.artifact.sha256
    assert saved["normalized_payload"] == imported.rows
    assert saved["raw_rows"] == imported.raw_rows
    assert saved["normalized_payload"][0]["search_volume"] is None
    assert saved["normalized_payload"][0]["search_volume_lower_bound"] == 10_000
    assert get_sellersprite_import(engine, saved["id"]) == saved

    with engine.connect() as connection:
        evidence = connection.execute(
            text(
                "SELECT entity_type, entity_ref, field_name, value_json, status, "
                "source_provider, source_type, source_ref "
                "FROM field_evidence"
            )
        ).mappings().one()
    assert evidence["entity_type"] == "sellersprite_import"
    assert evidence["entity_ref"] == saved["id"]
    assert evidence["field_name"] == "import_summary"
    assert evidence["status"] == "extracted"
    assert evidence["source_provider"] == "sellersprite"
    assert evidence["source_type"] == "browser_extension_export"
    assert evidence["source_ref"] == f"sha256:{imported.artifact.sha256}"
    assert json.loads(evidence["value_json"])["measurement_kind"] == "vendor_estimate"


def test_repository_stores_import_when_field_evidence_is_absent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'without-evidence.db'}")
    run_migrations(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE field_evidence")

    saved = save_sellersprite_import(engine, _imported_export(tmp_path))

    assert get_sellersprite_import(engine, saved["id"]) == saved


def test_repository_lists_newest_sanitized_import_manifests(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    run_migrations(engine)
    saved = save_sellersprite_import(engine, _imported_export(tmp_path))

    rows = list_sellersprite_imports(engine, limit=999)

    assert rows == [{
        "id": saved["id"], "asin": "B00Q7OAN50", "artifact_type": "csv",
        "file_sha256": saved["file_sha256"], "observed_at": saved["observed_at"],
        "imported_at": saved["imported_at"], "row_count": 1, "status": "imported",
        "error_code": None,
    }]
    assert "source_file" not in rows[0]
    assert "normalized_payload" not in rows[0]


def test_repository_rejects_estimated_manifest_status(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'status.db'}")
    run_migrations(engine)
    imported = replace(_imported_export(tmp_path), status="estimated")

    with pytest.raises(ValueError, match="status"):
        save_sellersprite_import(engine, imported)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM sellersprite_imports")).scalar_one() == 0


def test_repository_converts_nonfinite_values_to_json_null(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'nonfinite.db'}")
    run_migrations(engine)
    imported = replace(
        _imported_export(tmp_path),
        rows=[{"keyword": "umbrella", "search_volume": float("nan")}],
        raw_rows=[{"关键词": "umbrella", "搜索量": float("inf")}],
    )

    saved = save_sellersprite_import(engine, imported)

    assert saved["normalized_payload"][0]["search_volume"] is None
    assert saved["raw_rows"][0]["搜索量"] is None


def test_sellersprite_migration_is_additive_and_preserves_existing_rows(tmp_path):
    from db.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO run_logs(status, products_crawled, suppliers_matched, "
            "profits_calculated, candidates_after_filter, started_at) "
            "VALUES ('success', 0, 0, 0, 0, CURRENT_TIMESTAMP)"
        )

    assert "0003_sellersprite_browser_imports" in run_migrations(engine)
    assert run_migrations(engine) == []
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM run_logs").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM sellersprite_imports").scalar_one() == 0
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
    indexes = {index["name"]: index["column_names"] for index in inspect(engine).get_indexes("sellersprite_imports")}
    assert indexes["ix_sellersprite_imports_run_asin"] == ["sourcing_run_id", "asin"]
    assert indexes["ix_sellersprite_imports_file_sha256"] == ["file_sha256"]
