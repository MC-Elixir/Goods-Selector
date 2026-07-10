CREATE TABLE IF NOT EXISTS field_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type VARCHAR(40) NOT NULL,
    entity_ref VARCHAR(120) NOT NULL,
    field_name VARCHAR(120) NOT NULL,
    value_json TEXT,
    status VARCHAR(20) NOT NULL,
    source_provider VARCHAR(80) NOT NULL,
    source_type VARCHAR(80),
    source_ref TEXT,
    observed_at TIMESTAMP,
    expires_at TIMESTAMP,
    confidence REAL NOT NULL DEFAULT 0,
    extraction_method VARCHAR(80),
    schema_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    conflict_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('verified','extracted','inferred','stale','missing','mock','conflicting')),
    CHECK (confidence >= 0 AND confidence <= 1)
);
CREATE INDEX IF NOT EXISTS ix_field_evidence_entity ON field_evidence(entity_type, entity_ref);

CREATE TABLE IF NOT EXISTS query_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref VARCHAR(80) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    query_id VARCHAR(80) NOT NULL,
    query_type VARCHAR(40) NOT NULL,
    query_text VARCHAR(120) NOT NULL,
    reason TEXT NOT NULL,
    excluded_brand_tokens_json TEXT NOT NULL DEFAULT '[]',
    backend VARCHAR(60),
    result_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    retry_of VARCHAR(80),
    status VARCHAR(20) NOT NULL,
    artifact_ref TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_ref, query_id)
);

CREATE TABLE IF NOT EXISTS match_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref VARCHAR(80) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    offer_id VARCHAR(40) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    overall_confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_ref, asin, offer_id)
);

CREATE TABLE IF NOT EXISTS sourcing_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref VARCHAR(80) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    offer_id VARCHAR(40),
    status VARCHAR(30) NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_ref, asin, offer_id)
);
