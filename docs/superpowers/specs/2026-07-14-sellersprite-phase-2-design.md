# SellerSprite Phase 2 Design

## Goal

Turn the verified, human-supervised SellerSprite reverse-keyword workflow into
a daily local capability without changing a SellerSprite account, subscription,
or Chrome's persistent profile settings.

## Scope and invariants

- Marketplace remains Amazon US and each request accepts one ASIN only.
- No mock suppliers or synthetic keyword data are introduced.
- Browser actions remain profile-driven, visible, and bounded to one export
  click per request.
- Login, captcha, extension permission, quota, and download failures stop the
  workflow with a typed status. They are never retried by bypassing a vendor
  control.
- The default browser capability remains disabled until local configuration is
  explicitly saved and preflight passes.
- Chrome download configuration is temporary for the CDP-attached browser
  session: it is applied before an export and lost when Chrome exits. The
  implementation does not edit Chrome preferences or Windows registry state.

## Architecture

### Local configuration and readiness

The existing `data/sellersprite_live_locators.json` profile becomes a
user-controlled local artifact. A dedicated browser configuration API writes
only safe paths and boolean/timeout values to `.env`; it never returns or
stores cookies, account identifiers, or secrets. The Docker-facing path stays
`/app/data/imports/sellersprite` and maps to the project data directory.

`get_config_status()` and browser preflight expose one normalized capability
state:

- `ready`: CDP, validated profile, writable directory, and temporary download
  behavior probe are available.
- `needs_human`: login, captcha, extension permission, or quota is visible.
- `unavailable`: configuration, Chrome, or extension is unavailable.

The WebUI renders that state before enabling the export button and offers a
short, typed next action instead of generic failure text.

### Temporary CDP download behavior

`PlaywrightSellerSpriteSession` obtains a browser-level CDP session after
attaching to Chrome. Immediately before it snapshots the configured directory,
it calls `Browser.setDownloadBehavior` with `behavior="allow"`, the configured
container download directory, and download events enabled. This setting applies
only to the attached browser lifetime.

The browser adapter then opens the profile-defined export menu, snapshots the
directory, clicks the one export control, and observes exactly one new,
completed file. A failed CDP configuration maps to `DOWNLOAD_TIMEOUT` or
`EXTENSION_UNAVAILABLE` without clicking Export.

### Typed human handoff

The browser adapter detects the observed login and captcha selectors first.
It additionally recognizes a profile-defined permission/entitlement selector
and a profile-defined quota selector. Each maps to a safe error code:

- `SELLERSPRITE_LOGIN_REQUIRED`
- `CAPTCHA`
- `SELLERSPRITE_PERMISSION_REQUIRED`
- `SELLERSPRITE_QUOTA_EXCEEDED`

The service returns `NEEDS_HUMAN` for these terminal states and records a
sanitized run event. The UI displays the corresponding action: sign in,
complete verification, request extension permission, or wait/upgrade after a
quota limit. It never displays account details or raw vendor response text.

### WebUI operation and audit history

The existing reverse-keyword card remains the execution entrypoint. It gains a
capability badge, disabled/running state, and current download-policy status.
On success it still renders at most 20 normalized keyword rows.

An additive history endpoint returns a paginated, sanitized list of persisted
SellerSprite manifests: manifest ID, Amazon US ASIN, observed/imported time,
row count, file type, SHA-256, status, and safe error code. The UI renders a
compact audit table with no raw rows, cookies, account names, or local absolute
paths. Selecting a history item shows its immutable metadata only; it does not
re-import or re-download a file.

## Data flow

```text
WebUI capability check
  -> config/preflight
  -> CDP + profile + download-policy verification
  -> enabled export action
  -> Amazon US page / SellerSprite panel
  -> typed terminal check
  -> temporary Browser.setDownloadBehavior
  -> one export click and observed download
  -> importer / SQLite manifest
  -> bounded keyword preview + audit history
```

## Testing and acceptance

- Unit tests cover safe local configuration, status derivation, CDP download
  behavior success/failure, and typed quota/permission handoff.
- Browser adapter tests prove download behavior is configured before the
  directory snapshot and export click.
- Repository/API tests cover manifest history ordering, pagination, and
  response sanitization.
- WebUI tests cover capability status, human handoff text, history rendering,
  and disabled export behavior.
- A user-approved live run confirms Chrome writes directly to the configured
  directory without a save prompt, then verifies the imported manifest and
  WebUI audit row.
- Full pytest and Docker WebUI health checks must pass before completion.

## Explicit non-goals

- No Chrome preference, Windows registry, account, subscription, or extension
  permission mutation.
- No background polling, bulk ASIN export, seller communication, or purchase.
- No automatic captcha/login solving, quota bypass, or raw export download API.
