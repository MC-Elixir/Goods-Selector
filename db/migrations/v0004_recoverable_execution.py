"""Add ASIN-level recoverable execution state and idempotency keys."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection


VERSION = "0004_recoverable_execution"


def _columns(connection: Connection, table: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table)}


def _add_result_key(connection: Connection, table: str) -> None:
    if table not in inspect(connection).get_table_names():
        return
    if "result_key" not in _columns(connection, table):
        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN result_key VARCHAR(160)")
    connection.exec_driver_sql(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_result_key "
        f"ON {table}(result_key) WHERE result_key IS NOT NULL"
    )


def upgrade(connection: Connection) -> None:
    """Create execution tables and add nullable business-result keys."""

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS execution_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES run_logs(id) ON DELETE CASCADE,
            scope_type VARCHAR(12) NOT NULL CHECK (scope_type IN ('run','asin')),
            scope_key VARCHAR(80) NOT NULL,
            stage VARCHAR(80) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','succeeded','failed','retry_wait',
                                  'human_required','cancelled','skipped','timed_out')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
            input_fingerprint VARCHAR(64),
            output_fingerprint VARCHAR(64),
            input_snapshot JSON,
            output_snapshot JSON,
            evidence_refs JSON,
            worker_id VARCHAR(120),
            lease_token VARCHAR(64),
            heartbeat_at TIMESTAMP,
            lease_expires_at TIMESTAMP,
            next_retry_at TIMESTAMP,
            timeout_seconds REAL CHECK (timeout_seconds IS NULL OR timeout_seconds > 0),
            error_code VARCHAR(120),
            error_detail TEXT,
            human_action_required JSON,
            resume_token VARCHAR(64),
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_execution_node_identity
                UNIQUE(run_id, scope_type, scope_key, stage)
        )"""
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_nodes_run ON execution_nodes(run_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_nodes_stage ON execution_nodes(stage)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_nodes_status ON execution_nodes(status)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_node_runnable "
        "ON execution_nodes(status, next_retry_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_nodes_lease "
        "ON execution_nodes(lease_expires_at)"
    )

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS execution_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id INTEGER NOT NULL REFERENCES execution_nodes(id) ON DELETE CASCADE,
            attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
            generation INTEGER NOT NULL CHECK (generation >= 1),
            status VARCHAR(24) NOT NULL,
            worker_id VARCHAR(120),
            lease_token VARCHAR(64) NOT NULL,
            input_fingerprint VARCHAR(64),
            output_fingerprint VARCHAR(64),
            input_snapshot JSON,
            output_snapshot JSON,
            started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            heartbeat_at TIMESTAMP,
            finished_at TIMESTAMP,
            error_code VARCHAR(120),
            error_detail TEXT,
            finish_reason VARCHAR(80),
            CONSTRAINT uq_execution_attempt_number UNIQUE(node_id, attempt_no)
        )"""
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_attempts_node "
        "ON execution_attempts(node_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_attempts_lease "
        "ON execution_attempts(lease_token)"
    )

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS execution_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES run_logs(id) ON DELETE CASCADE,
            node_id INTEGER REFERENCES execution_nodes(id) ON DELETE SET NULL,
            operation VARCHAR(80) NOT NULL,
            actor_type VARCHAR(40) NOT NULL DEFAULT 'system',
            actor_ref VARCHAR(120),
            reason TEXT,
            before_status VARCHAR(24),
            after_status VARCHAR(24),
            payload JSON,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_operations_run "
        "ON execution_operations(run_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_execution_operations_node "
        "ON execution_operations(node_id)"
    )

    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS artifact_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES run_logs(id) ON DELETE CASCADE,
            node_id INTEGER NOT NULL REFERENCES execution_nodes(id) ON DELETE CASCADE,
            attempt_id INTEGER NOT NULL REFERENCES execution_attempts(id) ON DELETE CASCADE,
            artifact_set_id VARCHAR(64) NOT NULL,
            logical_name VARCHAR(160) NOT NULL,
            artifact_type VARCHAR(40) NOT NULL,
            temporary_path TEXT,
            final_path TEXT NOT NULL,
            size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
            sha256 VARCHAR(64),
            status VARCHAR(20) NOT NULL DEFAULT 'writing'
                CHECK (status IN ('writing','committed','invalid')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            committed_at TIMESTAMP,
            CONSTRAINT uq_artifact_set_logical_name
                UNIQUE(artifact_set_id, logical_name)
        )"""
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_artifact_manifests_run "
        "ON artifact_manifests(run_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_artifact_manifests_set "
        "ON artifact_manifests(artifact_set_id)"
    )

    for table in ("profit_snapshots", "scores", "market_analyses"):
        _add_result_key(connection, table)
