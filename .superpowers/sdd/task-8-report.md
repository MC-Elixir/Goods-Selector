# Task 8 Report: Safe 1688 Offer Detail Extraction and Provenance

## Scope

- Added fail-closed classification for auth, captcha, rate-limited, invalid, and offer-identity-mismatch pages.
- Added explicit nullable detail fields and per-field provenance with source type, observation time, confidence, and artifact hash.
- Preserved real MOQ and price tiers and extracted structured SKU, material, dimensions, weight, packaging, origin, lead-time, customization, supplier, transaction, image, certification, and return/dispute evidence.
- Reused the existing Playwright browser context, fetched details serially with configurable jitter, and bounded retries to timeouts and rate-limited pages. Auth/captcha become human-handoff results; invalid/unverified/mismatched artifacts become `blocked_invalid`; neither becomes a detail record.
- Added detail-cache schema, freshness timestamps, expiry, and blocked-record rejection.
- Kept the existing real-supplier cache guard: mock suppliers are not cacheable and no formal no-mock fallback was added.

## TDD evidence

The recovery agent could not recover the previous agent's original RED terminal output. It did produce fresh RED evidence for uncovered requirements:

```text
pytest ...test_offer_identity_mismatch_is_rejected ...test_best_structured_payload_is_selected_by_extracted_evidence ...test_detail_fetch_rejects_a_different_offer_identity -v
3 failed
- parse_1688_offer_detail_html did not accept expected_offer_id
- a mismatched offer page was incorrectly marked extracted
```

After the implementation, the selected Task 8 verification completed successfully:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_alibaba_detail.py tests/test_alibaba_playwright_detail.py tests/test_alibaba_result_cache.py tests/test_alibaba_diagnostics.py -v
34 passed in 0.76s
```

## Full-suite environment status

No second full `pytest tests/` run was started. The inherited full-suite process was reported as PID 61618 in uninterruptible `D` state waiting on host I/O/jbd2. During recovery PID 61618 later disappeared naturally and no `D`-state pytest process remained, but its exit code and pytest summary were not recoverable. Therefore there is no full-suite result for Task 8 and this report does not claim that the full suite passed.

## Review follow-up

A follow-up commit tightened the established production enrichment path:

- `Alibaba1688PlaywrightMatcher.enrich_supplier_detail` now passes both `supplier.alibaba_offer_id` and the final Playwright page URL into parsing before applying evidence.
- Embedded offer IDs and final/canonical offer URLs are independent identity sources. An expected ID with no identity evidence fails as `OFFER_ID_UNVERIFIED`; any mismatched or conflicting identity evidence fails as `OFFER_ID_MISMATCH`.
- Structured fields override visible-text evidence only when their field provenance is `extracted`; structured missing values no longer erase extracted fallback evidence.
- A page now needs an explicit offer identity or at least two distinct product-detail marker groups. A lone `商品详情` heading is rejected.
- Search-card MOQ remains `None` when absent.
- Only auth/captcha map to `human_handoff`; invalid/unverified/mismatched pages map to `blocked_invalid`, and rate limiting remains retryable.
- Matcher-level coverage verifies invalid detail is neither applied nor cached.

Fresh follow-up focused verification:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_alibaba_detail.py tests/test_alibaba_playwright_detail.py tests/test_alibaba_result_cache.py tests/test_alibaba_diagnostics.py tests/test_matchers_manual_queue.py -v
52 passed in 0.80s
```

A fresh full-suite attempt was started because host I/O initially appeared normal. Pytest PID 72890 temporarily entered `Dsl` state at `jbd2_log_wait_commit`; it was not force-killed and later resumed naturally. The command completed with exit code 0:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q
551 passed, 5 skipped, 210 warnings in 196.00s (0:03:16)
```

## Authoritative identity follow-up

Identity evidence is now restricted to the final page URL, HTML canonical URL, and the direct primary `offerId` on the same structured payload selected for detail evidence. Related/recommended offer links and nested related-offer IDs are ignored. Any authoritative source conflict fails closed, while absence across all three sources remains `OFFER_ID_UNVERIFIED`.

Fresh focused verification after this change:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_alibaba_detail.py tests/test_alibaba_playwright_detail.py tests/test_alibaba_result_cache.py tests/test_alibaba_diagnostics.py tests/test_matchers_manual_queue.py -q
56 passed in 0.89s
```

Fresh full-suite verification also completed with exit code 0 after a temporary, naturally recovered `jbd2_log_wait_commit` wait:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q
556 passed, 5 skipped, 210 warnings in 225.61s (0:03:45)
```

## Files

- `matchers/alibaba_detail.py`
- `matchers/_alibaba_playwright_search.py`
- `matchers/alibaba_result_cache.py`
- `matchers/alibaba_playwright.py`
- `tests/test_alibaba_detail.py`
- `tests/test_alibaba_playwright_detail.py`
- `tests/test_alibaba_result_cache.py`
- `tests/test_matchers_manual_queue.py`
