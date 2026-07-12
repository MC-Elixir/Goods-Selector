# SellerSprite Browser Automation MVP Design

**Date:** 2026-07-12
**Status:** Ready for user review
**Scope:** Phase 1 only — one Amazon US ASIN, SellerSprite reverse-keyword export, artifact import, and evidence preservation.

## 1. Goal and scope

Deliver a controlled vertical slice:

```text
ASIN
→ preflight Chrome/CDP and SellerSprite state
→ open Amazon US product page
→ verify Amazon and SellerSprite ASIN agreement
→ run reverse-keyword query
→ export file
→ observe download completion
→ parse Excel/CSV
→ preserve raw artifact and normalized evidence
→ show the first 20 keyword rows and an actionable status
```

The slice is additive. It must not change the default deterministic
`run_pipeline()` route, reintroduce non-US marketplaces, or allow mock
suppliers into formal results.

Phase 1 does **not** implement competitor export, market-analysis export,
BSR clustering, a second supplier platform, or the complete Agentic FSM. It
creates a stable typed browser tool that those later phases can reuse.

## 2. Constraints and safety policy

- Operate only the user's already authenticated Chrome and the capabilities
  visibly available to that account.
- Never purchase, add to cart, contact a seller, alter account settings,
  change a plan, or bypass login, captcha, rate limit, or membership gates.
- On an auth, captcha, permission, quota, or unobservable-plugin blocker,
  stop immediately with `NEEDS_HUMAN` and a precise reason code.
- Use role, visible text, stable attributes, iframe, and shadow-DOM locators in
  that order. Absolute coordinates are prohibited except for an explicitly
  documented manual recovery operation, which Phase 1 does not implement.
- Limit one ASIN per task, one normal attempt plus one retry, a 45-second page
  budget, a 120-second download budget, and a five-second minimum action
  interval.
- Keep the browser allow-list closed. Additional SellerSprite hosts are added
  only after Phase 0 proves that the visible workflow actually navigates there.

## 3. Chosen architecture

Use a deterministic Playwright adapter attached to the existing Chrome CDP
endpoint. The present `browser-use` sidecar remains available for generic
diagnostics, but is not the SellerSprite executor: it currently opens a tab
and reports page information rather than performing typed, replayable UI
actions.

```text
WebUI/API
  → SellerSprite service
    → CDP adapter (existing host Chrome)
    → download observer
    → importer/normalizer
    → artifact manifest + field evidence + run events
```

The adapter owns browser interaction only. The download observer owns file
stability and hashing. The importer owns parsing and normalization. Persistence
owns evidence and correlation. This makes every layer unit-testable without a
real browser or SellerSprite account.

## 4. Phase 0 gate: real DOM and download investigation

Before the automated action is enabled, a signed-in user session must produce
`docs/research/sellersprite_dom_investigation.md`. It records, without secrets:

1. whether the SellerSprite panel is in the Amazon document, an iframe, a
   shadow root, a browser-action popup, or a separately opened extension page;
2. stable locators for the panel-ready signal, reverse-keyword navigation, ASIN
   input, submit action, result-ready signal, and export action;
3. expected login, permission, quota, and captcha indicators;
4. the actual export extension, headers, and a sanitized sample schema; and
5. a Windows-visible download path and its matching container path.

If the required UI exists only in a non-automatable browser-action popup or no
stable locator is available, automated export is disabled. The importer remains
usable for a manually exported file and the task returns `NEEDS_HUMAN`; no
selector guessing or permission bypass is permitted.

## 5. Components and interfaces

### 5.1 SellerSprite browser service

New additive modules:

```text
agent/tools/sellersprite_browser.py
agent/tools/browser_downloads.py
agent/tools/sellersprite_importer.py
agent/sellersprite_models.py
agent/sellersprite_policy.py
```

The service exposes five typed operations:

```text
check_sellersprite_extension(context)
open_amazon_product(context, asin)
export_sellersprite_reverse_keywords(context, asin)
wait_for_browser_download(context, baseline)
import_sellersprite_export(context, artifact)
```

Every result carries `sourcing_run_id`, `call_id`, `asin`, timestamp, status,
error code, sanitized diagnostics, and artifact references. `sourcing_run_id`
is a canonical UUID generated for this browser task; a later pipeline
`RunLog.id` is stored separately as an optional legacy alias. The two IDs are
never conflated.

### 5.2 Browser connection and target selection

The adapter reuses the current CDP HTTP-to-WebSocket resolution, including its
Docker host-header handling. It attaches through Playwright CDP, selects or
opens exactly one `amazon.com/dp/<ASIN>` page, and verifies the visible or
canonical ASIN before taking SellerSprite actions.

The extension check reports one of:

```text
SUCCESS
EXTENSION_UNAVAILABLE
SELLERSPRITE_LOGIN_REQUIRED
SELLERSPRITE_PERMISSION_REQUIRED
CAPTCHA
NEEDS_HUMAN
```

It does not claim that an installed extension is available solely because Chrome
is reachable. A positive result requires the Phase-0 documented ready signal.

### 5.3 Download boundary

Configuration supplies a container-visible input directory and an explicitly
mapped Windows host download directory. The default artifact hierarchy is:

```text
data/imports/sellersprite/
  raw/reverse_keywords/
  normalized/
  failed/
  manifests/
```

The observer snapshots existing files before export, identifies a new allowed
`.xlsx`, `.xls`, or `.csv` file, ignores `.crdownload`, waits for size
stability, validates readability, calculates SHA-256, and rejects stale or
ambiguous files. It returns `DOWNLOAD_TIMEOUT`, `EXPORT_FAILED`, or
`INVALID_EXPORT` rather than selecting an old download.

The current Docker `./data:/app/data` mount covers the container side. Phase 0
must prove the corresponding Windows Chrome path; it is intentionally not
assumed from the current WSL checkout path.

### 5.4 Import and evidence model

The importer detects CSV/Excel, normalizes known headers, preserves original
text, converts currencies and durations conservatively, and leaves unknown or
absent values as `null`. `10K+` remains a lower bound/range instead of a made-up
exact number. Parent/child ASIN distinctions and duplicate rows are retained in
raw data while normalized rows are deduplicated by their documented keys.

Each artifact receives a manifest with source, type, hash, row count, observed
time, call/run IDs, ASIN, schema version, and status. A small additive
`sellersprite_imports` table stores the manifest and import diagnostics;
normalized keyword rows are stored as JSON payloads referenced by import ID in
Phase 1. A dedicated query-optimized keyword table is deferred to the
competitor/keyword-analysis phase.

The existing `field_evidence.status` contract does not allow `estimated`.
SellerSprite figures therefore use:

```text
status = extracted
measurement_kind = vendor_estimate
source_provider = sellersprite
source_type = browser_extension_export
```

`measurement_kind` is additive metadata in the manifest/raw evidence payload.
Missing values use `status = missing` and `value = null`; browser-export data is
never marked `verified` merely because it is non-empty.

### 5.5 API and WebUI

Add a focused endpoint rather than overloading the generic browser assistant:

```text
POST /api/sellersprite/reverse-keywords
{ "asin": "B00Q7OAN50" }
```

It returns business statuses, progress events, first 20 normalized keyword
rows, and an import summary. The WebUI gains a compact SellerSprite card with
an ASIN field, start button, human-action message, and concise result table.
It does not render raw browser JSON as the primary UI.

The existing generic Browser Assistant stays intact for 1688 diagnostics. The
preflight and configuration status gain a separate browser-export readiness
check; browser-derived market evidence can satisfy the Phase-1 display/import
workflow without falsely requiring an MJJL API key. Pipeline scoring integration
is deferred until a later market-source policy phase.

## 6. Failure handling and retry policy

All actions are idempotent by `call_id` and produce a run event. Normalized
terminal outcomes are:

```text
SUCCESS
EXTENSION_UNAVAILABLE
SELLERSPRITE_LOGIN_REQUIRED
SELLERSPRITE_PERMISSION_REQUIRED
CAPTCHA
ASIN_MISMATCH
EXPORT_FAILED
DOWNLOAD_TIMEOUT
INVALID_EXPORT
NEEDS_HUMAN
CANCELLED
```

Only transient navigation and download failures may retry once. Login, captcha,
permission, ASIN mismatch, ambiguous download, and invalid schema never retry
automatically. Cancellation is checked before and after each browser and file
operation.

## 7. Tests and live verification

Unit tests use injected fake CDP pages and temporary download directories to
cover allow-listing, target-ASIN validation, locator failures, bounded retry,
download stability, hash generation, Excel/CSV parsing, null preservation,
numeric normalization, and every terminal error code.

HTTP and WebUI tests cover endpoint validation, business-status rendering, and
no regression to existing Browser Assistant functionality. Migration tests
verify an additive upgrade, SQLite integrity, and preservation of historical
rows.

A live E2E test is opt-in and requires the signed-in Chrome profile plus the
Phase-0 investigation record. It validates one approved Amazon US ASIN, export,
download, import, manifest hash, and at least the first 20 displayed keyword
rows. It is not treated as a CI-only simulation. Completion also requires full
`pytest tests/`, Docker rebuild, and a served WebUI check on port 8765.

## 8. Acceptance criteria

Phase 1 is complete only when all of the following are evidenced:

1. `B00Q7OAN50` opens on Amazon US and target ASIN agreement is checked.
2. The real SellerSprite-ready signal is documented and detected, or the task
   safely reports `EXTENSION_UNAVAILABLE`.
3. Reverse-keyword export uses documented stable locators, not coordinates.
4. A new download is distinguished from old and `.crdownload` files.
5. The artifact is readable, hashed, manifested, run-scoped, and import-linked.
6. Parsed output contains header list, row count, and first 20 keyword rows.
7. Missing values remain `null`; vendor estimates are not marked verified.
8. Login, captcha, permission, download, and schema failures return the
   required business status without unsafe retries.
9. Existing deterministic CLI, no-mock defaults, Amazon-US restriction, and
   generic Browser Assistant tests remain compatible.
10. The live controlled E2E, full test suite, database checks, Docker rebuild,
    and WebUI behavior are reported with any unresolved external blockers.
