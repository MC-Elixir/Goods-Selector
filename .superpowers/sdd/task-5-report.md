# Task 5 Report: Amazon Detail, Buy Box, and Market Evidence Enrichment

## Status

Implemented on top of `254299eff32743720b7b392a3acbd4ce6d427aef` with Amazon US and existing crawler interfaces preserved.

## RED

Command:

`TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_amazon_detail_evidence.py tests/test_maijiajingling.py -v`

Observed collection failures for the intended missing contracts:

- `extract_amazon_detail` did not exist.
- `MarketDataError` did not exist.

A subsequent legacy DTO test also failed at import because `apply_detail_evidence` did not exist.

## GREEN

Focused Task 5 and compatibility suite:

`TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_amazon_detail_evidence.py tests/test_amazon_search.py tests/test_crawlers.py tests/test_maijiajingling.py tests/test_seller_sprite_diagnostics.py tests/test_scoring.py -q`

Result: `137 passed, 10 warnings in 1.13s`.

## Full Suite

Initial required full-suite run:

`TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/`

Result: `490 passed, 5 skipped, 209 warnings in 180.68s`.

After the final safe-response-diagnostic addition, a second full-suite run produced `1 failed, 490 passed, 5 skipped`: `test_runtime_attaches_result_summary_after_success` exceeded its two-second asynchronous wait. Immediate isolated rerun of that unchanged test passed: `1 passed, 4 warnings in 1.36s`. This is recorded as a timing flake, not hidden as a clean rerun.

## Files

- `crawlers/_amazon_extractors.py`
- `crawlers/amazon_search.py`
- `analyzers/maijiajingling.py`
- `tests/test_amazon_detail_evidence.py`
- `tests/test_maijiajingling.py`
- `.superpowers/sdd/task-5-report.md`

## Self-check

- Detail extraction always returns a complete evidence-key envelope and represents absence as `EvidenceStatus.MISSING` with `None`.
- Extracted timestamps are timezone-aware and satisfy Task 1 `FieldEvidence` validation.
- Coupon, discount/list price, variations, buy box seller/fulfillment/count, package quantity/material/dimensions, images, bullets, description, A+, availability, and first-available evidence are included.
- Legacy DTO fields are copied only from `extracted`/`verified` evidence; complete serialized evidence remains under `raw_data["field_evidence"]`.
- Market evidence distinguishes `success`, `partial`, and `failed`; empty DTOs cannot report success.
- 401/403/invalid-key, 429, timeout, and missing response structure map to stable safe codes.
- SellerSprite diagnostics retain endpoint, timezone-aware response timestamp, and SHA-256 response hash without API keys or raw response bodies.
- No Task 6 visual-understanding or Task 11 orchestrator work was added.
- `git diff --check` passed.

## Concerns

- One unrelated asynchronous agent-runtime test timed out once in the final full-suite rerun and passed immediately in isolation, as detailed above.
- Secondary-image extraction supports the explicit page attribute contract plus URL text lists; backend-specific DOM adapters may provide richer image attributes in later integration work.
