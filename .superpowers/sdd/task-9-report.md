# Task 9 Report: Structured Match Evidence and Minimum Evidence Threshold

## Status

Implemented `build_match_evidence()` as a standalone deterministic matcher. It consumes
`AmazonProductUnderstanding`, an enriched `SupplierDTO`, and an optional strict visual
classification dictionary. It does not modify or integrate the linear pipeline.

## Implementation

- Added `matchers/match_evidence.py`.
- Added hard-negative precedence for:
  - replacement/accessory versus full-product conflicts;
  - package quantity conflicts;
  - core function conflicts;
  - brand-exclusive versus generic sourcing conflicts;
  - explicit capacity, dimensions, material, and pack-count spec conflicts;
  - visual `is_match: false` classifications.
- Added minimum evidence requirements for function, package quantity, product type,
  price, and MOQ. Missing critical evidence forces `retry` with confidence capped at
  `0.49`; malformed visual classifications force `manual_review` with the same cap.
- Added explicit `passed_reasons`, `mismatch_reasons`, and `missing_evidence` output.
- Treats classification confidence only as confidence in the boolean classification,
  never as image similarity.
- Consumes Task 3 `raw_data["visual_match"]` classification metadata when present and
  preserves legacy `SupplierDTO.image_similarity` as a separate ranking signal.
- Rejects or downgrades malformed/non-finite evidence without allowing it into Pydantic
  score fields.

## TDD Evidence

RED:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_match_evidence.py -v
ModuleNotFoundError: No module named 'matchers.match_evidence'
```

GREEN / focused regression:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_match_evidence.py tests/test_product_spec.py tests/test_verifier_spec_match.py -v
32 passed in 0.72s
```

Full suite:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/ -q
1 failed, 571 passed, 5 skipped in 236.52s
```

The single failure was the existing asynchronous runtime timeout
`tests/test_agent_runtime.py::test_runtime_persists_job_history_to_disk`. An immediate
isolated rerun passed:

```text
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_agent_runtime.py::test_runtime_persists_job_history_to_disk -v -s
1 passed in 1.55s
```

## Coverage Added

- replacement component versus complete machine;
- one item versus four-pack;
- core function conflict;
- brand-exclusive replacement part;
- missing function and pack evidence;
- missing price and MOQ;
- explicit key specification conflict;
- negative visual classification;
- complete positive evidence;
- NaN and positive/negative infinity;
- malformed visual dictionaries;
- Task 3 visual metadata compatibility.

## Remaining Concern

The enriched supplier detail contract does not yet define a normalized brand
compatibility enum. Task 9 therefore recognizes `brand_compatibility` values containing
`only`, `专用`, `原装`, or `exclusive`, as well as excluded Amazon brand tokens. A future
detail schema should replace these compatibility aliases with a validated enum without
weakening the hard-negative rule.
