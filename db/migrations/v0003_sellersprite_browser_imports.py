"""Add immutable manifests for SellerSprite browser exports."""

from sqlalchemy.engine import Connection

VERSION = "0003_sellersprite_browser_imports"


def upgrade(connection: Connection) -> None:
    """Create only the new SellerSprite import table and its lookup indexes."""

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS sellersprite_imports (
            id VARCHAR(36) PRIMARY KEY,
            sourcing_run_id VARCHAR(36) NOT NULL,
            call_id VARCHAR(36) NOT NULL,
            legacy_run_log_id INTEGER,
            asin VARCHAR(20) NOT NULL,
            artifact_type VARCHAR(40) NOT NULL,
            source_provider VARCHAR(80) NOT NULL,
            source_type VARCHAR(80) NOT NULL,
            measurement_kind VARCHAR(40) NOT NULL,
            source_file TEXT NOT NULL,
            file_sha256 VARCHAR(64) NOT NULL,
            observed_at TIMESTAMP NOT NULL,
            imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER NOT NULL,
            headers_json TEXT NOT NULL,
            normalized_payload_json TEXT NOT NULL,
            quality_summary_json TEXT NOT NULL,
            schema_version VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL,
            error_code VARCHAR(80),
            diagnostic TEXT
        )"""
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_sellersprite_imports_run_asin "
        "ON sellersprite_imports(sourcing_run_id, asin)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_sellersprite_imports_file_sha256 "
        "ON sellersprite_imports(file_sha256)"
    )


def down(connection: Connection) -> None:
    """Drop the SellerSprite imports table and indexes."""

    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_sellersprite_imports_file_sha256")
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_sellersprite_imports_run_asin")
    connection.exec_driver_sql("DROP TABLE IF EXISTS sellersprite_imports")
