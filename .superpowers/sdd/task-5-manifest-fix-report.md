# Task 5 Manifest-ID Evidence-Chain Fix

## Scope

Re-review identified that the service could publish `SUCCESS` when a repository
returned no manifest ID or an arbitrary string. This focused follow-up changes
only the SellerSprite service/API evidence boundary and their tests.

## RED evidence

Before the fix, the source-mounted Docker focused run failed with six
discriminating cases:

- service results were `SUCCESS` for a missing, invalid, or uppercase
  non-canonical persisted manifest ID;
- HTTP responses were `SUCCESS` for injected service data with the same three
  invalid manifest-ID variants.

The initial focused result was `6 failed, 37 passed`.

## Fix

- The service now accepts a persisted manifest ID only when it is an exact,
  canonical UUID string. Otherwise it produces the safe terminal `INTERNAL`
  result after recording the artifact SHA-256 export event and before emitting
  `sellersprite_imported`.
- The HTTP allowlist uses the same canonical-ID rule, so malformed injected
  success data is converted to `INTERNAL` instead of being claimed as a valid
  export.
- The service fake repository now returns a deterministic valid UUID.

## Verification

Focused source-mounted Docker run:

```text
tests/test_sellersprite_service.py tests/test_agent_server.py
43 passed, 2 warnings in 7.40s
```

Serial Task 1–5 SellerSprite regression in a source-mounted, isolated Docker
container:

```text
tests/test_sellersprite_models.py
tests/test_browser_downloads.py
tests/test_sellersprite_importer.py
tests/test_sellersprite_repository.py
tests/test_sellersprite_browser.py
tests/test_sellersprite_service.py
tests/test_agent_server.py
tests/test_preflight.py
tests/test_config_status.py
tests/test_browser_agent.py
162 passed, 2 warnings in 22.81s
```

## Self-review

- Repository exceptions retain their existing `INTERNAL` terminal behavior.
- The artifact SHA-256 audit event remains before persistence and malformed
  persistence output never emits `sellersprite_imported`.
- The API cannot re-label missing, malformed, or non-canonical manifest IDs as
  success even if a dependency returns an invalid injected result.
