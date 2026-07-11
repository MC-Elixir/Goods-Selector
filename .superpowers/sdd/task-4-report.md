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
