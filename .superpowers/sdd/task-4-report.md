# Task 4 Recovery Report

## Status

Complete.

## Recovery background and TDD evidence

This task was recovered from an interrupted agent at HEAD `a29de7e`. Six Task 4 source/test files already contained uncommitted implementation and tests when recovery began. I inspected the complete Task 4 brief and the existing diff before running or changing anything.

The first observable focused run was therefore recovery verification, not an original RED:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py tests/test_scoring.py -v
85 passed in 0.15s
```

The previous agent's original RED output is not recoverable from the shared workspace. This report does not claim that I observed it. No additional production behavior was required after recovery inspection, so I did not manufacture a new RED/GREEN cycle for already implemented behavior.

## Implementation verified

- `InsufficientCostEvidence` makes missing purchase price and missing physical logistics inputs explicit.
- Purchase tiers accept both legacy `{qty, price}` and extracted `{min_qty, price_cny}` shapes; malformed tiers are ignored rather than converted to optimistic cost.
- Shipping and FBA calculations require weight and all three dimensions instead of applying standard-size defaults.
- `ScoringEvidenceError` gates missing competition evidence, missing real supplier price/MOQ evidence, mock-only supply evidence, and missing logistics fields.
- The pipeline catches both typed evidence errors per product, maps them to explicit rejection reasons, and does not persist absent profit or score snapshots.
- With `export_review_on_empty=True`, explicitly insufficient records can enter the review fallback without fabricated profit or score objects.

## Verification evidence

Focused regression suite:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py tests/test_scoring.py tests/test_pipeline_review_fallback.py tests/test_exporter_spec_match.py -v
91 passed in 1.21s
```

Full repository suite:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/
442 passed, 5 skipped, 209 warnings in 188.09s
```

The five skips are existing Amazon Scrapling cases. The warnings are existing deprecation warnings, principally `datetime.utcnow`, SQLAlchemy defaults, and lxml's `strip_cdata` option. No test failed.

## Self-review

- Missing evidence does not produce zero-cost purchases, default package dimensions, best-case competition scores, or mock-backed supply scores.
- Typed exceptions expose structured fields and pipeline rejection reasons use the required stable names: `missing_purchase_price`, `missing_logistics_dimensions`, `missing_market_evidence`, and `missing_moq`.
- Review fallback ordering remains score/profit based for fully evaluated rejected items, while insufficient items sort after scored records.
- Changes remain limited to Task 4 profit, scoring, orchestration, focused tests, and this report.

## Concerns

No blocking concerns. The recovery can prove the final behavior and regression state, but cannot independently prove the interrupted agent's original RED because that terminal evidence was not preserved.

## Important review fixes

Two Important review findings were addressed in a separate strict TDD cycle after commit `3b3dbf0`.

### RED

Tests were added first for malformed/nonpositive price tiers, price and MOQ split across different suppliers, stable pipeline rejection reason mapping, and insufficient-evidence status/reasons in Excel, Markdown, and JSON.

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_scoring.py::TestScoreSupply::test_malformed_or_nonpositive_tiers_are_not_price_evidence tests/test_scoring.py::TestScoreSupply::test_price_and_moq_must_exist_on_the_same_supplier tests/test_pipeline_review_fallback.py::test_typed_evidence_errors_map_to_explicit_rejection_reasons tests/test_exporter_spec_match.py::test_insufficient_review_reasons_and_status_reach_all_exports -v
5 failed, 1 passed in 0.82s
```

The failures showed that malformed tiers could count as price evidence, incomplete evidence produced `price_and_moq`, and JSON lacked `review_status` (with the same record-level reason loss affecting Excel and Markdown).

### GREEN

```text
same targeted command
6 passed in 0.82s
```

The minimal implementation exposes and reuses one tier normalizer from `profit_model`, requires positive price and MOQ on the same real supplier, emits specific missing fields, and centralizes exporter record status/reason resolution while preserving score-backed legacy records.

### Review-fix verification

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py tests/test_scoring.py tests/test_pipeline_review_fallback.py tests/test_exporter_spec_match.py -v
96 passed in 1.03s

TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/
447 passed, 5 skipped, 209 warnings in 203.45s
```

No new concerns were found. The five skips and warning categories remain the existing ones described above.

## Finite-number evidence gate

The final Important review finding was fixed in a separate TDD cycle after `a34a317`.

### RED

String and float forms of `nan`, `inf`, and `-inf` were tested independently in tier quantity, tier price, and fallback `base_price_cny`, through both profit and supply scoring paths.

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py -k nonfinite tests/test_scoring.py -k nonfinite -q
20 failed, 16 passed, 89 deselected in 0.24s
```

The observed failures included non-finite purchase costs, non-finite values accepted as supply price evidence, and a string-Infinity `TypeError` in downstream capital scoring.

### GREEN and verification

```text
same targeted command
36 passed, 89 deselected in 0.16s

TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py tests/test_scoring.py tests/test_pipeline_review_fallback.py tests/test_exporter_spec_match.py -q
132 passed in 0.91s

TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q
483 passed, 5 skipped, 209 warnings in 204.98s
```

The shared `normalize_positive_number` now requires finite values greater than zero. Tier normalization, purchase-cost fallback, and supply scoring reuse it; supply capital scoring also consumes normalized numeric prices. No new concerns were found.
