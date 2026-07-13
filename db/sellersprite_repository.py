"""Persistence for immutable SellerSprite browser-export manifests."""
from __future__ import annotations

import json
from math import isfinite
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, inspect, text

from agent.tools.sellersprite_importer import ImportedSellerSpriteExport


_IMPORT_COLUMNS = (
    "id, sourcing_run_id, call_id, legacy_run_log_id, asin, artifact_type, "
    "source_provider, source_type, measurement_kind, source_file, file_sha256, "
    "observed_at, imported_at, row_count, headers_json, normalized_payload_json, "
    "quality_summary_json, schema_version, status, error_code, diagnostic"
)


def save_sellersprite_import(
    engine: Engine,
    imported: ImportedSellerSpriteExport,
) -> dict[str, Any]:
    """Persist one imported export and an optional compact evidence summary.

    The imported rows remain JSON so this phase does not introduce a second,
    query-oriented keyword schema.  Values such as ``None`` are deliberately
    serialized as JSON ``null`` rather than replaced with made-up metrics.
    """

    # A manifest is only created after Task 2 has successfully imported a
    # readable artifact.  Keep this distinct from the evidence contract, where
    # estimates are expressed as metadata and the status remains ``extracted``.
    if imported.status != "imported":
        raise ValueError("SellerSprite import status must be 'imported'")

    import_id = str(uuid4())
    manifest = {
        "id": import_id,
        "sourcing_run_id": imported.context.sourcing_run_id,
        "call_id": imported.context.call_id,
        "legacy_run_log_id": None,
        "asin": imported.context.asin,
        "artifact_type": imported.artifact.path.suffix.lower().lstrip("."),
        "source_provider": imported.source_provider,
        "source_type": imported.source_type,
        "measurement_kind": imported.measurement_kind,
        "source_file": str(imported.artifact.path),
        "file_sha256": imported.artifact.sha256,
        "observed_at": imported.artifact.observed_at,
        "row_count": imported.row_count,
        "headers_json": _dump_json(imported.headers),
        "normalized_payload_json": _dump_json(
            {"rows": imported.rows, "raw_rows": imported.raw_rows}
        ),
        "quality_summary_json": _dump_json(imported.quality_summary),
        "schema_version": imported.schema_version,
        "status": imported.status,
        "error_code": None,
        "diagnostic": None,
    }

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sellersprite_imports ("
                "id, sourcing_run_id, call_id, legacy_run_log_id, asin, artifact_type, "
                "source_provider, source_type, measurement_kind, source_file, file_sha256, "
                "observed_at, row_count, headers_json, normalized_payload_json, "
                "quality_summary_json, schema_version, status, error_code, diagnostic"
                ") VALUES ("
                ":id, :sourcing_run_id, :call_id, :legacy_run_log_id, :asin, :artifact_type, "
                ":source_provider, :source_type, :measurement_kind, :source_file, :file_sha256, "
                ":observed_at, :row_count, :headers_json, :normalized_payload_json, "
                ":quality_summary_json, :schema_version, :status, :error_code, :diagnostic"
                ")"
            ),
            manifest,
        )
        if _has_table(connection, "field_evidence"):
            connection.execute(
                text(
                    "INSERT INTO field_evidence ("
                    "entity_type, entity_ref, field_name, value_json, status, "
                    "source_provider, source_type, source_ref, observed_at, "
                    "extraction_method, schema_version, conflict_refs_json"
                    ") VALUES ("
                    ":entity_type, :entity_ref, :field_name, :value_json, :status, "
                    ":source_provider, :source_type, :source_ref, :observed_at, "
                    ":extraction_method, :schema_version, :conflict_refs_json"
                    ")"
                ),
                {
                    "entity_type": "sellersprite_import",
                    "entity_ref": import_id,
                    "field_name": "import_summary",
                    "value_json": _dump_json(
                        {
                            "asin": imported.context.asin,
                            "row_count": imported.row_count,
                            "measurement_kind": imported.measurement_kind,
                        }
                    ),
                    "status": "extracted",
                    "source_provider": "sellersprite",
                    "source_type": "browser_extension_export",
                    "source_ref": f"sha256:{imported.artifact.sha256}",
                    "observed_at": imported.artifact.observed_at,
                    "extraction_method": "browser_export_import",
                    "schema_version": imported.schema_version,
                    "conflict_refs_json": "[]",
                },
            )

    saved = get_sellersprite_import(engine, import_id)
    if saved is None:  # Defensive guard against a broken database driver.
        raise RuntimeError("failed to read saved SellerSprite import")
    return saved


def get_sellersprite_import(engine: Engine, import_id: str) -> dict[str, Any] | None:
    """Return one persisted manifest with its JSON fields decoded."""

    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT {_IMPORT_COLUMNS} FROM sellersprite_imports WHERE id=:id"),
            {"id": import_id},
        ).mappings().one_or_none()
    if row is None:
        return None
    return _decode_manifest(dict(row))


def _has_table(connection: Any, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def _dump_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_safe(value: Any) -> Any:
    """Map unrepresentable numeric values to unknown/null before persistence."""

    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _decode_manifest(row: dict[str, Any]) -> dict[str, Any]:
    row["headers"] = json.loads(row.pop("headers_json"))
    payload = json.loads(row.pop("normalized_payload_json"))
    row["normalized_payload"] = payload["rows"]
    row["raw_rows"] = payload["raw_rows"]
    row["quality_summary"] = json.loads(row.pop("quality_summary_json"))
    return row
