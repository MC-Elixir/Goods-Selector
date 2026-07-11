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
- The planner imports Task 6's private `_brand_tokens` helper. This is the
  narrowest reuse with no circular dependency; promoting it to a new shared
  module would broaden this task's change surface.
