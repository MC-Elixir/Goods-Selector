### Task 13: Compatibility, Full Verification, and No-Mock Real E2E

**Files:**
- Modify: `README.md`
- Modify: `STATUS.md`
- Modify: `docs/scoring_spec.md`
- Modify: `tests/test_smoke_run.py`
- Create: `docs/audits/2026-07-10-phase1-phase2-results.md`

**Interfaces:**
- Consumes: Tasks 1–11, Phase 0 completeness artifact, real Amazon/1688 sessions.
- Produces: compatibility proof, measured field-quality deltas, benchmark report, and unresolved-issue log.

- [ ] **Step 1: Add compatibility assertions before the real run**

```python
# append to tests/test_smoke_run.py
from click.testing import CliRunner
import main as main_module
from main import cli


def test_legacy_pipeline_command_remains_default(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "run_pipeline", lambda **kwargs: calls.append(kwargs) or 77)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--category", "Sports & Outdoors", "--limit", "1"])
    assert result.exit_code == 0
    assert calls == [{"category": "Sports & Outdoors", "limit": 1, "marketplace": "US"}]
```

- [ ] **Step 2: Run focused compatibility suites**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_smoke_run.py tests/test_pipeline_source_mode.py tests/test_pipeline_runtime_controls.py tests/test_agent_runtime.py tests/test_agent_server.py -v`

Expected: all selected tests pass and legacy mode remains the default.

- [ ] **Step 3: Run the complete test suite**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/`

Expected: zero failures. Record pass/skip/warning counts and wall time in `docs/audits/2026-07-10-phase1-phase2-results.md`.

- [ ] **Step 4: Verify migration against a copied production database**

```bash
cp data/amazon_selector.db /tmp/amazon_selector_migration_test.db
DATABASE_URL=sqlite:////tmp/amazon_selector_migration_test.db python -m db.init_db
sqlite3 /tmp/amazon_selector_migration_test.db 'PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version FROM schema_migrations ORDER BY version;'
```

Expected: `integrity_check` is `ok`, `foreign_key_check` prints no rows, migration `0001_evidence_foundation` is present, and legacy table row counts equal the pre-migration snapshot.

- [ ] **Step 5: Run a small real no-mock Docker E2E**

Run the official Docker WebUI runtime, then launch one Amazon US keyword or category sample with one product, formal no-mock mode, market evidence required, supplier detail required, and export enabled. Permit human login/captcha handoff but do not substitute mock data.

Expected terminal outcomes are `recommend`, `needs_manual_review`, `reject`, or `insufficient_data`; infrastructure failure is reported separately. A run with zero crawled products must not be marked quality-success. Capture query attempts, detail-field statuses, match decisions, retries, external-call errors, mock count, and export paths.

- [ ] **Step 6: Recompute completeness and benchmark metrics**

Compare the same field definitions and sample cohort against `data/audits/phase0_field_completeness_20260710.json`. Report Amazon completeness, 1688 completeness, market missing rate, real supplier rate, mock contamination, and reviewed benchmark metrics. If reviewed labels are still zero, write `not measurable: no reviewed labels` for accuracy metrics.

- [ ] **Step 7: Document verified results without overstating quality**

In `docs/audits/2026-07-10-phase1-phase2-results.md`, record:

```markdown
## Changes
## Focused test results
## Full test results
## SQLite migration and integrity
## Real no-mock E2E
## Field completeness before and after
## Match metrics from reviewed labels
## Mock contamination before and after
## Remaining blockers and human verification
```

Update README/STATUS/scoring spec only with behavior proven by the preceding commands. State that `run_pipeline()` is still deterministic and the Phase 3 `--mode agent` route is not yet implemented.

- [ ] **Step 8: Commit verification documentation**

```bash
git add README.md STATUS.md docs/scoring_spec.md docs/audits/2026-07-10-phase1-phase2-results.md tests/test_smoke_run.py
git commit -m "docs: report sourcing quality vertical slice"
```

## Completion Gate

This plan is complete only when all of the following are evidenced:

- Explicit negative visual classifications yield rejection and cannot improve match scores.
- Missing critical price, MOQ, dimensions, weight, market demand, or competition evidence cannot produce a strong recommendation.
- Twelve de-branded query types are generated and query outcomes are persisted.
- Blocked 1688 pages are never parsed as offers.
- Formal no-mock mode has zero mock contamination.
- Accessory/full-product, pack-count, and core-function hard negatives are rejected.
- New LLM outputs fail closed on schema validation errors.
- Existing deterministic CLI, SQLite history, and export fields remain compatible.
- Full tests and a real small-scale E2E are reported.
- Matching-accuracy deltas are reported only from reviewed benchmark labels.

## Follow-on Plans

After this completion gate passes, write two separate implementation plans:

1. Phase 3 finite-state Agentic Sourcing Loop: `AgentState`, typed tools, policy, checkpoints, resume, `--mode agent`, bounded expansion, re-score, and audit decisions.
2. Phase 4 feedback and replay: WebUI labels, versioned benchmark feedback, replay, and version comparison.
