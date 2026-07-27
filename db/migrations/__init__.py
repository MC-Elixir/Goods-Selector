"""Ordered, structured database migrations."""

from db.migrations import (
    v0001_evidence_foundation,
    v0002_repair_evidence_semantics,
    v0003_sellersprite_browser_imports,
    v0004_recoverable_execution,
    v0005_seller_research,
)

MIGRATIONS = (
    v0001_evidence_foundation,
    v0002_repair_evidence_semantics,
    v0003_sellersprite_browser_imports,
    v0004_recoverable_execution,
    v0005_seller_research,
)
