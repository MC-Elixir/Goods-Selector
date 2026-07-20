# Task 4 Report: Deterministic SellerSprite CDP browser workflow

## Status

Implemented the isolated, profile-driven SellerSprite browser adapter and the
single-ASIN service orchestration. The existing generic browser assistant and
seven-stage sourcing pipeline are unchanged.

## RED evidence

Before implementation, the source-mounted test command failed during
collection as expected because both new modules were absent:

```text
ModuleNotFoundError: No module named 'agent.tools.sellersprite_browser'
ModuleNotFoundError: No module named 'agent.sellersprite_service'
```

The subsequent locator-boundary regression also failed as expected before the
adapter gained explicit iframe/shadow handling:

```text
FAILED test_adapter_uses_explicit_profile_boundary_for_frame_or_shadow[iframe]
FAILED test_adapter_uses_explicit_profile_boundary_for_frame_or_shadow[shadow]
```

## Implementation

- Added `PlaywrightSellerSpriteSession`, which attaches through the existing
  `_resolve_cdp_ws()` path, navigates only to canonical Amazon US `/dp/<ASIN>`
  URLs, and verifies the final ASIN before any SellerSprite action.
- Browser interaction uses only the supplied validated locator profile. Direct
  malformed profiles fail closed, and iframe/shadow locators require an
  explicit documented `outer >> inner` boundary. No coordinate or generated
  selector interaction exists.
- Login, permission, and captcha markers stop immediately without a click or
  retry. Missing profile/ready/action locators fail closed as
  `EXTENSION_UNAVAILABLE`.
- The adapter snapshots the configured download directory before one export
  click, then delegates new-download detection and import normalization to the
  prior task layers.
- Added `run_reverse_keyword_export()` with injectable session, observer,
  importer, repository, event recorder, clock, sleeper, and cancellation
  predicate. It persists only after successful readable import, emits
  sanitized structured run events, and permits one retry only for
  `EXPORT_FAILED` and `DOWNLOAD_TIMEOUT`.

## GREEN evidence

Focused source-mounted Docker run:

```bash
TEST_DATA=$(mktemp -d)
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e LOG_DIR=/app/data/logs \
  -v "$PWD:/app:ro" -v "$TEST_DATA:/app/data" -w /app \
  --entrypoint pytest amazon-selector:dev \
  tests/test_sellersprite_browser.py tests/test_sellersprite_service.py \
  -q -s -p no:cacheprovider
```

Result: `21 passed in 1.29s`.

Task 1–4 SellerSprite regression run:

```text
tests/test_sellersprite_models.py
tests/test_browser_downloads.py
tests/test_sellersprite_importer.py
tests/test_sellersprite_repository.py
tests/test_sellersprite_browser.py
tests/test_sellersprite_service.py
```

Result: `98 passed in 24.28s`.

`git diff --check` was clean before commit.

## Files changed

- `agent/tools/sellersprite_browser.py`
- `agent/sellersprite_service.py`
- `tests/test_sellersprite_browser.py`
- `tests/test_sellersprite_service.py`

Commit: `622a41c feat: automate sellersprite reverse keyword export`

## Self-review

- Confirmed all SellerSprite interactions originate in the active profile and
  are never coordinate-based.
- Confirmed Amazon target and final-page ASIN match occur before extension
  actions.
- Confirmed non-retryable terminal outcomes neither persist nor start a second
  browser attempt; transient failures are capped at one retry.
- Confirmed event payloads include correlation IDs/ASIN and only safe error,
  digest, row-count, or manifest fields—never paths, cookies, or exceptions.
- No user modifications outside the Task 4 files were staged; the shared SDD
  progress ledger remains uncommitted.
