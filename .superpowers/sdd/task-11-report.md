# Task 11 Report

## Status

Implemented and committed as a bounded additive vertical slice. The existing deterministic
pipeline and CLI defaults are unchanged.

## Delivered

- Added `run_sourcing_slice` with Task 6 understanding, the Task 7 twelve-query plan,
  cross-query offer deduplication, detail enrichment, visual verification, Task 9 match
  evidence, and at most two search iterations.
- Added stable search outcome codes and immediate AUTH/CAPTCHA handoff without parsing or
  mock fallback.
- Formal mode excludes mock suppliers before detail, match, persistence, and export inputs.
- Recommendation `recommend` requires a kept minimum-evidence match, positive real price and
  MOQ, demand and competition references, purchase cost reference, all four logistics inputs,
  and profit basis. Missing evidence produces explicit rejection reasons and manual tasks.
- Added Task 2 persistence for every query attempt and evaluated match plus the recommendation,
  scoped by `run_ref`, in one transaction per product. Repeated runs are idempotent, including
  recommendations with a null offer id.
- Extended JSON, Excel, and Markdown exports additively while retaining legacy fields,
  columns, and Task 4 insufficient review status.

## Tests

- Focused: `25 passed, 1 warning`
- Full suite: `621 passed, 5 skipped, 210 warnings` using
  `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q -s`
- An earlier captured full-suite run had one two-second AgentRuntime timing failure
  (`620 passed, 5 skipped, 1 failed`); the failing test passed in isolation and the complete
  `-s` rerun passed.

## Concerns

- The coordinator is intentionally not wired into the legacy pipeline default. Callers must
  supply the fake/real dependencies and may inject a SQLAlchemy engine for Task 2 persistence.
- Existing deprecation warnings remain outside Task 11 scope.

## Review Fixes (2026-07-12)

- Formal no-mock attempts now compute counts, hit rates, and refs only after filtering;
  persisted/exported audit data contains only an aggregate `mock_filtered_count`.
- Recommendation gating now requires structured, referenced, finite positive logistics and
  profit values. Legacy list-shaped basis remains schema-readable but cannot recommend.
- Retry/manual-review matches are retained in `review_matches`; missing and hard-conflict
  reasons flow into recommendation reasons and manual verification tasks.
- Persistence atomically replaces the exact `(run_ref, asin)` snapshot across all three Task 2
  tables and preserves other ASIN scopes.
- Legacy and evidence rejection reasons are merged in the specified JSON `rejection_reasons`
  field and the corresponding Excel/Markdown legacy presentation.
- Error mapping distinguishes TIMEOUT, INVALID_INPUT, MISSING_REQUIRED_DATA, INTERNAL,
  AUTH_REQUIRED, CAPTCHA, and RATE_LIMITED; non-retryable failures terminate the slice.

Review verification: focused regression `64 passed`; full suite `639 passed, 5 skipped`.

Final committed-HEAD verification (`216d9f664a99a3f278265d310e31d2b6e4dd2cb4`):
`TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q -s` exited `0` with
`639 passed, 5 skipped, 210 warnings in 242.00s`.

## Final Important Review Fixes

- Supplier detail TIMEOUT and RATE_LIMITED now have a controller-owned two-attempt budget.
  Exhaustion is retained in `detail_failures` and recommendation evidence with stable reason,
  real offer reference, attempt count, and an actionable retry task. Non-retryable failures are
  likewise audited; AUTH/CAPTCHA still hand off immediately.
- Search hit rate is now `relevant unique real offers / unique real offers`; cross-query dedupe
  happens only after relevance accounting. An injectable relevance assessor controls which hits
  may proceed to detail/match, and hit rates below 0.2 trigger bounded rewrite.

Focused verification: `48 passed, 1 warning`.

## Conservative Default Relevance

- Added `_default_relevance(query, supplier)` with explicit raw boolean/finite score,
  finite text similarity, high-confidence image-search-only similarity, and conservative
  normalized title/query phrase evidence.
- Missing, malformed, NaN, infinite, low, single-character, and ordinary substring signals
  are rejected. Injected assessors remain supported unchanged.
- Focused Task 11 and related query/match/search verification: `96 passed`.
- The prior full-suite PID `68160` exited before this final commit; its final summary was not
  available to this worker. Final-HEAD full verification remains environment pending.

## Strict Title and Playwright Image Relevance

- Multi-term title evidence now requires deterministic 75% core-term coverage with at least
  two complete terms; two-term queries therefore require both terms. ASCII terms use word
  equality and CJK terms use complete normalized query terms, not shared bigrams.
- `alibaba_playwright` is recognized as image-capable only when a finite image similarity is
  present and meets the high image threshold; ordinary keyword results have no image score and
  do not pass this rule.
- Focused Task 11 plus Alibaba Playwright/diagnostic verification: `64 passed`.
- Prior full PID `74404` ended before this commit; final-HEAD full remains environment pending.

## CJK Run Boundary Relevance

- CJK title matching now preserves original runs separated by whitespace, punctuation, or
  ASCII instead of concatenating them.
- Multi-term CJK queries require the ordered adjacent phrase within one title run. Single-term
  CJK queries allow only exact-run, prefix, or suffix matches, preventing internal-substring and
  cross-run false positives.
- Focused Task 11 plus query/search/Playwright verification: `81 passed`.
- No prior full-suite process remained; final-HEAD full remains environment pending.
