# Task 6 Report: Structured Amazon Product Understanding

## Status

Implemented and verified.

## RED

Command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py -v
```

Observed expected collection failure: `ModuleNotFoundError: No module named 'matchers.product_understanding'`.

## GREEN

Focused command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py -v
```

Result: `6 passed`.

Compatibility command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py tests/test_vision_matcher.py tests/test_matcher_keywords.py -v
```

Result: `36 passed`.

## Full Suite

Command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q --disable-warnings
```

Result: `505 passed, 5 skipped, 210 warnings in 358.68s` (exit code 0).

## Files

- `matchers/product_understanding.py`: payload adapter, image collection, strict canonical schema validation, and deterministic brand exclusion.
- `matchers/vision_analyzer.py`: provider-neutral structured product analysis for PPIO and Anthropic, all-image request construction, strict JSON parsing, real backend metadata, and isolated content-addressed caching.
- `tests/test_product_understanding.py`: all-text/all-image input, deduplication and cap, brand exclusion, fail-closed validation, backend metadata, and cache identity coverage.
- `.superpowers/sdd/task-6-report.md`: this report.

## Self-check

- `VisionAnalyzer.analyze()` remains unchanged and its legacy tests pass.
- No real external API was invoked; provider clients and image downloads are mocked in new tests.
- The structured prompt requests every `AmazonProductUnderstanding` field and explicitly covers replacement/consumable/full product classification, package quantity, visible-only dimensions, and uncertainty.
- Pydantic `AmazonProductUnderstanding.model_validate()` is the fail-closed schema boundary.
- Brand is retained in `excluded_brand_tokens` and deterministically removed from supplier keyword copy.
- Structured cache keys use the prompt version, provider, model, canonical text JSON, and the SHA-256 hash of every downloaded image. The `apu_` key namespace cannot collide with the legacy `va_` single-image key.
- Diff scope contains only Task 6 implementation, tests, and this report.

## Concerns

- Image downloads remain sequential, matching the existing analyzer's simple synchronous runtime model. This is intentionally not expanded into a concurrency refactor for Task 6.
- Existing suite warnings were not changed as part of this task.

## Review Fix Follow-up

### RED

Added review regressions for explicit semantic-field presence, strict types, extra fields,
prompt-content cache identity, layered safe errors, multi-token/alias brand cleaning, and
parsed URL validation.

Command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py -v
```

Result before implementation: `13 failed, 6 passed`. A separate traceback-safety RED
also failed because a provider secret remained visible through exception chaining.

### GREEN and compatibility

Command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py tests/test_vision_matcher.py tests/test_matcher_keywords.py -v
```

Result: `49 passed`.

### Full suite

Command:

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q --disable-warnings
```

Result: `518 passed, 5 skipped, 210 warnings in 229.67s` (exit code 0).

### Review-fix self-check

- All semantic model fields must be explicitly present; only ASIN, original title, and
  provider/model/prompt metadata are runtime-owned and overwritten at the boundary.
- Final validation uses `model_validate(..., strict=True)` and continues to forbid extras.
- The structured cache identity now includes the SHA-256 of the actual prompt content.
- Stable safe codes distinguish `image_download_failure`, `provider_failure`,
  `json_parse_failure`, and `schema_validation`; suppressed exception chaining prevents
  raw responses and API keys from appearing in rendered tracebacks.
- Supplier-facing generic/supply-chain names are cleaned with the full product brand,
  reasonable brand words, and all model-provided exclusion aliases; contaminated supplier
  keyword entries are removed while exclusion evidence is retained.
- Image URLs require an HTTP(S) scheme and non-empty network location after parsing.
