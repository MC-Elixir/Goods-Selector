# Task 7 Report: Twelve-Type De-branded Query Planning

## Status

Implemented and verified.

## Changes

- Added deterministic generation for all 12 canonical `QueryType` values.
- Added case-insensitive removal of complete excluded brands, brand words, model
  tokens, aliases, and imitation-seeking terms.
- Preserved the understanding's excluded tokens and structured evidence refs on
  every query without mutating the input understanding.
- Added meaningful fallbacks for absent optional evidence, with minimum-length,
  unique query text and deterministic unique IDs.
- Added low-relevance rewrites for iterations 1 and 2, explicit `retry_of`
  lineage, and existing text/ID fingerprint deduplication. Iteration 3 and later
  return no rewrites.
- Reused Task 6 `_brand_tokens` behavior to avoid divergent brand tokenization.

## TDD Evidence

- Initial RED: planner test collection failed with
  `ModuleNotFoundError: No module named 'matchers.query_planner'`.
- Brand-imitation RED: the focused brand test failed while `仿` and `同款`
  remained after brand removal.
- GREEN focused suite:
  `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_query_planner.py -v`
  -> `6 passed`.
- GREEN full suite:
  `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/`
  -> `524 passed, 5 skipped, 210 warnings` in 209.63s.

## Risks / Notes

- The full suite warnings are pre-existing deprecation warnings unrelated to
  Task 7.
- Brand safety is centralized in a dependency-light module imported by Tasks 6
  and 7, so the refactor introduces no circular dependency.

## Review Follow-up

- Moved stable brand tokenization, matching, and removal into the public
  `matchers.brand_safety` module shared by Tasks 6 and 7.
- Latin and numeric brand/model tokens now require independent ASCII
  alphanumeric boundaries. This removes standalone `US`, `Home`, `GE`, and
  `A-100` case-insensitively without damaging `industrial`, `household`, or
  `geometry`. Tokens containing CJK continue to use substring matching.
- Rewrite iteration 1 now accepts only initial queries. Iteration 2 accepts
  only a rewrite whose referenced parent is an initial query present in the
  supplied plan. Skipped and repeated iterations return no rewrite, preserving
  the `initial -> rewrite1 -> rewrite2` chain.
- Query text collision handling now uses a deterministic loop and checks the
  final fingerprint before append, including when brand cleaning removes all
  type-specific qualifiers.

### Follow-up TDD Evidence

- RED: four tests reproduced ordinary-word corruption, single-pass collision,
  skipped iteration 2, and Task 6 boundary corruption (`4 failed, 25 passed`).
- Focused query planner + product understanding: `29 passed`.
- Query planner + product understanding + vision compatibility: `54 passed`.
- Full suite: `528 passed, 5 skipped, 210 warnings` in 209.21s.
