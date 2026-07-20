# Task 5 Report: SellerSprite preflight, configuration status, and HTTP API

## Status

Implemented the isolated SellerSprite browser readiness signal and the bounded
reverse-keyword HTTP API. The pre-existing MJJL market-data guard and generic
Browser Assistant routes were left unchanged.

## RED evidence

Before production code, the source-mounted Docker test command failed as
expected because the new route, status block, and preflight check did not yet
exist:

```text
7 failed, 28 passed
```

The missing behavior was explicit in the failures:

- `POST /api/sellersprite/reverse-keywords` returned `404` instead of input
  validation responses.
- `agent.server.run_reverse_keyword_export` did not exist for route dispatch.
- `agent.preflight._check_seller_sprite_browser` did not exist.
- `get_config_status()` lacked `seller_sprite_browser`.

## Implementation

- Added `POST /api/sellersprite/reverse-keywords`, accepting only the existing
  JSON-object request shape. It validates a normalized ASIN and an optional
  canonical UUID `sourcing_run_id` before delegating exactly once to
  `run_reverse_keyword_export`.
- Business outcomes remain HTTP 200 and are serialized as a stable safe
  response with `status`, `error_code`, correlation context, and an explicit
  evidence allowlist (`row_count`, string keyword list, UUID manifest ID).
  Source paths, cookies, CDP addresses, raw manifests, and arbitrary result
  fields are not returned.
- Added the `seller_sprite_browser` status block with booleans and numeric
  budgets only; configured host/container paths and profile contents are not
  exposed.
- Added a distinct warning-only browser preflight check. It verifies browser
  enablement, a validated locator profile, writable configured container
  download directory, and a usable resolved CDP websocket. It never consults
  the MJJL API key or changes market-data guard behavior.

## GREEN evidence

Focused source-mounted Docker run:

```bash
TEST_DATA=$(mktemp -d)
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e LOG_DIR=/app/data/logs \
  -v "$PWD:/app:ro" -v "$TEST_DATA:/app/data" -w /app \
  --entrypoint pytest amazon-selector:dev \
  tests/test_agent_server.py tests/test_preflight.py \
  tests/test_config_status.py tests/test_browser_agent.py \
  -q -s -p no:cacheprovider
```

Result: `44 passed in 4.06s`.

`git diff --check` was clean before commit.

## Files changed

- `agent/preflight.py`
- `agent/config_status.py`
- `agent/server.py`
- `tests/test_preflight.py`
- `tests/test_config_status.py`
- `tests/test_agent_server.py`

## Self-review

- Confirmed the endpoint has no host, path, profile, cookie, or CDP URL input.
- Confirmed invalid ASIN, UUID, and non-object JSON return clean 400 JSON
  errors before workflow dispatch.
- Confirmed the endpoint uses one service invocation and treats documented
  workflow outcomes as data rather than transport errors.
- Confirmed browser preflight is advisory (`ok` or `warning` only), independent
  of MJJL configuration, and generic Browser Assistant tests still pass.
- No user modifications outside Task 5 files were staged; the shared SDD
  ledger and Task 4 report remain uncommitted.
