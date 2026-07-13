# SellerSprite Phase-0 Live DOM Investigation

## Status

Live DOM investigation was performed with the user present on an Amazon US
product page. It established real extension boundaries and terminal-state
markers, but it did **not** complete an export/import E2E because the
SellerSprite login session expired before the export step. Browser export
remains disabled by default.

## Sanitized observations

- Observation window: 2026-07-13 to 2026-07-14 (Asia/Shanghai).
- Extension version displayed in the UI: `v5.0.4`.
- The extension is injected into the Amazon document below
  `#main-sellersprite-extension`; no extension iframe or open shadow root was
  observed.
- The collapsed entry control is
  `css=#main-sellersprite-extension .logo-btn-container`.
- The expanded-panel ready signal is
  `css=#main-sellersprite-extension #ext-main-box`.
- The visible reverse-keyword navigation control is
  `css=#main-sellersprite-extension .nav-item-ext:has-text("关键词反查")`.
- The ASIN input is
  `css=#main-sellersprite-extension input[name="field-keywords"]`.
- The visible submit control is
  `css=#main-sellersprite-extension form[name="header-search-form"] .input-group-suffix`.
- The reverse-result readiness signal is
  `css=#main-sellersprite-extension .result-number-bar`.
- In the observed window layout, the export action is first moved into the
  visible extension control
  `css=#main-sellersprite-extension .footer-nex .more-btn`. Clicking it opens
  a document-level Element Plus popover, where the export button is
  `css=[id^="el-popper-container"] button:has-text("导出")`. The action is
  opened before the download-directory snapshot and clicked exactly once.
- The captcha terminal marker exists as
  `css=#main-sellersprite-extension .robot-card-container`; it was present but
  not visible during the authenticated observation.
- On 2026-07-14 the actual login terminal view was observed as
  `css=#main-sellersprite-extension .ext-sign-in-container`, with visible
  user-login text. This maps to `SELLERSPRITE_LOGIN_REQUIRED`.
- No permission-required state was observed. The local non-production profile
  uses the conservative visible-text fallback `text=权限`; it is not treated as
  a verified permission-state marker until that state is observed.

## Download mapping

The user configured Chrome to download to the project-controlled WSL path:

- Chrome/Windows path:
  `\\wsl.localhost\Ubuntu\home\dell\code\amazon_selector\data\imports\sellersprite`
- Docker path: `/app/data/imports/sellersprite`

Both the host-side directory and the Docker path were writable. No actual
export file was produced after this mapping was configured because the
extension reached `SELLERSPRITE_LOGIN_REQUIRED` before export. Filename, file
type, headers, and importer column mappings remain unverified.

## Safety and acceptance gate

No cookies, account identifiers, secrets, browser history, query results, or
screenshots are recorded here. The login terminal outcome was not retried or
bypassed.

Do not enable browser export or create a production locator profile until the
user re-authenticates in their visible Chrome session, a permission marker (if
shown) is recorded, and one controlled export proves the downloaded artifact,
headers, import normalization, and SQLite manifest. The opt-in E2E test also
requires explicit `SELLERSPRITE_E2E=1`; a skipped test is not verification.
