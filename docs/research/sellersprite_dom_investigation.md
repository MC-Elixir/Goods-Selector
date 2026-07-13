# SellerSprite Phase-0 Live DOM Investigation

## Status

**Pending live investigation.** No signed-in SellerSprite session has been
observed for this repository, and no browser automation has been enabled for
it. This is intentionally a record of what is *not yet known*, rather than a
synthetic locator-profile or a claim of live verification.

## Findings recorded so far

None. In particular, this repository has not recorded any of the following as
live findings:

- SellerSprite panel location or stable DOM / iframe / shadow-DOM locators;
- locator-profile values for `ready`, login, permission, captcha, reverse
  keyword, input, submit, results, or export controls;
- extension version;
- login, captcha, or permission indicators;
- export headers or column mappings;
- host-to-container download-directory mapping;
- observation time, screenshots, or an E2E result.

No locator-profile file is checked in or implied by this document. Browser
export remains disabled by default.

## Required live-session procedure

Perform this investigation only with a user present, after that user has
signed in to SellerSprite in their own visible Chrome profile and has expressly
approved the investigation. Use one Amazon **US** ASIN. Do not bypass login,
captcha, account permissions, rate limits, or quotas, and do not purchase,
message sellers, alter account settings, or alter a subscription.

Before any automatic action is enabled, record only sanitized observations:

1. Time of observation and extension version.
2. Stable documented locator-profile keys and values, without coordinates.
3. Panel location and any iframe or shadow-DOM boundary.
4. Visible login, captcha, and permission indicators.
5. Actual export header list and observed download filename/type.
6. The separately controlled Windows-host and Docker-container download
   directories.

Do not record cookies, account identifiers, secrets, browser history, or
screenshots containing personal data. If a login, captcha, or permission state
is encountered, record the typed terminal status only; leave browser export
disabled and do not retry or bypass it.

## Acceptance gate

The live E2E test may be run only after this record contains real sanitized
findings, a reviewed local locator profile exists outside source control, the
download mapping is verified, and the user explicitly sets
`SELLERSPRITE_E2E=1`. A skipped test is not a live verification result.
