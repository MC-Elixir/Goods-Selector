# Task 8 Report: Safe 1688 Offer Detail Extraction and Provenance

## Scope

- Added fail-closed classification for auth, captcha, rate-limited, invalid, and offer-identity-mismatch pages.
- Added explicit nullable detail fields and per-field provenance with source type, observation time, confidence, and artifact hash.
- Preserved real MOQ and price tiers and extracted structured SKU, material, dimensions, weight, packaging, origin, lead-time, customization, supplier, transaction, image, certification, and return/dispute evidence.
- Reused the existing Playwright browser context, fetched details serially with configurable jitter, and bounded retries to timeouts and rate-limited pages. Auth/captcha and other blocked artifacts become handoff results and never become detail records.
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

## Files

- `matchers/alibaba_detail.py`
- `matchers/_alibaba_playwright_search.py`
- `matchers/alibaba_result_cache.py`
- `tests/test_alibaba_detail.py`
- `tests/test_alibaba_playwright_detail.py`
- `tests/test_alibaba_result_cache.py`
