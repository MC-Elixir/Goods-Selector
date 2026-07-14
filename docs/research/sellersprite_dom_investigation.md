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

Both the host-side directory and the Docker path were writable. After the user
confirmed Chrome's download prompt, a real XLSX export was received. The
filename identifies the Amazon-US ASIN and a result count; it is intentionally
not reproduced here. The file contained 1,109 normalized rows and was
persisted with SHA-256
`5b25b3e03d15f9b931b1c97a5ebdb057a58c7d450d5f3a1c1e2b7b00124d0763`.

The sanitized export header list was:

`流量词`, `关键词翻译`, `AC推荐词`, `流量占比`, `预估周曝光量`, `关键词类型`,
`转化效果`, `流量词类型`, `自然流量占比`, `广告流量占比`, `自然排名`,
`自然排名页码`, `更新时间` (twice), `广告排名`, `广告排名页码`, `ABA周排名`,
`月搜索量`, `SPR`, `标题密度`, `购买量`, `购买率`, `展示量`, `点击量`, `商品数`,
`需供比`, `广告竞品数`, `点击总占比`, `转化总占比`, `PPC价格`, `建议竞价范围`,
`前十ASIN`.

The importer now maps `流量词` to `keyword` and `商品数` to
`competing_products`, and accepts duplicate unmapped headers such as the two
`更新时间` columns. On 2026-07-14, a read-only live panel inspection showed an
authenticated result view but no permission-required or quota-exhausted
terminal state. Therefore no quota locator is committed or implied by this
record. The local profile supports an optional `quota_required` selector only
after that vendor state is observed and reviewed.

The daily workflow now uses the volume-backed
`data/sellersprite_browser_config.json` and applies CDP
`Browser.setDownloadBehavior` for only the attached browser lifetime before
the single export click. Its no-prompt automatic E2E still requires a new
explicit approved live verification; it is not claimed by this investigation.

## Safety and acceptance gate

No cookies, account identifiers, secrets, browser history, query results, or
screenshots are recorded here. The login terminal outcome was not retried or
bypassed.

Do not invent a permission or quota locator from normal-page text. The
user-approved controlled export has proved the artifact, headers, import
normalization, and SQLite manifest; automatic no-prompt download and any
unobserved terminal-state locator each remain separate verification gates.
