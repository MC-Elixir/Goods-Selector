const state = {
  preflight: null,
  categories: [],
  jobs: [],
  executionNodes: {},
  runs: [],
  results: [],
  manualQueue: [],
  importedSuppliers: [],
  targetContractReviews: [],
  configStatus: null,
  browserSetup: null,
  trialFeedbackSummary: null,
  cookieSetupPhase: {},
  selectedBrowserOs: "windows",
  reviewFilter: "all",
  expandedReviews: new Set(),
  selectedAsin: "",
  activeSection: "trial",
  activeTrialJobId: localStorage.getItem("activeTrialJobId") || "",
  sellerSpriteKeywordRows: [],
  sellerSpriteImportHistory: [],
  lang: localStorage.getItem("agentLang") || "en",
  notificationEnabled: localStorage.getItem("backgroundNotifications") === "enabled",
  activeHumanAlert: null,
};

const DEFAULT_DOCUMENT_TITLE = document.title;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const I18N = {
  en: {
    "actions.download": "Download",
    "actions.downloadAccepted": "Download accepted",
    "actions.export": "Export",
    "actions.refresh": "Refresh",
    "actions.reloadResults": "Reload Results",
    "actions.reset": "Reset",
    "actions.cancel": "Cancel",
    "actions.delete": "Delete",
    "actions.retry": "Retry",
    "actions.resume": "Resume",
    "actions.forceRerun": "Force rerun",
    "actions.runAgent": "Run Agent",
    "actions.viewAll": "View all",
    "brand.subtitle": "Agent Console",
    "browser.cookieCheck": "1688 session check",
    "browser.offerUrl": "1688 offer URL",
    "browser.pageDiagnostic": "Page diagnostic",
    "browser.run": "Run Browser Assistant",
    "browser.running": "Running browser assistant",
    "browser.supplierDetail": "1688 detail enrich",
    "browser.taskType": "Browser task",
    "browser.url": "Page URL",
    "browserSetup.title": "Dedicated Chrome on port 9222",
    "browserSetup.check": "Check 9222",
    "browserSetup.guide": "Setup guide",
    "browserSetup.profileNote": "Chrome 136+ requires a non-default user data directory. Use this dedicated profile only for Amazon, 1688, and SellerSprite automation.",
    "browserSetup.copy": "Copy command",
    "browserSetup.copied": "Command copied",
    "browserSetup.security": "Keep port 9222 local. The agent can access pages and login sessions in this dedicated profile.",
    "browserSetup.ready": "Chrome 9222 ready",
    "browserSetup.missing": "Chrome 9222 unavailable",
    "sellersprite.reverseKeywords.title": "SellerSprite Reverse Keyword Export",
    "sellersprite.reverseKeywords.subtitle": "Export and import up to 20 structured reverse-keyword rows for one Amazon US ASIN.",
    "sellersprite.reverseKeywords.asin": "Amazon US ASIN",
    "sellersprite.reverseKeywords.asinPlaceholder": "10-character ASIN, for example B00Q7OAN50",
    "sellersprite.reverseKeywords.export": "Export reverse keywords",
    "sellersprite.reverseKeywords.running": "Exporting reverse keywords. Keep Chrome open.",
    "sellersprite.reverseKeywords.success": "Export imported successfully: {count} keyword rows available.",
    "sellersprite.reverseKeywords.showing": "Export imported successfully: Showing {shown} of {total} keyword rows.",
    "sellersprite.reverseKeywords.noRows": "The export completed, but no keyword rows are available to display.",
    "sellersprite.reverseKeywords.needsHuman": "SellerSprite needs your action in Chrome before this export can continue.",
    "sellersprite.reverseKeywords.captcha": "A SellerSprite captcha or verification is shown. Complete it in Chrome, then retry.",
    "sellersprite.reverseKeywords.authentication": "Sign in to SellerSprite in Chrome, then retry the export.",
    "sellersprite.reverseKeywords.permission": "Your SellerSprite account does not have permission for this export.",
    "sellersprite.reverseKeywords.disabled": "SellerSprite browser automation is disabled or unavailable. Enable it and verify the Chrome extension.",
    "sellersprite.reverseKeywords.cancelled": "The reverse-keyword export was cancelled.",
    "sellersprite.reverseKeywords.failed": "The reverse-keyword export could not be completed. Review the local service status and retry.",
    "sellersprite.reverseKeywords.requestFailed": "The local service could not start the reverse-keyword export. Check the ASIN and retry.",
    "sellersprite.reverseKeywords.table.keyword": "Keyword",
    "sellersprite.reverseKeywords.table.searchVolume": "Search volume",
    "sellersprite.reverseKeywords.table.purchaseRate": "Purchase rate",
    "sellersprite.reverseKeywords.table.competingProducts": "Competing products",
    "sellersprite.reverseKeywords.table.trend": "Trend",
    "chat.placeholder": "Ask about the current run or selected ASIN",
    "chat.send": "Send",
    "chat.title": "Selection Assistant",
    "hero.subtitle": "Launch sourcing runs, inspect preflight health, and read saved product candidates.",
    "hero.title": "Amazon Selector Agent",
    "jobs.noActive": "No active jobs",
    "jobs.noActiveHint": "Start an agent run to see progress here.",
    "notifications.enable": "Enable background alerts",
    "notifications.enabled": "Background alerts on",
    "notifications.denied": "Allow notifications in browser settings",
    "notifications.unsupported": "System alerts unavailable",
    "notifications.title": "Sourcing task needs attention",
    "notifications.view": "View",
    "manual.empty": "No blocked sourcing items",
    "manual.ignore": "Ignore",
    "manual.keywords": "Keywords",
    "manual.resolve": "Resolve",
    "manual.title": "1688 Manual Queue",
    "match.conflict": "conflict",
    "match.missing": "missing",
    "match.ok": "ok",
    "metrics.agent": "Agent",
    "metrics.cookieHealth": "Cookie Health",
    "nav.results": "Results Library",
    "nav.contractReview": "Contract Review",
    "nav.run": "Run Agent",
    "nav.trial": "One-click Research",
    "nav.research": "Market Research",
    "nav.settings": "Settings",
    "research.title": "Market Research — Seller Shortlist",
    "research.subtitle": "Turn a SellerSprite competitor export into a small-seller-friendly shortlist: seller, representative product, price, rating, reviews, launch date, monthly sales/revenue, and the fit reason.",
    "research.import.title": "Analyze a competitor export",
    "research.import.subtitle": "Place the SellerSprite competitor CSV/XLSX under data/imports, then enter its file name.",
    "research.browser.title": "Or drive the browser export",
    "research.browser.subtitle": "Requires the SellerSprite browser flow with competitor_* locators configured.",
    "research.niche": "Niche label",
    "research.keyword": "Keyword",
    "research.category": "Target category",
    "research.categoryAuto": "Auto-detect",
    "research.file": "Export file name",
    "research.url": "SellerSprite page URL (optional)",
    "research.aiReasons": "Generate AI fit reasons (falls back to rules)",
    "research.analyze": "Build shortlist",
    "research.runBrowser": "Run browser export",
    "research.history": "Recent research runs",
    "trial.kicker": "CONTROLLED TRIAL · REAL DATA",
    "trial.title": "One-click market research and 1688 sourcing",
    "trial.subtitle": "First open the target Amazon category or search list in the dedicated Chrome on port 9222. The job exports SellerSprite data, scores the market, selects ASINs, finds 1688 suppliers, and produces two Excel reports.",
    "trial.idle": "Ready to start",
    "trial.sourceMode": "Research source",
    "trial.categoryMode": "Amazon category list",
    "trial.keywordMode": "Amazon search list",
    "trial.englishHint": "Use the English query shown on Amazon US.",
    "trial.limit": "Top scored candidates for sourcing",
    "trial.aiReasons": "Generate optional AI research reasons",
    "trial.contract": "The trial uses real Amazon, SellerSprite, and 1688 data only. Missing login, captcha, or supplier evidence pauses or fails explicitly; mock results are never inserted.",
    "trial.start": "Start full research",
    "trial.openListHint": "Confirm the dedicated Chrome is showing the target Amazon list and the SellerSprite table has loaded.",
    "trial.progressTitle": "Workflow progress",
    "trial.noJob": "No trial job has been created",
    "trial.stagePreflight": "Environment and login checks",
    "trial.stagePreflightHint": "Chrome, cookies, download directory",
    "trial.stageResearch": "Market export and aggregate scoring",
    "trial.stageResearchHint": "Real SellerSprite list → research Excel",
    "trial.stageSourcing": "1688 sourcing and profit scoring",
    "trial.stageSourcingHint": "Top ASINs → supplier evidence",
    "trial.stageReport": "Candidate shortlist and delivery",
    "trial.stageReportHint": "Downloadable Excel / JSON",
    "trial.continue": "Handled — continue job",
    "trial.deliverables": "Deliverables",
    "trial.feedbackTitle": "Trial experience",
    "trial.feedbackHint": "After the job ends, take 20 seconds to tell us what worked and what needs improvement.",
    "trial.feedbackEase": "Ease of use (1–5)",
    "trial.feedbackUsefulness": "Report usefulness (1–5)",
    "trial.feedbackAgain": "Would use again",
    "trial.feedbackYes": "Yes",
    "trial.feedbackNo": "No",
    "trial.feedbackBlocked": "Main blocker",
    "trial.feedbackNone": "No blocker",
    "trial.feedbackPreflight": "Login / environment",
    "trial.feedbackResearch": "Market research",
    "trial.feedbackSourcing": "1688 sourcing",
    "trial.feedbackReport": "Understanding the report",
    "trial.feedbackComment": "Additional feedback (optional)",
    "trial.feedbackSubmit": "Submit feedback",
    "trial.feedbackSaved": "Feedback saved. Thank you.",
    "trial.validationTitle": "Trial acceptance",
    "trial.validationSubtitle": "Use completed real-job feedback to decide whether to begin the local installer phase.",
    "trial.validationNoData": "Waiting for real feedback",
    "trial.validationCollecting": "Collecting evidence",
    "trial.validationReady": "Ready for installer",
    "trial.validationImprove": "Improve before packaging",
    "trial.validationSamples": "Valid responses",
    "trial.validationCoverage": "Entry modes covered",
    "trial.validationDelivery": "Two-report delivery rate",
    "trial.validationEase": "Average ease",
    "trial.validationUsefulness": "Report usefulness",
    "trial.validationAgain": "Would use again",
    "trial.validationNoBlocker": "No main blocker",
    "trial.validationGates": "Installer entry gates",
    "trial.validationBlockers": "Blocker distribution",
    "trial.validationNoDataHint": "No real client feedback yet. Do not begin the installer phase.",
    "trial.validationCollectingHint": "{count} more completed trial response(s) required before a decision.",
    "trial.validationReadyHint": "All experience gates passed. The local installer phase may begin.",
    "trial.validationImproveHint": "The sample is sufficient, but one or more experience gates failed. Improve the workflow and trial again.",
    "trial.validationEmptyBlockers": "No blocker data yet.",
    "trial.validationGate.sample_size": "At least 3 completed trial responses",
    "trial.validationGate.source_mode_count": "Both category and keyword entry modes tested",
    "trial.validationGate.delivery_rate": "At least 2/3 deliver both report sets",
    "trial.validationGate.average_ease": "Average ease ≥ 4.0 / 5",
    "trial.validationGate.average_usefulness": "Report usefulness ≥ 4.0 / 5",
    "trial.validationGate.would_use_again_rate": "At least 2/3 would use again",
    "trial.validationGate.no_blocker_rate": "At least 2/3 report no main blocker",
    "trial.queued": "The full research job is queued. You may keep this page open.",
    "trial.ready": "All prerequisites detected. Keep the Amazon list open when starting.",
    "preflight.actionRequired": "Action required",
    "preflight.allPassed": "All blocking checks passed. Start a new sourcing run when ready.",
    "preflight.checking": "Checking",
    "preflight.initialBody": "The agent checks cookies, database, exports, and 1688 cooldown before running.",
    "preflight.needsReview": "Needs Review",
    "preflight.ready": "Ready",
    "preflight.readyToRun": "Ready to run",
    "preflight.resolveFailed": "Resolve the failed preflight items before launching a formal run.",
    "preflight.review": "Review",
    "preflight.title": "Preflight Checklist",
    "preflight.waiting": "Waiting for preflight",
    "session.title": "Complete browser sessions",
    "session.subtitle": "The agent can open the login page and securely save site-scoped cookies after you finish login.",
    "session.auto": "Auto complete",
    "session.save": "Login complete — save cookies",
    "session.opened": "{site} login opened in the dedicated Chrome. Complete login, then click save.",
    "session.saved": "{site} cookies saved. Preflight has been refreshed.",
    "session.needsChrome": "Start the dedicated 9222 Chrome first, then retry.",
    "session.working": "Working…",
    "recent.avgScore": "avg score",
    "recent.manual": "manual",
    "recent.market": "market",
    "recent.mock": "mock",
    "recent.quality.blocked": "Blocked",
    "recent.quality.conflict_review": "Conflict review",
    "recent.quality.mock_review": "Mock review",
    "recent.quality.needs_review": "Needs review",
    "recent.quality.ready": "Ready",
    "recent.ready": "ready",
    "recent.rows": "rows",
    "recent.title": "Recent Runs",
    "results.searchPlaceholder": "Search ASIN, title, or supplier",
    "results.deleteConfirm": "Hide this result from the library? The source export and database history stay intact.",
    "results.subtitle": "Read previous crawl and sourcing outputs from local JSON and Excel exports.",
    "results.title": "Saved Product Selection Results",
    "contractReview.kicker": "PINNED HUMAN REVIEW QUEUE",
    "contractReview.title": "Target-contract evidence review",
    "contractReview.subtitle": "Review the three historical Amazon/1688 cases. Partial decisions are saved, but only completed cases enter evaluation.",
    "contractReview.complete": "cases reviewed",
    "results.reviewFilter.accepted": "Has accepted supplier",
    "results.reviewFilter.all": "All review states",
    "results.reviewFilter.pending": "Needs supplier review",
    "results.reviewFilter.rejected": "Has rejected supplier",
    "review.candidates": "Supplier candidates",
    "review.candidateScore": "Candidate",
    "review.confidence.high": "High confidence",
    "review.confidence.low": "Low confidence",
    "review.confidence.medium": "Medium confidence",
    "review.accept": "Accept",
    "review.accepted": "Accepted",
    "review.acceptedShort": "accepted",
    "review.conflict": "Conflict",
    "review.details": "Details",
    "review.decisionBrief": "Decision brief",
    "review.hide": "Hide",
    "review.issues": "Issues",
    "review.matchEvidence": "Match evidence",
    "review.marketEvidence": "Market evidence",
    "review.nextSteps": "Next steps",
    "review.noIssues": "No blocking issues",
    "review.noImage": "No image",
    "review.loadingImage": "Loading image",
    "review.noMarket": "No SellerSprite market data",
    "review.noSpec": "No structured spec extracted",
    "review.factory": "Factory",
    "review.field": "Field",
    "review.trader": "Trader",
    "review.monthlySales": "Sales",
    "review.repeatRate": "Repeat",
    "review.productSpec": "Product spec",
    "review.parameterComparison": "Parameter comparison",
    "review.status.matched": "Matched",
    "review.status.missing": "Missing",
    "review.status.unknown": "Check",
    "review.targetValue": "Target",
    "review.supplierValue": "Supplier",
    "review.profitEvidence": "Profit evidence",
    "review.pending": "Pending",
    "review.pendingShort": "pending",
    "review.reject": "Reject",
    "review.rejected": "Rejected",
    "review.rejectedShort": "rejected",
    "review.ready": "Ready",
    "review.rejectionReasons": "Rejection reasons",
    "review.scoreEvidence": "Score evidence",
    "review.action.blocked_no_supplier": "Blocked: no supplier",
    "review.action.manual_verify": "Manual verification",
    "review.action.ready_to_sample": "Ready to sample",
    "review.action.score_review": "Score review",
    "review.next.accept_or_reject_supplier": "Accept or reject supplier",
    "review.next.compare_more_suppliers": "Compare more suppliers",
    "review.next.find_supplier": "Find supplier",
    "review.next.inspect_score": "Inspect score",
    "review.next.open_supplier": "Open supplier",
    "review.next.renegotiate_cost": "Renegotiate cost",
    "review.next.request_quote": "Request quote",
    "review.next.retry_1688": "Retry 1688",
    "review.next.save_shortlist": "Save shortlist",
    "review.next.verify_specs": "Verify specs",
    "review.positiveSignals": "Positive evidence",
    "review.metric.bsr": "BSR",
    "review.metric.est_monthly_sales": "Monthly sales",
    "review.metric.monthly_purchases": "Monthly purchases",
    "review.metric.search_volume_monthly": "Search volume",
    "review.rejection.margin_too_low": "low margin",
    "review.rejection.monthly_sales_too_low": "low monthly sales",
    "review.rejection.price_too_low": "low selling price",
    "review.rejection.restricted_product": "restricted product",
    "review.rejection.score_too_low": "low total score",
    "review.rejection.supplier_match_too_low": "weak supplier match",
    "review.rejection.supplier_spec_conflict": "spec conflict",
    "review.rejection.supplier_spec_too_low": "weak spec match",
    "review.riskSignals": "Risks",
    "review.signal.candidate_score": "Candidate score",
    "review.signal.conflict": "Conflict",
    "review.signal.margin": "Margin",
    "review.signal.market_data_basic": "Market data",
    "review.signal.market_data_missing": "Market data missing",
    "review.signal.market_data_rich": "Market data",
    "review.signal.match_quality": "Match quality",
    "review.signal.missing": "Missing",
    "review.signal.rejection": "Rejected by rule",
    "review.signal.spec_match": "Spec match",
    "review.signal.supplier_evidence": "Supplier evidence",
    "review.signal.supplier_missing": "No supplier evidence",
    "review.source": "Source",
    "review.status.conflict": "Conflict",
    "review.status.needs_specs": "Needs specs",
    "review.status.no_supplier": "No supplier",
    "review.status.ready": "Ready",
    "review.status.review": "Review",
    "review.supplierSpec": "Top supplier spec",
    "review.supplierQuality": "Supplier",
    "review.targetImage": "Amazon image",
    "review.matchScore": "Match",
    "review.visualEvidence": "Visual evidence",
    "review.visualScore": "Visual",
    "review.verdict.reject": "Do not shortlist",
    "review.verdict.recommend": "Best to verify",
    "review.verdict.review": "Review manually",
    "review.verdict.verify": "Verify specs",
    "review.reason.candidate": "Rank score",
    "review.reason.highSales": "High sales",
    "review.reason.match": "Match",
    "review.reason.profit": "Profit",
    "review.reason.repeat": "Repeat",
    "review.reason.rank": "Sourcing rank",
    "review.reason.spec": "Spec",
    "review.reason.rejected": "Rejected match",
    "run.category": "Category",
    "run.hintDefault": "Estimated time depends on 1688 and LLM verification.",
    "run.hintQueued": "Agent job queued. Progress will appear in Recent Runs.",
    "run.keyword": "Keyword",
    "run.limit": "Limit",
    "run.llmVerify": "LLM Verify",
    "run.marketDataBlocked": "SellerSprite ASIN check must pass before requiring market data.",
    "run.marketplace": "Marketplace",
    "run.requireMarketData": "Require Market Data",
    "run.requireSupplierEvidence": "Require Supplier Evidence",
    "run.sourceAsin": "ASIN (later)",
    "run.sourceCategory": "By category",
    "run.sourceKeyword": "By product keyword",
    "run.sourceMode": "Search Mode",
    "run.subtitle": "Configure a sourcing run and review the generated analysis summary.",
    "run.title": "Run Agent",
    "settings.subtitle": "The local agent follows the repository system prompt and deterministic tools.",
    "settings.title": "Agent Policy",
    "settings.capability.alibaba": "1688 Open Platform",
    "settings.capability.cache": "API cache",
    "settings.capability.browserAgent": "Browser Assistant",
    "settings.capability.mock": "Mock suppliers",
    "settings.capability.scrapling": "Scrapling matcher",
    "settings.capability.sellerSprite": "SellerSprite API (optional)",
    "settings.capability.vision": "Vision model",
    "settings.configured": "Configured",
    "settings.disabled": "Disabled",
    "settings.enabled": "Enabled",
    "settings.missing": "Missing",
    "settings.promptTitle": "Runtime Prompt",
    "settings.saveSellerSprite": "Save SellerSprite",
    "settings.sellerSpriteBase": "API base",
    "settings.sellerSpriteOptional": "Optional; market analysis uses browser export, not MJJL_API_KEY",
    "settings.sellerSpriteAsin": "SellerSprite ASIN check",
    "settings.checkAsin": "Check ASIN",
    "settings.checkingAsin": "Checking ASIN",
    "settings.asinCheckOk": "ASIN check passed",
    "settings.asinCheckFailed": "ASIN check failed",
    "settings.alibabaNamespace": "1688 namespace",
    "settings.alibabaMethod": "1688 method",
    "settings.alibabaKeywordParam": "Keyword param",
    "settings.alibabaCandidates": "Fallback candidates",
    "settings.saveAlibabaSearch": "Save 1688 API",
    "settings.savingAlibabaSearch": "Saving 1688 API",
    "settings.alibabaSearchSaved": "1688 API saved",
    "settings.alibabaPifatuan": "1688 pifatuan check",
    "settings.checkLimit": "Limit",
    "settings.checkPifatuan": "Check 1688 API",
    "settings.checkingPifatuan": "Checking 1688 API",
    "settings.pifatuanCheckOk": "1688 API check passed",
    "settings.pifatuanCheckFailed": "1688 API check failed",
    "settings.importKeyword": "Import keyword",
    "settings.importNote": "Note",
    "settings.importPayload": "1688 API JSON payload",
    "settings.importAlibaba": "Import 1688 JSON",
    "settings.importingAlibaba": "Importing 1688 JSON",
    "settings.importAlibabaOk": "1688 JSON imported",
    "settings.importedTitle": "Imported 1688 candidates",
    "settings.importedEmpty": "No imported 1688 candidates",
    "settings.sellerSpriteKey": "SellerSprite key",
    "settings.sellerSpriteSaved": "SellerSprite saved",
    "settings.visionBase": "Vision API base",
    "settings.visionKey": "Vision API key",
    "settings.visionModel": "Vision model",
    "settings.visionSaved": "Vision model saved",
    "settings.saveVision": "Save vision model",
    "sidebar.agentDefinition": "Agent Definition",
    "sidebar.agentDefinitionText": "Environment, tools, and prompt policy are wired into a local execution loop.",
    "sidebar.footer": "v0.3 Agent Preview",
    "sidebar.systemStatus": "System Status",
    "status.failed": "failed",
    "status.human_required": "human action",
    "status.review_required": "review required",
    "status.retry_wait": "retry wait",
    "status.timed_out": "timed out",
    "status.skipped": "skipped",
    "status.cancel_requested": "cancelling",
    "status.cancelled": "cancelled",
    "status.mock": "Mock",
    "status.queued": "queued",
    "status.review": "Review",
    "status.running": "running",
    "status.selected": "Selected",
    "status.success": "success",
    "table.asin": "ASIN",
    "table.buyCost": "Buy Cost",
    "table.export": "Export",
    "table.actions": "Actions",
    "table.margin": "Margin",
    "table.match": "Match",
    "table.review": "Review",
    "table.saved": "Saved",
    "table.score": "Score",
    "table.status": "Status",
    "table.supplier": "Supplier",
    "table.title": "Title",
    "topMetrics.online": "Online",
    "runSelect.all": "All exports",
  },
  zh: {
    "actions.download": "下载",
    "actions.downloadAccepted": "下载已通过",
    "actions.export": "导出",
    "actions.refresh": "刷新",
    "actions.reloadResults": "重新加载",
    "actions.reset": "重置",
    "actions.cancel": "取消",
    "actions.delete": "删除",
    "actions.retry": "重试",
    "actions.resume": "继续",
    "actions.forceRerun": "强制重跑",
    "actions.runAgent": "运行 Agent",
    "actions.viewAll": "查看全部",
    "brand.subtitle": "Agent 控制台",
    "browser.cookieCheck": "1688 会话检查",
    "browser.offerUrl": "1688 货源链接",
    "browser.pageDiagnostic": "页面诊断",
    "browser.run": "运行浏览器助手",
    "browser.running": "浏览器助手运行中",
    "browser.supplierDetail": "1688 详情补采",
    "browser.taskType": "浏览器任务",
    "browser.url": "页面链接",
    "browserSetup.title": "9222 专用 Chrome",
    "browserSetup.check": "检测 9222",
    "browserSetup.guide": "启动指引",
    "browserSetup.profileNote": "Chrome 136+ 必须使用非默认用户目录。这个专用浏览器只用于 Amazon、1688 和卖家精灵自动化。",
    "browserSetup.copy": "复制命令",
    "browserSetup.copied": "命令已复制",
    "browserSetup.security": "不要把 9222 暴露到公网或局域网。Agent 可访问此专用浏览器中的页面和登录态。",
    "browserSetup.ready": "Chrome 9222 已就绪",
    "browserSetup.missing": "Chrome 9222 不可用",
    "sellersprite.reverseKeywords.title": "卖家精灵反查关键词导出",
    "sellersprite.reverseKeywords.subtitle": "为一个 Amazon US ASIN 导出并导入最多 20 条结构化反查关键词数据。",
    "sellersprite.reverseKeywords.asin": "Amazon US ASIN",
    "sellersprite.reverseKeywords.asinPlaceholder": "10 位 ASIN，例如 B00Q7OAN50",
    "sellersprite.reverseKeywords.export": "导出反查关键词",
    "sellersprite.reverseKeywords.running": "正在导出反查关键词，请保持 Chrome 打开。",
    "sellersprite.reverseKeywords.success": "导出已成功导入：可查看 {count} 条关键词数据。",
    "sellersprite.reverseKeywords.showing": "导出已成功导入：当前展示 {shown}/{total} 条关键词数据。",
    "sellersprite.reverseKeywords.noRows": "导出已完成，但没有可展示的关键词数据。",
    "sellersprite.reverseKeywords.needsHuman": "卖家精灵需要你先在 Chrome 中完成操作，才能继续导出。",
    "sellersprite.reverseKeywords.captcha": "卖家精灵显示了验证码或验证页面。请在 Chrome 中完成验证后重试。",
    "sellersprite.reverseKeywords.authentication": "请先在 Chrome 中登录卖家精灵，再重试导出。",
    "sellersprite.reverseKeywords.permission": "你的卖家精灵账号没有此导出功能的权限。",
    "sellersprite.reverseKeywords.disabled": "卖家精灵浏览器自动化已关闭或不可用。请启用后检查 Chrome 扩展。",
    "sellersprite.reverseKeywords.cancelled": "反查关键词导出已取消。",
    "sellersprite.reverseKeywords.failed": "反查关键词导出未能完成。请检查本地服务状态后重试。",
    "sellersprite.reverseKeywords.requestFailed": "本地服务无法开始反查关键词导出。请检查 ASIN 后重试。",
    "sellersprite.reverseKeywords.table.keyword": "关键词",
    "sellersprite.reverseKeywords.table.searchVolume": "搜索量",
    "sellersprite.reverseKeywords.table.purchaseRate": "购买率",
    "sellersprite.reverseKeywords.table.competingProducts": "竞品数",
    "sellersprite.reverseKeywords.table.trend": "趋势",
    "chat.placeholder": "询问当前任务或选中的 ASIN",
    "chat.send": "发送",
    "chat.title": "选品聊天助手",
    "hero.subtitle": "启动选品任务，检查运行前状态，并查看已保存的候选商品。",
    "hero.title": "Amazon 选品 Agent",
    "jobs.noActive": "暂无运行任务",
    "jobs.noActiveHint": "启动一次 Agent 任务后，可在这里查看进度。",
    "notifications.enable": "开启后台提醒",
    "notifications.enabled": "后台提醒已开启",
    "notifications.denied": "请在浏览器设置中允许通知",
    "notifications.unsupported": "当前浏览器不支持系统提醒",
    "notifications.title": "选品任务等待人工处理",
    "notifications.view": "查看",
    "manual.empty": "暂无阻塞货源任务",
    "manual.ignore": "忽略",
    "manual.keywords": "关键词",
    "manual.resolve": "已处理",
    "manual.title": "1688 人工队列",
    "match.conflict": "冲突",
    "match.missing": "缺失",
    "match.ok": "命中",
    "metrics.agent": "Agent",
    "metrics.cookieHealth": "Cookie 状态",
    "nav.results": "结果库",
    "nav.contractReview": "合同复核",
    "nav.run": "运行 Agent",
    "nav.trial": "一键研究",
    "nav.research": "市场研究",
    "nav.settings": "设置",
    "research.title": "市场研究 —— 卖家清单",
    "research.subtitle": "把卖家精灵「查竞品 / 选市场」导出，整理成更适合中小卖家研究的清单：卖家、代表产品、价格、评分、评论数、上架时间、月销量/月销售额，以及是否适合的理由。",
    "research.import.title": "分析竞品导出文件",
    "research.import.subtitle": "把卖家精灵竞品 CSV/XLSX 放到 data/imports 目录，然后填写文件名。",
    "research.browser.title": "或直接驱动浏览器导出",
    "research.browser.subtitle": "需已配置带 competitor_* 定位符的卖家精灵浏览器流程。",
    "research.niche": "细分类目标签",
    "research.keyword": "关键词",
    "research.category": "目标品类",
    "research.categoryAuto": "自动识别",
    "research.file": "导出文件名",
    "research.url": "卖家精灵页面 URL（可选）",
    "research.aiReasons": "生成 AI 适合理由（无 key 时回退规则理由）",
    "research.analyze": "生成清单",
    "research.runBrowser": "运行浏览器导出",
    "research.history": "最近的研究记录",
    "trial.kicker": "受控试用 · 真实数据",
    "trial.title": "一键完成市场研究与 1688 找货",
    "trial.subtitle": "先在 9222 专用 Chrome 打开目标 Amazon 类目或搜索列表。提交后系统会自动导出卖家精灵数据、汇总评分、筛选 ASIN、匹配 1688 货源并生成两份 Excel。",
    "trial.idle": "等待开始",
    "trial.sourceMode": "研究入口",
    "trial.categoryMode": "Amazon 类目列表",
    "trial.keywordMode": "Amazon 搜索列表",
    "trial.englishHint": "Amazon US 请填写英文检索词。",
    "trial.limit": "进入找货的高分候选数",
    "trial.aiReasons": "生成 AI 研究理由（可选）",
    "trial.contract": "正式试用只使用真实 Amazon、卖家精灵与 1688 数据；缺少登录、验证码或有效供应商证据时会暂停或明确失败，不会填充 Mock 结果。",
    "trial.start": "开始完整研究",
    "trial.openListHint": "请先确认 9222 Chrome 当前显示目标 Amazon 列表，且卖家精灵表格已加载。",
    "trial.progressTitle": "任务进度",
    "trial.noJob": "尚未创建试用任务",
    "trial.stagePreflight": "运行环境与登录检查",
    "trial.stagePreflightHint": "Chrome、Cookies、下载目录",
    "trial.stageResearch": "市场数据导出与汇总评分",
    "trial.stageResearchHint": "卖家精灵真实列表 → 研究 Excel",
    "trial.stageSourcing": "1688 找货与利润评分",
    "trial.stageSourcingHint": "高分 ASIN → 供应商证据",
    "trial.stageReport": "候选清单与报告交付",
    "trial.stageReportHint": "可下载 Excel / JSON",
    "trial.continue": "我已处理，继续任务",
    "trial.deliverables": "可交付文件",
    "trial.feedbackTitle": "本次试用体验",
    "trial.feedbackHint": "任务结束后用 20 秒告诉我们哪里顺畅、哪里需要改进。",
    "trial.feedbackEase": "操作顺畅度（1–5）",
    "trial.feedbackUsefulness": "报告帮助度（1–5）",
    "trial.feedbackAgain": "愿意继续使用",
    "trial.feedbackYes": "是",
    "trial.feedbackNo": "否",
    "trial.feedbackBlocked": "主要卡点",
    "trial.feedbackNone": "没有卡点",
    "trial.feedbackPreflight": "登录/环境检查",
    "trial.feedbackResearch": "市场研究",
    "trial.feedbackSourcing": "1688 找货",
    "trial.feedbackReport": "报告理解",
    "trial.feedbackComment": "补充意见（可选）",
    "trial.feedbackSubmit": "提交体验反馈",
    "trial.feedbackSaved": "反馈已保存，谢谢。",
    "trial.validationTitle": "试用验收",
    "trial.validationSubtitle": "用真实终态任务反馈判断是否进入本地安装包阶段。",
    "trial.validationNoData": "等待真实反馈",
    "trial.validationCollecting": "正在收集证据",
    "trial.validationReady": "可进入安装包",
    "trial.validationImprove": "先改进再打包",
    "trial.validationSamples": "有效反馈",
    "trial.validationCoverage": "入口覆盖",
    "trial.validationDelivery": "双报告交付率",
    "trial.validationEase": "平均顺畅度",
    "trial.validationUsefulness": "报告帮助度",
    "trial.validationAgain": "愿意继续使用",
    "trial.validationNoBlocker": "无主要卡点",
    "trial.validationGates": "进入安装包门槛",
    "trial.validationBlockers": "卡点分布",
    "trial.validationNoDataHint": "尚无甲方真实反馈，暂不进入安装包阶段。",
    "trial.validationCollectingHint": "还需 {count} 次终态试用反馈，才能做进入安装包判断。",
    "trial.validationReadyHint": "全部体验门槛已通过，可以进入本地安装包阶段。",
    "trial.validationImproveHint": "样本已足够，但仍有体验门槛未通过；请先改进流程并再次试用。",
    "trial.validationEmptyBlockers": "尚无卡点数据。",
    "trial.validationGate.sample_size": "至少 3 次终态试用反馈",
    "trial.validationGate.source_mode_count": "类目与关键词两种入口均已试用",
    "trial.validationGate.delivery_rate": "至少 2/3 完成两组报告交付",
    "trial.validationGate.average_ease": "平均顺畅度 ≥ 4.0 / 5",
    "trial.validationGate.average_usefulness": "报告帮助度 ≥ 4.0 / 5",
    "trial.validationGate.would_use_again_rate": "至少 2/3 愿意继续使用",
    "trial.validationGate.no_blocker_rate": "至少 2/3 没有主要卡点",
    "trial.queued": "完整研究任务已排队，可以保持此页面打开。",
    "trial.ready": "前置条件已检测通过。开始时请保持 Amazon 列表页打开。",
    "preflight.actionRequired": "需要处理",
    "preflight.allPassed": "所有阻塞项已通过。可以开始新的选品任务。",
    "preflight.checking": "检查中",
    "preflight.initialBody": "Agent 会先检查 cookies、数据库、导出目录和 1688 cooldown。",
    "preflight.needsReview": "需要检查",
    "preflight.ready": "就绪",
    "preflight.readyToRun": "可以运行",
    "preflight.resolveFailed": "请先处理失败的运行前检查项，再启动正式任务。",
    "preflight.review": "检查",
    "preflight.title": "运行前检查",
    "preflight.waiting": "等待检查结果",
    "session.title": "补充浏览器登录态",
    "session.subtitle": "Agent 可打开登录页，并在你完成登录后安全保存当前站点的 Cookies。",
    "session.auto": "一键补充",
    "session.save": "已登录，保存并检查",
    "session.opened": "已在专用 Chrome 中打开 {site} 登录页。完成登录后点击保存。",
    "session.saved": "{site} Cookies 已保存，运行前检查已刷新。",
    "session.needsChrome": "请先启动 9222 专用 Chrome，然后重试。",
    "session.working": "处理中…",
    "recent.avgScore": "平均分",
    "recent.manual": "需复核",
    "recent.market": "市场",
    "recent.mock": "Mock",
    "recent.quality.blocked": "阻塞",
    "recent.quality.conflict_review": "冲突复核",
    "recent.quality.mock_review": "Mock 复核",
    "recent.quality.needs_review": "需复核",
    "recent.quality.ready": "可验证",
    "recent.ready": "可验证",
    "recent.rows": "行",
    "recent.title": "最近任务",
    "results.searchPlaceholder": "搜索 ASIN、标题或供应商",
    "results.deleteConfirm": "从结果库隐藏这条记录？原始导出和数据库审计记录不会删除。",
    "results.subtitle": "读取本地 JSON 和 Excel 导出的历史爬取与选品结果。",
    "results.title": "已保存的选品结果",
    "contractReview.kicker": "固定证据人工复核队列",
    "contractReview.title": "目标合同证据复核",
    "contractReview.subtitle": "复核三组历史 Amazon / 1688 案例。部分操作会安全保存，但只有完成复核的案例才进入评估。",
    "contractReview.complete": "案例已复核",
    "results.reviewFilter.accepted": "有通过供应商",
    "results.reviewFilter.all": "全部审核状态",
    "results.reviewFilter.pending": "待审核供应商",
    "results.reviewFilter.rejected": "有拒绝供应商",
    "review.candidates": "供应商候选",
    "review.candidateScore": "候选",
    "review.confidence.high": "高信心",
    "review.confidence.low": "低信心",
    "review.confidence.medium": "中等信心",
    "review.accept": "通过",
    "review.accepted": "已通过",
    "review.acceptedShort": "通过",
    "review.conflict": "冲突",
    "review.details": "详情",
    "review.decisionBrief": "决策摘要",
    "review.hide": "收起",
    "review.issues": "问题",
    "review.matchEvidence": "匹配证据",
    "review.marketEvidence": "市场证据",
    "review.nextSteps": "下一步",
    "review.noIssues": "暂无阻塞问题",
    "review.noImage": "暂无图片",
    "review.loadingImage": "图片加载中",
    "review.noMarket": "暂无卖家精灵市场数据",
    "review.noSpec": "未提取到结构化参数",
    "review.factory": "工厂",
    "review.field": "字段",
    "review.trader": "贸易商",
    "review.monthlySales": "月销",
    "review.repeatRate": "复购",
    "review.productSpec": "目标产品参数",
    "review.parameterComparison": "参数对照",
    "review.status.matched": "匹配",
    "review.status.missing": "缺失",
    "review.status.unknown": "复核",
    "review.targetValue": "目标",
    "review.supplierValue": "供应商",
    "review.profitEvidence": "利润证据",
    "review.pending": "待定",
    "review.pendingShort": "待定",
    "review.reject": "拒绝",
    "review.rejected": "已拒绝",
    "review.rejectedShort": "拒绝",
    "review.ready": "可验证",
    "review.rejectionReasons": "拒绝原因",
    "review.scoreEvidence": "评分证据",
    "review.action.blocked_no_supplier": "阻塞：无供应商",
    "review.action.manual_verify": "人工复核",
    "review.action.ready_to_sample": "可打样",
    "review.action.score_review": "评分复核",
    "review.next.accept_or_reject_supplier": "通过或拒绝供应商",
    "review.next.compare_more_suppliers": "对比更多供应商",
    "review.next.find_supplier": "寻找供应商",
    "review.next.inspect_score": "检查评分",
    "review.next.open_supplier": "打开供应商",
    "review.next.renegotiate_cost": "压价或重算成本",
    "review.next.request_quote": "询价",
    "review.next.retry_1688": "重试 1688",
    "review.next.save_shortlist": "加入短名单",
    "review.next.verify_specs": "核对参数",
    "review.positiveSignals": "正向证据",
    "review.metric.bsr": "BSR",
    "review.metric.est_monthly_sales": "月销量",
    "review.metric.monthly_purchases": "月购买量",
    "review.metric.search_volume_monthly": "月搜索量",
    "review.rejection.margin_too_low": "毛利过低",
    "review.rejection.monthly_sales_too_low": "月销量过低",
    "review.rejection.price_too_low": "售价过低",
    "review.rejection.restricted_product": "受限/合规风险品",
    "review.rejection.score_too_low": "总分偏低",
    "review.rejection.supplier_match_too_low": "供应商匹配偏弱",
    "review.rejection.supplier_spec_conflict": "参数冲突",
    "review.rejection.supplier_spec_too_low": "参数匹配偏弱",
    "review.riskSignals": "风险",
    "review.signal.candidate_score": "候选分",
    "review.signal.conflict": "冲突",
    "review.signal.margin": "毛利率",
    "review.signal.market_data_basic": "市场数据",
    "review.signal.market_data_missing": "缺少市场数据",
    "review.signal.market_data_rich": "市场数据",
    "review.signal.match_quality": "匹配质量",
    "review.signal.missing": "缺失",
    "review.signal.rejection": "规则拒绝",
    "review.signal.spec_match": "参数匹配",
    "review.signal.supplier_evidence": "供应商证据",
    "review.signal.supplier_missing": "缺少供应商证据",
    "review.source": "来源",
    "review.status.conflict": "参数冲突",
    "review.status.needs_specs": "需补参数",
    "review.status.no_supplier": "无供应商",
    "review.status.ready": "可入选",
    "review.status.review": "待复核",
    "review.supplierSpec": "Top 供应商参数",
    "review.supplierQuality": "供应商",
    "review.targetImage": "Amazon 主图",
    "review.matchScore": "匹配",
    "review.visualEvidence": "视觉证据",
    "review.visualScore": "视觉",
    "review.verdict.reject": "不建议入选",
    "review.verdict.recommend": "优先核验",
    "review.verdict.review": "人工复核",
    "review.verdict.verify": "核对参数",
    "review.reason.candidate": "排序分",
    "review.reason.highSales": "高月销",
    "review.reason.match": "匹配",
    "review.reason.profit": "利润",
    "review.reason.repeat": "复购",
    "review.reason.rank": "货源排序",
    "review.reason.spec": "参数",
    "review.reason.rejected": "已判低匹配",
    "run.category": "类目",
    "run.hintDefault": "耗时取决于 1688 状态和 LLM 验证设置。",
    "run.hintQueued": "Agent 任务已排队。进度会显示在最近任务中。",
    "run.keyword": "关键词",
    "run.limit": "数量上限",
    "run.llmVerify": "LLM 验证",
    "run.marketDataBlocked": "要求市场数据前，需要先通过卖家精灵 ASIN 检查。",
    "run.marketplace": "站点",
    "run.requireMarketData": "要求市场数据",
    "run.requireSupplierEvidence": "要求供应商证据",
    "run.sourceAsin": "ASIN（暂未开放）",
    "run.sourceCategory": "按类目搜索",
    "run.sourceKeyword": "按产品关键词搜索",
    "run.sourceMode": "搜索模式",
    "run.subtitle": "配置一次选品任务，并查看任务完成后的分析总结。",
    "run.title": "运行 Agent",
    "settings.subtitle": "本地 Agent 遵循仓库系统提示词和确定性工具。",
    "settings.title": "Agent 策略",
    "settings.capability.alibaba": "1688 开放平台",
    "settings.capability.cache": "API 缓存",
    "settings.capability.browserAgent": "浏览器助手",
    "settings.capability.mock": "Mock 供应商",
    "settings.capability.scrapling": "Scrapling 匹配器",
    "settings.capability.sellerSprite": "卖家精灵 API（可选）",
    "settings.capability.vision": "视觉模型",
    "settings.configured": "已配置",
    "settings.disabled": "已关闭",
    "settings.enabled": "已启用",
    "settings.missing": "缺失",
    "settings.promptTitle": "运行提示词",
    "settings.saveSellerSprite": "保存卖家精灵",
    "settings.sellerSpriteBase": "API 地址",
    "settings.sellerSpriteOptional": "未启用 API；市场分析走浏览器导出，不需要 MJJL_API_KEY",
    "settings.sellerSpriteAsin": "卖家精灵 ASIN 检查",
    "settings.checkAsin": "检查 ASIN",
    "settings.checkingAsin": "正在检查 ASIN",
    "settings.asinCheckOk": "ASIN 检查通过",
    "settings.asinCheckFailed": "ASIN 检查失败",
    "settings.alibabaNamespace": "1688 命名空间",
    "settings.alibabaMethod": "1688 API 方法",
    "settings.alibabaKeywordParam": "关键词参数",
    "settings.alibabaCandidates": "候选 API 列表",
    "settings.saveAlibabaSearch": "保存 1688 API",
    "settings.savingAlibabaSearch": "正在保存 1688 API",
    "settings.alibabaSearchSaved": "1688 API 已保存",
    "settings.alibabaPifatuan": "1688 分销严选检查",
    "settings.checkLimit": "数量",
    "settings.checkPifatuan": "检查 1688 API",
    "settings.checkingPifatuan": "正在检查 1688 API",
    "settings.pifatuanCheckOk": "1688 API 检查通过",
    "settings.pifatuanCheckFailed": "1688 API 检查失败",
    "settings.importKeyword": "导入关键词",
    "settings.importNote": "备注",
    "settings.importPayload": "1688 API JSON 返回",
    "settings.importAlibaba": "导入 1688 JSON",
    "settings.importingAlibaba": "正在导入 1688 JSON",
    "settings.importAlibabaOk": "1688 JSON 已导入",
    "settings.importedTitle": "已导入 1688 候选",
    "settings.importedEmpty": "暂无已导入 1688 候选",
    "settings.sellerSpriteKey": "卖家精灵 Key",
    "settings.sellerSpriteSaved": "卖家精灵已保存",
    "settings.visionBase": "视觉 API 地址",
    "settings.visionKey": "视觉 API Key",
    "settings.visionModel": "视觉模型",
    "settings.visionSaved": "视觉模型已保存",
    "settings.saveVision": "保存视觉模型",
    "sidebar.agentDefinition": "Agent 定义",
    "sidebar.agentDefinitionText": "环境、工具和提示词策略已接入本地执行循环。",
    "sidebar.footer": "v0.3 Agent 预览版",
    "sidebar.systemStatus": "系统状态",
    "status.failed": "失败",
    "status.human_required": "等待人工处理",
    "status.review_required": "待复核",
    "status.retry_wait": "等待重试",
    "status.timed_out": "已超时",
    "status.skipped": "已跳过",
    "status.cancel_requested": "取消中",
    "status.cancelled": "已取消",
    "status.mock": "Mock",
    "status.queued": "排队中",
    "status.review": "待复核",
    "status.running": "运行中",
    "status.selected": "已入选",
    "status.success": "成功",
    "table.asin": "ASIN",
    "table.buyCost": "采购成本",
    "table.export": "导出",
    "table.actions": "操作",
    "table.margin": "利润率",
    "table.match": "匹配",
    "table.review": "审核",
    "table.saved": "保存",
    "table.score": "评分",
    "table.status": "状态",
    "table.supplier": "供应商",
    "table.title": "标题",
    "topMetrics.online": "在线",
    "runSelect.all": "全部导出",
  },
};

const PREFLIGHT_LABELS = {
  zh: {
    vision: "视觉模型 Key 已配置",
    amazon_cookies: "Amazon cookies 可用",
    "1688_cookies": "1688 登录 cookie 有效",
    alibaba_open: "1688 开放平台已验证",
    database: "SQLite 数据库已找到",
    exports: "导出目录可写",
    "1688_circuit": "1688 熔断已清除",
    disk: "存储空间可用",
    seller_sprite: "卖家精灵 API（可选，默认走浏览器导出）",
    seller_sprite_browser: "卖家精灵浏览器自动化",
  },
};

const JOB_MESSAGE_LABELS = {
  zh: {
    "No candidates passed filters": "无候选通过筛选",
    "Review report generated": "已生成复核报告",
    "No candidates passed hard filters; no export was generated": "无候选通过硬筛选，未生成正式候选导出",
    "No candidates passed hard filters; a review report was generated": "无候选通过硬筛选，已生成包含供应商证据与淘汰原因的复核报告",
    "Cancellation requested": "取消中",
    "Cancelled before start": "启动前已取消",
    "Cancelled before pipeline": "进入流水线前已取消",
    "Cancelled after pipeline": "流水线结束后已取消",
    "Run cancelled": "已取消",
    "Supplier evidence missing": "缺少真实货源证据",
    "Real supplier match evidence required but missing from export": "导出中缺少真实 1688 货源匹配证据",
    "Market data missing": "缺少市场数据",
    "SellerSprite rich market data required but missing from export": "导出中缺少卖家精灵富市场数据",
    "1688 supplier search is paused after a recent verification block": "上一次 1688 验证触发了安全冷却；当前页面可能没有验证码",
  },
  en: {},
};

document.addEventListener("DOMContentLoaded", () => {
  applyLanguage();
  bindNavigation();
  bindActions();
  bindBackgroundNotifications();
  updateSourceModeFields();
  refreshAll();
  setInterval(refreshJobs, 4000);
  setInterval(refreshManualQueue, 8000);
});

function bindNavigation() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".nav-item").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      state.activeSection = button.dataset.section;
      const section = state.activeSection;
      $("#trialSection").style.display = section === "trial" ? "grid" : "none";
      $("#runSection").style.display = section === "run" ? "grid" : "none";
      $("#resultsSection").style.display = section === "run" || section === "results" ? "grid" : "none";
      $("#contractReviewSection").style.display = section === "contract-review" ? "block" : "none";
      $("#settingsSection").style.display = section === "settings" ? "block" : "none";
      const researchSection = $("#researchSection");
      if (researchSection) {
        researchSection.style.display = section === "research" ? "block" : "none";
        if (section === "research") refreshResearchHistory();
      }
      if (section === "contract-review") refreshTargetContractReviews();
      window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    });
  });
}

function bindActions() {
  $("#languageButton").addEventListener("click", toggleLanguage);
  $("#refreshButton").addEventListener("click", refreshAll);
  $("#loadRunsButton").addEventListener("click", refreshRuns);
  $("#reloadResultsButton").addEventListener("click", refreshResults);
  $("#runButton").addEventListener("click", startRun);
  $("#trialForm").addEventListener("submit", startFullResearch);
  $("#trialContinueButton").addEventListener("click", continueTrialJob);
  $("#trialFeedbackForm").addEventListener("submit", submitTrialFeedback);
  $$("input[name='trial_source_mode']").forEach((input) => {
    input.addEventListener("change", updateTrialSourceModeFields);
  });
  $("#resetButton").addEventListener("click", () => {
    $("#runForm").reset();
    updateSourceModeFields();
    refreshKeywordPreview();
    updateRunAvailability();
  });
  $$("input[name='source_mode']").forEach((input) => {
    input.addEventListener("change", () => {
      updateSourceModeFields();
      refreshKeywordPreview();
    });
  });
  $("#runForm input[name='keyword']").addEventListener("input", refreshKeywordPreview);
  $("#runForm input[name='require_market_data']").addEventListener("change", updateRunAvailability);
  $("#searchInput").addEventListener("input", renderResults);
  $("#runSelect").addEventListener("change", () => {
    state.selectedAsin = "";
    updateReviewedDownloadLink();
    renderChatContext();
    refreshResults();
  });
  $("#reviewFilter").addEventListener("change", () => {
    state.reviewFilter = $("#reviewFilter").value;
    renderResults();
  });
  $("#sellerSpriteForm").addEventListener("submit", configureSellerSprite);
  $("#visionModelForm").addEventListener("submit", configureVisionModel);
  $("#sellerSpriteAsinForm").addEventListener("submit", checkSellerSpriteAsin);
  $("#alibabaSearchApiForm").addEventListener("submit", configureAlibabaSearchApi);
  $("#alibabaPifatuanForm").addEventListener("submit", checkAlibabaPifatuan);
  $("#alibabaImportForm").addEventListener("submit", importAlibabaPayload);
  $("#browserAgentForm").addEventListener("submit", sendBrowserAgentTask);
  $("#sellerSpriteReverseKeywordForm").addEventListener("submit", runSellerSpriteReverseKeywords);
  $("#sellerSpriteBrowserConfigForm").addEventListener("submit", configureSellerSpriteBrowser);
  $("#checkBrowserSetupButton").addEventListener("click", refreshBrowserSetup);
  $("#toggleBrowserGuideButton").addEventListener("click", toggleBrowserSetupGuide);
  $("#copyBrowserCommandButton").addEventListener("click", copyBrowserLaunchCommand);
  $$("[data-browser-os]").forEach((button) => {
    button.addEventListener("click", () => selectBrowserOs(button.dataset.browserOs));
  });
  $("#researchImportForm").addEventListener("submit", runResearchImport);
  $("#researchBrowserForm").addEventListener("submit", runResearchBrowserExport);
  $("#chatForm").addEventListener("submit", sendChatMessage);
}

async function refreshAll() {
  await Promise.all([
    refreshCategories(),
    refreshPreflight(),
    refreshConfigStatus(),
    refreshBrowserSetup(),
    refreshJobs(),
    refreshRuns(),
    refreshPrompt(),
    refreshManualQueue(),
    refreshImportedSuppliers(),
    refreshSellerSpriteImportHistory(),
    refreshTrialFeedbackSummary(),
    refreshTargetContractReviews(),
  ]);
  await refreshResults();
}

async function refreshCategories() {
  const data = await getJson("/api/categories");
  state.categories = data.categories || [];
  renderCategorySelect();
}

async function refreshPreflight() {
  const data = await getJson("/api/preflight");
  state.preflight = data;
  renderPreflight();
}

async function refreshTrialFeedbackSummary() {
  try {
    state.trialFeedbackSummary = await getJson("/api/trial/feedback/summary");
  } catch (_error) {
    state.trialFeedbackSummary = null;
  }
  renderTrialFeedbackSummary();
}

async function refreshJobs() {
  const data = await getJson("/api/jobs");
  state.jobs = data.jobs || [];
  const runIds = [...new Set(state.jobs.map((job) => job.run_log_id).filter(Boolean))];
  const nodeResults = await Promise.all(runIds.map(async (runId) => {
    try {
      const payload = await getJson(`/api/runs/${encodeURIComponent(runId)}/nodes`);
      return [String(runId), payload.nodes || []];
    } catch (_error) {
      return [String(runId), []];
    }
  }));
  state.executionNodes = Object.fromEntries(nodeResults);
  syncHumanActionAlerts();
  renderJobs();
  renderTrialWorkflow();
}

function bindBackgroundNotifications() {
  const button = $("#notificationButton");
  const dismiss = $("#backgroundAlertDismiss");
  const view = $("#backgroundAlertView");
  button?.addEventListener("click", enableBackgroundNotifications);
  dismiss?.addEventListener("click", () => $("#backgroundAlert")?.classList.add("hidden"));
  view?.addEventListener("click", focusHumanAction);
  renderNotificationButton();
}

function renderNotificationButton() {
  const button = $("#notificationButton");
  if (!button) return;
  if (!("Notification" in window)) {
    button.textContent = t("notifications.unsupported");
    button.disabled = true;
    return;
  }
  const enabled = state.notificationEnabled && Notification.permission === "granted";
  button.classList.toggle("enabled", enabled);
  button.textContent = Notification.permission === "denied"
    ? t("notifications.denied")
    : enabled ? t("notifications.enabled") : t("notifications.enable");
}

async function enableBackgroundNotifications() {
  if (!("Notification" in window)) return;
  const permission = Notification.permission === "default"
    ? await Notification.requestPermission()
    : Notification.permission;
  state.notificationEnabled = permission === "granted";
  if (state.notificationEnabled) {
    localStorage.setItem("backgroundNotifications", "enabled");
    const pending = currentHumanAction();
    if (pending) showHumanActionAlert(pending.job, pending.node, { forceSystem: true });
  } else {
    localStorage.removeItem("backgroundNotifications");
  }
  renderNotificationButton();
}

function currentHumanAction() {
  for (const job of state.jobs) {
    if (job.status !== "human_required") continue;
    const nodes = state.executionNodes[String(job.run_log_id)] || [];
    return { job, node: nodes.find((item) => item.status === "human_required") || null };
  }
  return null;
}

function syncHumanActionAlerts() {
  const pending = currentHumanAction();
  document.title = pending ? `⚠ ${DEFAULT_DOCUMENT_TITLE}` : DEFAULT_DOCUMENT_TITLE;
  if (!pending) {
    state.activeHumanAlert = null;
    return;
  }
  const node = pending.node;
  const key = `${pending.job.id}:${node?.id || "job"}:${node?.updated_at || pending.job.finished_at || ""}`;
  if (state.activeHumanAlert === key) return;
  state.activeHumanAlert = key;
  showHumanActionAlert(pending.job, node);
}

function humanActionDescription(job, node) {
  const scope = node?.scope_key || job.config?.keyword || job.config?.category || job.id;
  const stage = node?.stage || "browser";
  const code = node?.error_code || "";
  const detail = node?.human_action_required?.instructions
    || node?.error_detail
    || jobMessageLabel(job.error)
    || jobMessageLabel(job.message);
  return `${scope} · ${stage}${code ? ` · ${code}` : ""} — ${detail}`;
}

function showHumanActionAlert(job, node, { forceSystem = false } = {}) {
  const alert = $("#backgroundAlert");
  const title = $("#backgroundAlertTitle");
  const body = $("#backgroundAlertBody");
  const view = $("#backgroundAlertView");
  if (alert && title && body) {
    title.textContent = t("notifications.title");
    body.textContent = humanActionDescription(job, node);
    if (view) view.textContent = t("notifications.view");
    alert.classList.remove("hidden");
  }
  if (
    state.notificationEnabled
    && "Notification" in window
    && Notification.permission === "granted"
    && (document.hidden || forceSystem)
  ) {
    const notification = new Notification(t("notifications.title"), {
      body: humanActionDescription(job, node),
      tag: `human-required-${job.id}-${node?.id || "job"}`,
      requireInteraction: true,
    });
    notification.onclick = () => {
      window.focus();
      focusHumanAction();
      notification.close();
    };
  }
}

function focusHumanAction() {
  window.focus();
  $(".nav-item[data-section='trial']")?.click();
  $(".trial-progress-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function refresh1688SessionBeforeResume(node) {
  const errorCode = node?.error_code || node?.human_action_required?.error_code || "";
  if (!["CAPTCHA", "CAPTCHA_COOLDOWN", "AUTH_REQUIRED"].includes(errorCode)) return;
  const captured = await postJson("/api/browser-setup", {
    action: "save_cookies",
    site: "1688",
  });
  if (!captured.ok) {
    throw new Error(captured.message || "1688 session could not be saved.");
  }
  await Promise.all([refreshPreflight(), refreshBrowserSetup()]);
}

async function refreshRuns() {
  const data = await getJson("/api/runs");
  state.runs = data.runs || [];
  renderRuns();
  renderRunSelect();
}

async function refreshResults() {
  const runId = $("#runSelect").value;
  const data = await getJson(`/api/results${runId ? `?run=${encodeURIComponent(runId)}` : ""}`);
  state.results = data.items || [];
  renderResults();
}

async function refreshManualQueue() {
  const data = await getJson("/api/manual-queue?status=open");
  state.manualQueue = data.items || [];
  renderManualQueue();
}

async function refreshTargetContractReviews() {
  const list = $("#contractReviewList");
  if (!list) return;
  try {
    const data = await getJson("/api/target-contract/reviews");
    state.targetContractReviews = data.cases || [];
    renderTargetContractReviews(data);
  } catch (error) {
    list.innerHTML = `<p class="muted-text">${escapeHtml(error.message)}</p>`;
  }
}

async function refreshImportedSuppliers() {
  const data = await getJson("/api/imported-suppliers?limit=10");
  state.importedSuppliers = data.items || [];
  renderImportedSuppliers();
}

async function refreshConfigStatus() {
  const data = await getJson("/api/config/status");
  state.configStatus = data;
  fillAlibabaSearchApiForm(data.alibaba_open || {});
  renderConfigStatus();
  renderSellerSpriteBrowserCapability(data.seller_sprite_browser || {});
}

async function refreshBrowserSetup() {
  try {
    state.browserSetup = await getJson("/api/browser-setup/status");
  } catch (error) {
    state.browserSetup = {
      configured: false,
      reachable: false,
      detail: error.message,
      launch_commands: {},
    };
  }
  renderBrowserSetup();
  renderPreflight();
}

function renderBrowserSetup() {
  const setup = state.browserSetup || {};
  const reachable = Boolean(setup.reachable);
  const badge = $("#browserSetupBadge");
  const detail = $("#browserSetupDetail");
  if (badge) {
    badge.className = `badge ${reachable ? "ok" : "err"}`;
    badge.textContent = reachable ? t("browserSetup.ready") : t("browserSetup.missing");
  }
  if (detail) {
    detail.textContent = reachable
      ? (state.lang === "zh" ? "Chrome 远程调试连接正常" : "Chrome remote debugging is reachable")
      : (state.lang === "zh" ? "请使用下方命令启动 9222 专用 Chrome" : (setup.detail || t("browserSetup.missing")));
  }
  renderBrowserLaunchCommand();
  renderSellerSpriteResearchPrerequisite();
  renderTrialReadiness();
}

function toggleBrowserSetupGuide() {
  const guide = $("#browserSetupGuide");
  const button = $("#toggleBrowserGuideButton");
  if (!guide || !button) return;
  const willOpen = guide.classList.contains("hidden");
  guide.classList.toggle("hidden", !willOpen);
  button.setAttribute("aria-expanded", String(willOpen));
}

function selectBrowserOs(osName) {
  state.selectedBrowserOs = ["windows", "macos", "linux"].includes(osName) ? osName : "windows";
  $$("[data-browser-os]").forEach((button) => {
    button.classList.toggle("active", button.dataset.browserOs === state.selectedBrowserOs);
  });
  renderBrowserLaunchCommand();
}

function renderBrowserLaunchCommand() {
  const target = $("#browserLaunchCommand");
  if (!target) return;
  target.textContent = state.browserSetup?.launch_commands?.[state.selectedBrowserOs] || "";
}

async function copyBrowserLaunchCommand() {
  const command = $("#browserLaunchCommand")?.textContent || "";
  if (!command) return;
  try {
    await navigator.clipboard.writeText(command);
    $("#copyBrowserCommandButton").textContent = t("browserSetup.copied");
  } catch (_error) {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents($("#browserLaunchCommand"));
    selection.removeAllRanges();
    selection.addRange(range);
  }
  setTimeout(() => {
    $("#copyBrowserCommandButton").textContent = t("browserSetup.copy");
  }, 1400);
}

async function refreshSellerSpriteImportHistory() {
  const data = await getJson("/api/sellersprite/imports?limit=20");
  state.sellerSpriteImportHistory = Array.isArray(data.items) ? data.items : [];
  renderSellerSpriteImportHistory(state.sellerSpriteImportHistory);
}

async function configureSellerSpriteBrowser(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = new FormData(form);
  const status = $("#sellerSpriteBrowserConfigStatus");
  try {
    const result = await postJson("/api/sellersprite/browser-config", {
      locator_profile_path: String(values.get("locator_profile_path") || ""),
      download_dir: String(values.get("download_dir") || ""),
      host_download_dir: String(values.get("host_download_dir") || ""),
      enabled: Boolean(form.elements.enabled.checked),
    });
    status.className = result.status === "ready" ? "status-ok" : "status-error";
    status.textContent = result.status === "ready"
      ? "Browser configuration saved."
      : result.enabled
        ? "Browser export is enabled. Add a reviewed locator profile before exporting."
        : "Browser export is disabled.";
    await Promise.all([refreshConfigStatus(), refreshPreflight()]);
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function refreshPrompt() {
  const data = await getJson("/api/prompt");
  $("#promptBox").textContent = data.system_prompt || "";
}

async function configureSellerSprite(event) {
  event.preventDefault();
  const form = new FormData($("#sellerSpriteForm"));
  const status = $("#sellerSpriteConfigStatus");
  try {
    const result = await postJson("/api/config/seller-sprite", {
      key: String(form.get("key") || ""),
      base_url: String(form.get("base_url") || ""),
    });
    $("#sellerSpriteKeyInput").value = "";
    status.className = "status-ok";
    status.textContent = `${t("settings.sellerSpriteSaved")} (${result.key_length})`;
    await Promise.all([refreshConfigStatus(), refreshPreflight()]);
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function configureVisionModel(event) {
  event.preventDefault();
  const form = new FormData($("#visionModelForm"));
  const status = $("#visionModelConfigStatus");
  try {
    const result = await postJson("/api/config/vision-model", {
      key: String(form.get("key") || ""),
      model: String(form.get("model") || ""),
      base_url: String(form.get("base_url") || ""),
    });
    $("#visionApiKeyInput").value = "";
    status.className = "status-ok";
    status.textContent = `${t("settings.visionSaved")} (${result.model})`;
    await Promise.all([refreshConfigStatus(), refreshPreflight()]);
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function checkSellerSpriteAsin(event) {
  event.preventDefault();
  const form = new FormData($("#sellerSpriteAsinForm"));
  const status = $("#sellerSpriteAsinStatus");
  status.className = "";
  status.textContent = t("settings.checkingAsin");
  try {
    const result = await postJson("/api/config/seller-sprite/asin-check", {
      asin: String(form.get("asin") || ""),
      marketplace: String(form.get("marketplace") || "US"),
    });
    status.className = result.error || !result.has_market_evidence ? "status-error" : "status-ok";
    status.textContent = sellerSpriteAsinSummary(result);
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function configureAlibabaSearchApi(event) {
  event.preventDefault();
  const form = new FormData($("#alibabaSearchApiForm"));
  const status = $("#alibabaSearchApiStatus");
  status.className = "";
  status.textContent = t("settings.savingAlibabaSearch");
  try {
    const result = await postJson("/api/config/alibaba/search-api", {
      namespace: String(form.get("namespace") || ""),
      method: String(form.get("method") || ""),
      keyword_param: String(form.get("keyword_param") || ""),
      candidates: String(form.get("candidates") || ""),
    });
    status.className = "status-ok";
    status.textContent = `${t("settings.alibabaSearchSaved")}: ${result.namespace}/${result.method}`;
    await Promise.all([refreshConfigStatus(), refreshPreflight()]);
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function checkAlibabaPifatuan(event) {
  event.preventDefault();
  const form = new FormData($("#alibabaPifatuanForm"));
  const status = $("#alibabaPifatuanStatus");
  status.className = "";
  status.textContent = t("settings.checkingPifatuan");
  try {
    const result = await postJson("/api/config/alibaba/pifatuan-check", {
      keyword: String(form.get("keyword") || ""),
      limit: Number(form.get("limit") || 3),
    });
    status.className = result.error || !result.count ? "status-error" : "status-ok";
    status.textContent = alibabaPifatuanSummary(result);
    await refreshConfigStatus();
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function importAlibabaPayload(event) {
  event.preventDefault();
  const form = new FormData($("#alibabaImportForm"));
  const status = $("#alibabaImportStatus");
  status.className = "";
  status.textContent = t("settings.importingAlibaba");
  try {
    const result = await postJson("/api/imported-suppliers", {
      keyword: String(form.get("keyword") || ""),
      note: String(form.get("note") || ""),
      payload: String(form.get("payload") || ""),
    });
    status.className = "status-ok";
    status.textContent = `${t("settings.importAlibabaOk")}: ${result.imported || 0}/${result.total || 0}`;
    $("#alibabaImportPayloadInput").value = "";
    await refreshImportedSuppliers();
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

async function runSellerSpriteReverseKeywords(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const status = $("#sellerSpriteReverseKeywordStatus");
  const submitButton = form.querySelector("button[type='submit']");
  const asin = String(new FormData(form).get("asin") || "").trim();

  status.className = "";
  status.textContent = t("sellersprite.reverseKeywords.running");
  state.sellerSpriteKeywordRows = [];
  renderSellerSpriteKeywordRows(state.sellerSpriteKeywordRows);
  submitButton.disabled = true;
  try {
    const result = await postJson("/api/sellersprite/reverse-keywords", { asin });
    status.className = sellerSpriteStatusClass(result);
    status.textContent = sellerSpriteStatusText(result);
    state.sellerSpriteKeywordRows = sellerSpriteKeywordRows(result);
    renderSellerSpriteKeywordRows(state.sellerSpriteKeywordRows);
  } catch (_error) {
    status.className = "status-error";
    status.textContent = t("sellersprite.reverseKeywords.requestFailed");
    state.sellerSpriteKeywordRows = [];
    renderSellerSpriteKeywordRows(state.sellerSpriteKeywordRows);
  } finally {
    updateSellerSpriteExportAvailability();
    await refreshSellerSpriteImportHistory();
  }
}

function sellerSpriteStatusClass(result) {
  return result?.status === "SUCCESS" ? "status-ok" : "status-error";
}

function sellerSpriteStatusText(result) {
  if (result?.status === "SUCCESS") {
    const shown = sellerSpriteKeywordRows(result).length;
    const total = sellerSpritePublicNumber(result?.data?.row_count);
    if (!shown) return t("sellersprite.reverseKeywords.noRows");
    if (total !== null && total > shown) {
      return t("sellersprite.reverseKeywords.showing")
        .replace("{shown}", sellerSpriteNumberText(shown))
        .replace("{total}", sellerSpriteNumberText(total));
    }
    return t("sellersprite.reverseKeywords.success").replace("{count}", sellerSpriteNumberText(shown));
  }

  const errorCode = result?.error_code || result?.status;
  if (errorCode === "CAPTCHA") return t("sellersprite.reverseKeywords.captcha");
  if (errorCode === "SELLERSPRITE_LOGIN_REQUIRED") return t("sellersprite.reverseKeywords.authentication");
  if (errorCode === "SELLERSPRITE_PERMISSION_REQUIRED") return t("sellersprite.reverseKeywords.permission");
  if (errorCode === "SELLERSPRITE_QUOTA_EXCEEDED") return "SellerSprite quota is exhausted. Review your SellerSprite plan in Chrome, then retry.";
  if (errorCode === "EXTENSION_UNAVAILABLE") return t("sellersprite.reverseKeywords.disabled");
  if (errorCode === "CANCELLED") return t("sellersprite.reverseKeywords.cancelled");
  if (result?.status === "NEEDS_HUMAN") return t("sellersprite.reverseKeywords.needsHuman");
  return t("sellersprite.reverseKeywords.failed");
}

function renderSellerSpriteBrowserCapability(browser) {
  const target = $("#sellerSpriteBrowserCapability");
  if (!target) return;
  const status = browser?.status || "disabled";
  target.className = status === "ready" ? "status-ok sellersprite-browser-capability" : "status-error sellersprite-browser-capability";
  target.textContent = status === "ready"
    ? (state.lang === "zh"
      ? "浏览器导出已就绪：Chrome CDP、定位符配置和下载目录均已验证。"
      : "Browser export is ready: Chrome CDP, locator profile, and download directory are verified.")
    : status === "disabled"
      ? (state.lang === "zh"
        ? "浏览器导出已关闭。准备好 9222 Chrome 和定位符后再启用。"
        : "Browser export is disabled. Prepare Chrome 9222 and the locator profile before enabling it.")
      : (browser?.readiness_detail || (state.lang === "zh"
        ? "浏览器导出尚未就绪，请检查 9222 Chrome、定位符和下载目录。"
        : "Browser export is not ready. Check Chrome 9222, the locator profile, and download directory."));
  const form = $("#sellerSpriteBrowserConfigForm");
  if (form) form.elements.enabled.checked = Boolean(browser?.enabled);
  updateSellerSpriteExportAvailability();
  renderSellerSpriteResearchPrerequisite();
  renderTrialReadiness();
}

function updateSellerSpriteExportAvailability() {
  const button = $("#sellerSpriteReverseKeywordForm button[type='submit']");
  if (button) button.disabled = state.configStatus?.seller_sprite_browser?.status !== "ready";
}

function renderSellerSpriteResearchPrerequisite() {
  const target = $("#researchBrowserPrerequisite");
  const button = $("#researchBrowserForm button[type='submit']");
  if (!target || !button) return;
  const browser = state.configStatus?.seller_sprite_browser || {};
  const chromeReady = Boolean(state.browserSetup?.reachable);
  const ready = browser.status === "ready" && chromeReady;
  target.className = `browser-prerequisite ${ready ? "status-ok" : "status-error"}`;
  target.textContent = ready
    ? (state.lang === "zh"
      ? "卖家精灵自动化已就绪：9222 Chrome、扩展配置和下载目录均可用。"
      : "SellerSprite automation is ready: Chrome 9222, extension configuration, and downloads are available.")
    : (state.lang === "zh"
      ? "自动导出需要：9222 专用 Chrome、已登录的卖家精灵、已安装扩展、已审核定位符和可写下载目录。"
      : "Browser export requires dedicated Chrome 9222, a signed-in SellerSprite session, the extension, a reviewed locator profile, and a writable download directory.");
  button.disabled = !ready;
}

function renderSellerSpriteImportHistory(items) {
  const target = $("#sellerSpriteImportHistory");
  if (!target) return;
  target.replaceChildren();
  const rows = Array.isArray(items) ? items.slice(0, 20) : [];
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No imported SellerSprite downloads yet.";
    target.appendChild(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "sellersprite-import-history-list";
  rows.forEach((item) => {
    const entry = document.createElement("li");
    const sha = typeof item.file_sha256 === "string" ? item.file_sha256.slice(0, 12) : "-";
    entry.textContent = `${item.observed_at || "-"} · ${item.asin || "-"} · ${item.row_count ?? "-"} rows · ${item.artifact_type || "-"} · ${sha} · ${item.status || "-"}`;
    list.appendChild(entry);
  });
  target.appendChild(list);
}

function sellerSpriteKeywordRows(result) {
  return result?.status === "SUCCESS" && Array.isArray(result.data?.keyword_rows)
    ? result.data.keyword_rows.slice(0, 20)
    : [];
}

function renderSellerSpriteKeywordRows(rows) {
  const results = $("#sellerSpriteReverseKeywordResults");
  const safeRows = Array.isArray(rows) ? rows.slice(0, 20) : [];
  if (!safeRows.length) {
    results.replaceChildren();
    return;
  }

  results.innerHTML = `
    <div class="sellersprite-keyword-table-wrap">
      <table class="sellersprite-keyword-table">
        <thead>
          <tr>
            <th>${escapeHtml(t("sellersprite.reverseKeywords.table.keyword"))}</th>
            <th>${escapeHtml(t("sellersprite.reverseKeywords.table.searchVolume"))}</th>
            <th>${escapeHtml(t("sellersprite.reverseKeywords.table.purchaseRate"))}</th>
            <th>${escapeHtml(t("sellersprite.reverseKeywords.table.competingProducts"))}</th>
            <th>${escapeHtml(t("sellersprite.reverseKeywords.table.trend"))}</th>
          </tr>
        </thead>
        <tbody>
          ${safeRows.map((row) => sellerSpriteKeywordRow(row)).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sellerSpriteKeywordRow(row) {
  const safeRow = row && typeof row === "object" ? row : {};
  return `
    <tr>
      <td>${escapeHtml(typeof safeRow.keyword === "string" ? safeRow.keyword : "-")}</td>
      <td>${escapeHtml(sellerSpriteMetricValue(safeRow, "search_volume", "search_volume_lower_bound"))}</td>
      <td>${escapeHtml(sellerSpriteRateValue(safeRow))}</td>
      <td>${escapeHtml(sellerSpriteMetricValue(safeRow, "competing_products", "competing_products_lower_bound"))}</td>
      <td>${escapeHtml(typeof safeRow.trend === "string" && safeRow.trend.trim() ? safeRow.trend : "-")}</td>
    </tr>
  `;
}

function sellerSpriteMetricValue(row, exactField, lowerBoundField) {
  const exact = sellerSpritePublicNumber(row?.[exactField]);
  if (exact !== null) return sellerSpriteNumberText(exact);
  const lowerBound = sellerSpritePublicNumber(row?.[lowerBoundField]);
  return lowerBound === null ? "-" : `≥${sellerSpriteNumberText(lowerBound)}`;
}

function sellerSpriteRateValue(row) {
  const exact = sellerSpritePublicNumber(row?.purchase_rate);
  if (exact !== null) return `${sellerSpriteNumberText(exact)}%`;
  const lowerBound = sellerSpritePublicNumber(row?.purchase_rate_lower_bound);
  return lowerBound === null ? "-" : `≥${sellerSpriteNumberText(lowerBound)}%`;
}

function sellerSpritePublicNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function sellerSpriteNumberText(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

async function sendBrowserAgentTask(event) {
  event.preventDefault();
  const form = new FormData($("#browserAgentForm"));
  const status = $("#browserAgentStatus");
  const resultBox = $("#browserAgentResult");
  status.className = "";
  status.textContent = t("browser.running");
  resultBox.textContent = "";
  try {
    const result = await postJson("/api/browser-agent", {
      task_type: String(form.get("task_type") || ""),
      url: String(form.get("url") || ""),
      offer_url: String(form.get("offer_url") || ""),
      asin: String(form.get("asin") || ""),
      keyword: String(form.get("keyword") || ""),
    });
    status.className = result.ok ? "status-ok" : "status-error";
    status.textContent = result.status || "";
    resultBox.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    status.className = "status-error";
    status.textContent = error.message;
  }
}

function renderImportedSuppliers() {
  const list = $("#importedSupplierList");
  if (!list) return;
  const items = state.importedSuppliers || [];
  if (!items.length) {
    list.innerHTML = `<p class="muted-text">${escapeHtml(t("settings.importedEmpty"))}</p>`;
    return;
  }
  list.innerHTML = items.map((item) => `
    <div class="imported-supplier-item">
      <div>
        <strong>${escapeHtml(item.supplier || item.title || item.offer_id || "-")}</strong>
        <span>${escapeHtml(item.title || item.offer_id || "-")}</span>
      </div>
      <small>${escapeHtml([
        item.keyword || "",
        money(item.price_cny, "¥"),
        item.moq === null || item.moq === undefined ? "" : `MOQ ${item.moq}`,
        item.monthly_sales === null || item.monthly_sales === undefined ? "" : `${formatInteger(item.monthly_sales)} sales`,
      ].filter(Boolean).join(" · "))}</small>
    </div>
  `).join("");
}

function renderTargetContractReviews(payload = {}) {
  const list = $("#contractReviewList");
  if (!list) return;
  const cases = state.targetContractReviews || [];
  const reviewedCount = cases.filter((item) => item.reviewed).length;
  $("#contractReviewCount").textContent = `${reviewedCount} / ${payload.case_count ?? cases.length}`;
  if (!cases.length) {
    list.innerHTML = `<p class="muted-text">No pinned review cases are available.</p>`;
    return;
  }
  list.innerHTML = cases.map((item, index) => targetContractCase(item, index)).join("");
  list.querySelectorAll("[data-contract-action]").forEach((button) => {
    button.addEventListener("click", () => submitTargetContractReview(button));
  });
}

function targetContractCase(item, index) {
  const amazon = item.amazon_evidence || {};
  const artifact = item.artifact || {};
  const noteId = `contract-note-${index}`;
  const artifactClass = artifact.sha256_verified ? "verified" : "unavailable";
  const artifactLabel = artifact.sha256_verified
    ? "SHA-256 verified"
    : (artifact.error || "Evidence unavailable");
  return `
    <article class="contract-review-case ${item.reviewed ? "reviewed" : ""}" data-case-id="${escapeAttr(item.case_id)}">
      <header class="contract-case-header">
        <div>
          <span class="contract-case-number">Case ${index + 1}</span>
          <strong>${escapeHtml(item.asin || "-")}</strong>
          <small>${escapeHtml(item.category_id || "")}</small>
        </div>
        <span class="contract-case-status ${item.reviewed ? "reviewed" : "pending"}">
          ${item.reviewed ? "Reviewed · included in evaluation" : "Pending · excluded from evaluation"}
        </span>
      </header>
      <section class="contract-amazon-card">
        ${amazon.main_image_url ? `<img src="${escapeAttr(amazon.main_image_url)}" alt="" loading="lazy">` : `<div class="contract-image-placeholder">Amazon</div>`}
        <div>
          <span class="contract-source-label">Amazon target</span>
          <h3>${escapeHtml(amazon.title || item.amazon_title || "-")}</h3>
          <a href="${escapeAttr(amazon.listing_url || `https://www.amazon.com/dp/${item.asin}`)}" target="_blank" rel="noreferrer">${escapeHtml(item.asin || "Open listing")}</a>
        </div>
      </section>
      <div class="contract-artifact ${artifactClass}">
        <strong>${escapeHtml(artifactLabel)}</strong>
        <span>${escapeHtml(artifact.path || item.artifact_path || "")}</span>
        <code>${escapeHtml((artifact.actual_sha256 || artifact.expected_sha256 || "").slice(0, 16))}${artifact.expected_sha256 ? "…" : ""}</code>
      </div>
      <div class="contract-candidate-list">
        ${(item.candidates || []).map((candidate) => targetContractCandidate(item, candidate, noteId)).join("")}
      </div>
      <footer class="contract-case-footer">
        <label>
          <span>Review note</span>
          <textarea id="${escapeAttr(noteId)}" rows="2" maxlength="1000" placeholder="Why does this evidence match or not match?">${escapeHtml(item.review_notes || "")}</textarea>
        </label>
        <div>
          <button class="contract-no-match ${item.no_match === true ? "selected" : ""}" type="button"
            data-contract-action="no_match" data-case-id="${escapeAttr(item.case_id)}" data-note-id="${escapeAttr(noteId)}">
            No matching 1688 candidate
          </button>
          <small>Use no-match explicitly when every shown candidate is unsuitable.</small>
        </div>
      </footer>
    </article>
  `;
}

function targetContractCandidate(item, candidate, noteId) {
  const evidence = candidate.stored_evidence;
  const evidencePairs = targetContractEvidencePairs(evidence);
  return `
    <section class="contract-candidate-card ${escapeAttr(candidate.decision || "pending")}">
      <div class="contract-candidate-main">
        ${candidate.image_url ? `<img src="${escapeAttr(candidate.image_url)}" alt="" loading="lazy">` : `<div class="contract-image-placeholder">1688</div>`}
        <div>
          <span class="contract-source-label">1688 candidate · ${escapeHtml(candidate.offer_id)}</span>
          <h3>${escapeHtml(candidate.title || "-")}</h3>
          <a href="${escapeAttr(candidate.offer_url)}" target="_blank" rel="noreferrer">Open stored offer</a>
        </div>
      </div>
      <div class="contract-evidence-grid">
        ${evidencePairs.length
          ? evidencePairs.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")
          : `<p class="muted-text">The pinned artifact is unavailable; fixture title and offer ID are shown, but no unverified evidence is substituted.</p>`}
      </div>
      ${evidence ? `
        <details class="contract-raw-evidence">
          <summary>Stored evidence JSON</summary>
          <pre>${escapeHtml(JSON.stringify(evidence, null, 2))}</pre>
        </details>` : ""}
      <div class="contract-decision-controls" role="group" aria-label="Decision for offer ${escapeAttr(candidate.offer_id)}">
        <button class="accept ${candidate.decision === "accepted" ? "selected" : ""}" type="button"
          data-contract-action="accept" data-case-id="${escapeAttr(item.case_id)}"
          data-offer-id="${escapeAttr(candidate.offer_id)}" data-note-id="${escapeAttr(noteId)}">Accept match</button>
        <button class="reject ${candidate.decision === "rejected" ? "selected" : ""}" type="button"
          data-contract-action="reject" data-case-id="${escapeAttr(item.case_id)}"
          data-offer-id="${escapeAttr(candidate.offer_id)}" data-note-id="${escapeAttr(noteId)}">Reject match</button>
        <span>${escapeHtml(candidate.decision === "pending" ? "No decision" : candidate.decision)}</span>
      </div>
    </section>
  `;
}

function targetContractEvidencePairs(evidence) {
  if (!evidence || typeof evidence !== "object") return [];
  const raw = evidence.raw_data && typeof evidence.raw_data === "object" ? evidence.raw_data : {};
  const spec = raw.spec_match && typeof raw.spec_match === "object" ? raw.spec_match : {};
  const pairs = [
    ["Supplier", evidence.supplier_name],
    ["Price", evidence.base_price_cny === null || evidence.base_price_cny === undefined ? null : `¥${evidence.base_price_cny}`],
    ["MOQ", evidence.moq],
    ["Monthly sales", evidence.monthly_sales],
    ["Repeat buyer rate", evidence.repeat_buyer_rate === null || evidence.repeat_buyer_rate === undefined ? null : `${number(evidence.repeat_buyer_rate * 100, 1)}%`],
    ["Factory", evidence.is_factory === true ? "Yes" : evidence.is_factory === false ? "No" : null],
    ["Match score", evidence.match_quality_score === null || evidence.match_quality_score === undefined ? null : percent(evidence.match_quality_score)],
    ["Candidate score", evidence.candidate_score ?? raw.supplier_candidate_score],
    ["Spec conflicts", Array.isArray(spec.conflicts) ? spec.conflicts.join(", ") : null],
    ["Spec missing", Array.isArray(spec.missing) ? spec.missing.join(", ") : null],
  ];
  return pairs.filter(([, value]) => value !== null && value !== undefined && value !== "");
}

async function submitTargetContractReview(button) {
  const notice = $("#contractReviewNotice");
  const note = document.getElementById(button.dataset.noteId)?.value || "";
  const buttons = button.closest(".contract-review-case")?.querySelectorAll("button") || [];
  buttons.forEach((node) => { node.disabled = true; });
  notice.className = "contract-review-notice";
  notice.textContent = "Saving review decision…";
  try {
    const response = await postJson("/api/target-contract/reviews", {
      case_id: button.dataset.caseId,
      action: button.dataset.contractAction,
      offer_id: button.dataset.offerId || null,
      note,
    });
    const index = state.targetContractReviews.findIndex((item) => item.case_id === response.case.case_id);
    if (index >= 0) state.targetContractReviews[index] = response.case;
    notice.className = "contract-review-notice saved";
    notice.textContent = response.case.reviewed
      ? "Saved. This completed case is now eligible for target-contract evaluation."
      : "Saved. This case remains excluded until every candidate is decided with at least one acceptance, or no-match is explicit.";
    renderTargetContractReviews({ case_count: state.targetContractReviews.length });
  } catch (error) {
    buttons.forEach((node) => { node.disabled = false; });
    notice.className = "contract-review-notice error";
    notice.textContent = error.message;
  }
}

function fillAlibabaSearchApiForm(status) {
  const ns = $("#alibabaNamespaceInput");
  const method = $("#alibabaMethodInput");
  const keyword = $("#alibabaKeywordParamInput");
  const candidates = $("#alibabaCandidatesInput");
  if (ns && !ns.value) ns.value = status.namespace || "";
  if (method && !method.value) method.value = status.method || "";
  if (keyword && !keyword.value) keyword.value = status.keyword_param || "keywords";
  if (candidates && !candidates.value) candidates.value = status.candidates || "";
}

function toggleLanguage() {
  state.lang = state.lang === "en" ? "zh" : "en";
  localStorage.setItem("agentLang", state.lang);
  applyLanguage();
  renderTrialWorkflow();
  renderTrialFeedbackSummary();
}

function applyLanguage() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  $$("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  $$("[data-i18n-placeholder]").forEach((node) => {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  });
  const languageButton = $("#languageButton");
  languageButton.textContent = state.lang === "en" ? "中" : "EN";
  languageButton.setAttribute("aria-pressed", state.lang === "zh" ? "true" : "false");
  languageButton.setAttribute("aria-label", state.lang === "en" ? "Switch to Chinese" : "切换到英文");
  renderPreflight();
  renderCategorySelect();
  renderJobs();
  renderRuns();
  renderRunSelect();
  renderReviewFilter();
  updateReviewedDownloadLink();
  renderResults();
  renderManualQueue();
  renderConfigStatus();
  renderBrowserSetup();
  renderNotificationButton();
  renderSellerSpriteBrowserCapability(state.configStatus?.seller_sprite_browser || {});
  updateTrialSourceModeFields();
  renderTrialReadiness();
  renderTrialWorkflow();
  renderTargetContractReviews({ case_count: state.targetContractReviews.length });
  renderChatContext();
  renderSellerSpriteKeywordRows(state.sellerSpriteKeywordRows);
}

function t(key) {
  return I18N[state.lang]?.[key] || I18N.en[key] || key;
}

function tx(key, fallback) {
  const value = t(key);
  return value === key ? fallback : value;
}

function renderCategorySelect() {
  for (const select of [$("#categorySelect"), $("#trialCategorySelect")].filter(Boolean)) {
    if (!state.categories.length) continue;
    const current = select.value || "Home & Kitchen";
    select.innerHTML = state.categories.map((item) => {
      const label = state.lang === "zh"
        ? `${item.label_zh} / ${item.canonical}`
        : `${item.label_en} / ${item.label_zh}`;
      return `<option value="${escapeAttr(item.canonical)}">${escapeHtml(label)}</option>`;
    }).join("");
    select.value = state.categories.some((item) => item.canonical === current)
      ? current
      : state.categories[0].canonical;
  }
}

function updateTrialSourceModeFields() {
  const mode = $("#trialForm input[name='trial_source_mode']:checked")?.value || "category";
  $$("[data-trial-source-field]").forEach((node) => {
    node.classList.toggle("hidden", node.dataset.trialSourceField !== mode);
  });
}

function activeSourceMode() {
  return $("#runForm input[name='source_mode']:checked")?.value || "category";
}

function updateSourceModeFields() {
  const mode = activeSourceMode();
  $$("[data-source-field]").forEach((node) => {
    node.classList.toggle("hidden", node.dataset.sourceField !== mode);
  });
}

async function refreshKeywordPreview() {
  const hint = $("#keywordHint");
  if (!hint) return;
  if (activeSourceMode() !== "keyword") {
    hint.textContent = "";
    hint.className = "field-hint";
    return;
  }
  const keyword = $("#runForm input[name='keyword']")?.value.trim() || "";
  if (!keyword) {
    hint.textContent = state.lang === "zh" ? "Amazon US 请使用英文检索词，例如 outdoor patio umbrella。" : "Amazon US uses an English search query, for example outdoor patio umbrella.";
    hint.className = "field-hint";
    return;
  }
  try {
    const preview = await getJson(`/api/keyword-preview?keyword=${encodeURIComponent(keyword)}`);
    if (preview.requires_english_query) {
      hint.textContent = state.lang === "zh" ? "请输入对应英文检索词后再运行。" : "Enter the matching English query before running.";
      hint.className = "field-hint error";
      return;
    }
    const mapped = preview.normalized !== preview.original;
    hint.textContent = mapped
      ? `${state.lang === "zh" ? "Amazon US 实际检索词" : "Amazon US query"}: ${preview.normalized}`
      : `${state.lang === "zh" ? "Amazon US 检索词已确认" : "Amazon US query confirmed"}: ${preview.normalized}`;
    hint.className = "field-hint ok";
  } catch (error) {
    hint.textContent = error.message;
    hint.className = "field-hint error";
  }
}

function renderChatContext() {
  const context = $("#chatContext");
  if (!context) return;
  const runId = $("#runSelect")?.value || "";
  const query = $("#searchInput")?.value || "";
  const parts = [
    "Amazon US",
    runId ? `run ${runId}` : "",
    state.selectedAsin ? `ASIN ${state.selectedAsin}` : "",
    query ? `query ${query}` : "",
  ].filter(Boolean);
  context.textContent = parts.join(" · ");
}

function renderPreflight() {
  const ready = Boolean(state.preflight?.ready);
  $("#sideStatus").textContent = !state.preflight
    ? t("preflight.checking")
    : ready ? t("preflight.ready") : t("preflight.needsReview");
  $("#sideDot").className = `status-dot ${ready ? "ready" : state.preflight ? "error" : ""}`;
  $("#agentMetric").textContent = t("topMetrics.online");

  const cookie = (state.preflight?.checks || []).find((c) => c.key === "1688_cookies");
  $("#cookieMetric").textContent = !state.preflight
    ? t("preflight.checking")
    : cookie?.level === "ok" ? t("preflight.ready") : t("preflight.review");

  $("#preflightBadge").className = `badge ${ready ? "ok" : "err"}`;
  $("#preflightBadge").textContent = ready ? t("preflight.readyToRun") : t("preflight.actionRequired");
  if (!state.preflight) {
    $("#preflightBadge").textContent = t("preflight.checking");
  }
  updateRunAvailability();

  const list = $("#preflightList");
  list.innerHTML = "";
  for (const check of state.preflight?.checks || []) {
    const row = document.createElement("div");
    row.className = `check ${check.level}`;
    row.innerHTML = `
      <span class="mark">${check.level === "ok" ? "✓" : "!"}</span>
      <span>${escapeHtml(preflightLabel(check))}</span>
      <small>${escapeHtml(check.detail)}</small>
    `;
    list.appendChild(row);
  }

  const readyCard = $("#readyCard");
  readyCard.querySelector("strong").textContent = ready ? t("preflight.readyToRun") : t("preflight.actionRequired");
  if (!state.preflight) {
    readyCard.querySelector("strong").textContent = t("preflight.waiting");
  }
  readyCard.querySelector("p").textContent = ready
    ? t("preflight.allPassed")
    : state.preflight ? t("preflight.resolveFailed") : t("preflight.initialBody");
  renderSessionSetup();
  updateRunAvailability();
  renderTrialReadiness();
}

function renderSessionSetup() {
  const panel = $("#sessionSetupPanel");
  const items = $("#sessionSetupItems");
  if (!panel || !items) return;
  const checks = state.preflight?.checks || [];
  const missing = ["amazon", "1688"].filter((site) => {
    const key = site === "amazon" ? "amazon_cookies" : "1688_cookies";
    return checks.some((check) => check.key === key && check.level !== "ok");
  });
  panel.classList.toggle("hidden", !missing.length);
  items.replaceChildren();
  missing.forEach((site) => {
    const label = site === "amazon" ? "Amazon" : "1688";
    const phase = state.cookieSetupPhase[site] || "idle";
    const row = document.createElement("div");
    row.className = "session-setup-item";
    const text = document.createElement("span");
    text.innerHTML = `<strong>${label}</strong><small>${
      escapeHtml(site === "amazon"
        ? (state.lang === "zh" ? "缺少或不完整" : "Missing or incomplete")
        : (state.lang === "zh" ? "登录态缺失" : "Login session missing"))
    }</small>`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.dataset.cookieSite = site;
    button.textContent = phase === "awaiting_login" ? t("session.save") : t("session.auto");
    button.disabled = phase === "working";
    button.addEventListener("click", () => completeCookieSetup(site));
    row.append(text, button);
    items.appendChild(row);
  });
}

async function completeCookieSetup(site) {
  const status = $("#sessionSetupStatus");
  if (!state.browserSetup?.reachable) {
    status.className = "status-error";
    status.textContent = t("session.needsChrome");
    $(".nav-item[data-section='settings']")?.click();
    const guide = $("#browserSetupGuide");
    if (guide) guide.classList.remove("hidden");
    $("#toggleBrowserGuideButton")?.setAttribute("aria-expanded", "true");
    return;
  }
  const phase = state.cookieSetupPhase[site] || "idle";
  state.cookieSetupPhase[site] = "working";
  status.className = "";
  status.textContent = t("session.working");
  renderSessionSetup();
  try {
    const captured = await postJson("/api/browser-setup", {
      action: "save_cookies",
      site,
    });
    if (captured.ok) {
      state.cookieSetupPhase[site] = "saved";
      status.className = "status-ok";
      status.textContent = t("session.saved").replace("{site}", captured.label || site);
      await Promise.all([refreshPreflight(), refreshBrowserSetup()]);
      return;
    }
    if (phase !== "awaiting_login") {
      const opened = await postJson("/api/browser-setup", {
        action: "open_login",
        site,
      });
      state.cookieSetupPhase[site] = "awaiting_login";
      status.className = "status-ok";
      status.textContent = t("session.opened").replace("{site}", opened.label || site);
    } else {
      state.cookieSetupPhase[site] = "awaiting_login";
      status.className = "status-error";
      status.textContent = captured.message || t("session.opened").replace("{site}", site);
    }
  } catch (error) {
    state.cookieSetupPhase[site] = phase === "awaiting_login" ? phase : "idle";
    status.className = "status-error";
    status.textContent = error.message;
  } finally {
    renderSessionSetup();
  }
}

function renderTrialReadiness() {
  const checks = state.preflight?.checks || [];
  const checkReady = (key) => checks.some((item) => item.key === key && item.level === "ok");
  const readiness = {
    chrome: Boolean(state.browserSetup?.reachable),
    sellersprite: state.configStatus?.seller_sprite_browser?.status === "ready"
      || checkReady("seller_sprite_browser"),
    amazon: checkReady("amazon_cookies"),
    "1688": checkReady("1688_cookies"),
  };
  Object.entries(readiness).forEach(([key, ready]) => {
    const node = $(`[data-readiness="${key}"]`);
    if (!node) return;
    node.classList.toggle("ready", ready);
    node.classList.toggle("missing", !ready);
    node.setAttribute("aria-label", `${node.textContent}: ${ready ? "ready" : "action required"}`);
  });
  const running = trialJob() && ["queued", "running", "cancel_requested", "retry_wait"].includes(trialJob().status);
  const button = $("#trialStartButton");
  if (button) button.disabled = !Object.values(readiness).every(Boolean) || Boolean(running);
  const hint = $("#trialHint");
  if (hint && hint.dataset.queued !== "true") {
    const missing = Object.entries(readiness).filter(([, ready]) => !ready).map(([key]) => key);
    hint.textContent = missing.length
      ? (state.lang === "zh"
        ? `还需处理：${missing.join("、")}。可在“设置”查看 9222 与浏览器配置。`
        : `Action required: ${missing.join(", ")}. Open Settings for Chrome and browser configuration.`)
      : t("trial.ready");
  }
}

function trialJob() {
  const selected = state.jobs.find((job) => job.id === state.activeTrialJobId);
  const latest = state.jobs.find((job) => job.config?.workflow_mode === "full_research");
  if (selected) {
    // Follow retry descendants even when the retry was created by the API or
    // another browser tab, so the controlled-trial screen never stays pinned
    // to an obsolete failed attempt.
    const byId = new Map(state.jobs.map((job) => [job.id, job]));
    let ancestorId = latest?.retry_of;
    while (ancestorId) {
      if (ancestorId === selected.id) {
        state.activeTrialJobId = latest.id;
        localStorage.setItem("activeTrialJobId", latest.id);
        return latest;
      }
      ancestorId = byId.get(ancestorId)?.retry_of;
    }
    return selected;
  }
  if (latest) {
    state.activeTrialJobId = latest.id;
    localStorage.setItem("activeTrialJobId", latest.id);
  }
  return latest || null;
}

async function startFullResearch(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const sourceMode = String(form.get("trial_source_mode") || "category");
  const payload = {
    source_mode: sourceMode,
    marketplace: "US",
    limit: Number(form.get("limit") || 10),
    no_mock: true,
    generate_ai_reasons: Boolean(form.get("generate_ai_reasons")),
    require_supplier_evidence: true,
  };
  if (sourceMode === "keyword") {
    payload.keyword = String(form.get("keyword") || "").trim();
    payload.research_keyword = payload.keyword;
    payload.niche_label = payload.keyword;
  } else {
    payload.category = String(form.get("category") || "").trim();
    payload.research_keyword = payload.category;
    payload.niche_label = payload.category;
  }
  const button = $("#trialStartButton");
  const hint = $("#trialHint");
  button.disabled = true;
  hint.dataset.queued = "true";
  hint.textContent = t("trial.queued");
  try {
    const response = await postJson("/api/trial/full-research", payload);
    state.activeTrialJobId = response.job.id;
    localStorage.setItem("activeTrialJobId", response.job.id);
    await refreshJobs();
  } catch (error) {
    hint.dataset.queued = "false";
    hint.textContent = error.message;
    renderTrialReadiness();
  }
}

async function continueTrialJob() {
  const job = trialJob();
  if (!job) return;
  const button = $("#trialContinueButton");
  button.disabled = true;
  try {
    if (["failed", "cancelled"].includes(job.status) || !job.run_log_id) {
      const response = await postJson(`/api/jobs/${encodeURIComponent(job.id)}/retry`, {});
      state.activeTrialJobId = response.job.id;
      localStorage.setItem("activeTrialJobId", response.job.id);
    } else {
      const nodes = state.executionNodes[String(job.run_log_id)] || [];
      const node = nodes.find((item) => item.status === "human_required");
      if (!node) throw new Error("No resumable browser action was found.");
      await refresh1688SessionBeforeResume(node);
      await postJson(
        `/api/jobs/${encodeURIComponent(job.id)}/nodes/${encodeURIComponent(node.id)}/resume`,
        {
          reason: "Trial user completed the required browser action",
          resume_token: node.resume_token,
        },
      );
    }
    await refreshJobs();
  } catch (error) {
    const alert = $("#trialAlert");
    alert.classList.remove("hidden");
    alert.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderTrialWorkflow() {
  const job = trialJob();
  const badge = $("#trialStatusBadge");
  const meta = $("#trialJobMeta");
  const alert = $("#trialAlert");
  const continueButton = $("#trialContinueButton");
  const deliverables = $("#trialDeliverables");
  const feedback = $("#trialFeedbackForm");
  if (!badge || !meta || !alert || !continueButton || !deliverables || !feedback) return;

  $$("#trialStages li").forEach((item) => {
    item.classList.remove("active", "complete", "error", "human");
  });
  alert.classList.add("hidden");
  continueButton.classList.add("hidden");
  deliverables.classList.add("hidden");
  feedback.classList.add("hidden");

  if (!job) {
    badge.className = "badge muted";
    badge.textContent = t("trial.idle");
    meta.textContent = t("trial.noJob");
    renderTrialReadiness();
    return;
  }

  const source = job.config?.source_mode === "keyword"
    ? job.config.keyword
    : job.config?.category;
  meta.textContent = `${job.id} · ${source || "-"} · ${Number(job.config?.limit || 0)} ASIN`;
  badge.className = `badge ${job.status === "success" ? "ok" : ["failed", "cancelled"].includes(job.status) ? "err" : "warn"}`;
  badge.textContent = statusLabel(job.status);

  const events = Array.isArray(job.events) ? job.events : [];
  const hasResearch = job.research?.status === "SUCCESS";
  const researchAttempted = Boolean(job.research?.status)
    || events.some((event) => event.event === "market_research");
  const pipelineStarted = Boolean(job.run_log_id) || events.some((event) => event.event === "pipeline");
  const stageNodes = {
    preflight: $("#trialStages [data-stage='preflight']"),
    research: $("#trialStages [data-stage='research']"),
    sourcing: $("#trialStages [data-stage='sourcing']"),
    report: $("#trialStages [data-stage='report']"),
  };
  stageNodes.preflight.classList.add(
    job.status === "queued" ? "active"
      : job.status === "failed" && !researchAttempted && !pipelineStarted ? "error"
        : "complete"
  );
  if (hasResearch) stageNodes.research.classList.add("complete");
  else if (researchAttempted && (job.status === "running" || job.status === "human_required" || job.status === "failed")) {
    stageNodes.research.classList.add(job.status === "human_required" ? "human" : job.status === "failed" ? "error" : "active");
  }
  if (pipelineStarted) {
    stageNodes.sourcing.classList.add(
      job.status === "success" ? "complete"
        : job.status === "human_required" ? "human"
          : job.status === "review_required" ? "human"
          : job.status === "failed" || job.status === "cancelled" ? "error"
            : "active"
    );
  }
  if (job.status === "success" || (job.exports && Object.keys(job.exports).length)) {
    stageNodes.report.classList.add("complete");
  }

  if (job.error) {
    alert.classList.remove("hidden");
    alert.classList.toggle(
      "human",
      job.status === "human_required" || job.status === "review_required",
    );
    alert.textContent = jobMessageLabel(job.error);
  }
  if (job.status === "human_required" || job.status === "failed" || job.status === "cancelled") {
    continueButton.textContent = ["failed", "cancelled"].includes(job.status)
      ? t("actions.retry")
      : t("trial.continue");
    continueButton.classList.remove("hidden");
  }

  const links = trialDownloadLinks(job);
  if (links) {
    deliverables.classList.remove("hidden");
    $("#trialDownloadLinks").innerHTML = links;
  }
  if (["success", "failed", "cancelled", "review_required"].includes(job.status)) {
    feedback.classList.remove("hidden");
    if (feedback.dataset.jobId !== job.id) {
      feedback.reset();
      feedback.dataset.jobId = job.id;
      $("#trialFeedbackButton").disabled = false;
      $("#trialFeedbackStatus").textContent = "";
    }
  }
  const hint = $("#trialHint");
  if (!["queued", "running", "retry_wait"].includes(job.status)) {
    hint.dataset.queued = "false";
  }
  renderTrialReadiness();
}

async function submitTrialFeedback(event) {
  event.preventDefault();
  const job = trialJob();
  if (!job) return;
  const form = event.currentTarget;
  const button = $("#trialFeedbackButton");
  const status = $("#trialFeedbackStatus");
  const fields = new FormData(form);
  button.disabled = true;
  status.textContent = "";
  try {
    await postJson("/api/trial/feedback", {
      job_id: job.id,
      job_status: job.status,
      ease: Number(fields.get("ease")),
      result_usefulness: Number(fields.get("result_usefulness")),
      would_use_again: fields.get("would_use_again") === "true",
      blocked_stage: fields.get("blocked_stage") || "none",
      comment: String(fields.get("comment") || "").trim(),
    });
    status.textContent = t("trial.feedbackSaved");
    await refreshTrialFeedbackSummary();
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
}

function renderTrialFeedbackSummary() {
  const summary = state.trialFeedbackSummary;
  const badge = $("#trialValidationBadge");
  const criteria = $("#trialValidationCriteria");
  const blockers = $("#trialValidationBlockers");
  const decision = $("#trialValidationDecision");
  if (!badge || !criteria || !blockers || !decision) return;

  const sampleSize = Number(summary?.sample_size || 0);
  const minimumSample = Number(summary?.minimum_sample_size || 3);
  const metrics = summary?.metrics || {};
  $("#trialValidationSamples").textContent = `${sampleSize} / ${minimumSample}`;
  $("#trialValidationCoverage").textContent = `${Number(metrics.source_mode_count || 0)} / 2`;
  $("#trialValidationDelivery").textContent = trialPercent(metrics.delivery_rate);
  $("#trialValidationEase").textContent = trialRating(metrics.average_ease);
  $("#trialValidationUsefulness").textContent = trialRating(metrics.average_usefulness);
  $("#trialValidationAgain").textContent = trialPercent(metrics.would_use_again_rate);
  $("#trialValidationNoBlocker").textContent = trialPercent(metrics.no_blocker_rate);

  const status = summary?.status || "no_data";
  const statusView = {
    no_data: ["muted", "trial.validationNoData"],
    collecting: ["warn", "trial.validationCollecting"],
    ready_for_installer: ["ok", "trial.validationReady"],
    needs_improvement: ["err", "trial.validationImprove"],
  }[status] || ["muted", "trial.validationNoData"];
  badge.className = `badge ${statusView[0]}`;
  badge.textContent = t(statusView[1]);

  const criterionRows = Array.isArray(summary?.criteria) ? summary.criteria : [
    { key: "sample_size", passed: false },
    { key: "source_mode_count", passed: false },
    { key: "delivery_rate", passed: false },
    { key: "average_ease", passed: false },
    { key: "average_usefulness", passed: false },
    { key: "would_use_again_rate", passed: false },
    { key: "no_blocker_rate", passed: false },
  ];
  criteria.innerHTML = criterionRows.map((criterion) => {
    const pending = status === "no_data" || status === "collecting";
    const className = criterion.passed ? "pass" : pending ? "pending" : "fail";
    const icon = criterion.passed ? "✓" : pending ? "…" : "!";
    return `
      <div class="${className}">
        <span>${icon}</span>
        <strong>${escapeHtml(t(`trial.validationGate.${criterion.key}`))}</strong>
      </div>
    `;
  }).join("");

  const blockerCounts = summary?.blocker_counts || {};
  const blockerLabels = {
    none: t("trial.feedbackNone"),
    preflight: t("trial.feedbackPreflight"),
    market_research: t("trial.feedbackResearch"),
    sourcing: t("trial.feedbackSourcing"),
    report: t("trial.feedbackReport"),
  };
  const blockerRows = Object.entries(blockerLabels)
    .filter(([key]) => Number(blockerCounts[key] || 0) > 0)
    .map(([key, label]) => `
      <span class="${key === "none" ? "clear" : ""}">
        ${escapeHtml(label)} <strong>${Number(blockerCounts[key] || 0)}</strong>
      </span>
    `);
  blockers.innerHTML = blockerRows.length
    ? blockerRows.join("")
    : `<small>${escapeHtml(t("trial.validationEmptyBlockers"))}</small>`;

  if (status === "collecting") {
    decision.textContent = t("trial.validationCollectingHint").replace(
      "{count}",
      String(Number(summary?.remaining_trials || 0)),
    );
  } else if (status === "ready_for_installer") {
    decision.textContent = t("trial.validationReadyHint");
  } else if (status === "needs_improvement") {
    decision.textContent = t("trial.validationImproveHint");
  } else {
    decision.textContent = t("trial.validationNoDataHint");
  }
  decision.className = `trial-validation-decision ${status}`;
}

function trialRating(value) {
  return value === null || value === undefined ? "— / 5" : `${Number(value).toFixed(1)} / 5`;
}

function trialPercent(value) {
  return value === null || value === undefined ? "—" : `${Math.round(Number(value) * 100)}%`;
}

function trialDownloadLinks(job) {
  const links = [];
  const add = (label, path) => {
    if (!path) return;
    const filename = String(path).split(/[\\/]/).pop();
    links.push(`<a class="ghost-button" href="/api/exports/${encodeURIComponent(filename)}">${escapeHtml(label)}</a>`);
  };
  add(state.lang === "zh" ? "市场汇总 Excel" : "Market research Excel", job.research?.exports?.xlsx);
  add(state.lang === "zh" ? "市场数据 JSON" : "Market research JSON", job.research?.exports?.json);
  add(state.lang === "zh" ? "选品结果 Excel" : "Sourcing results Excel", job.exports?.xlsx);
  add(state.lang === "zh" ? "选品证据 JSON" : "Sourcing evidence JSON", job.exports?.json);
  return links.join("");
}

function renderJobs() {
  const list = $("#jobList");
  list.innerHTML = "";
  const jobs = state.jobs.slice(0, 5);
  if (!jobs.length) {
    list.innerHTML = `<div class="job"><span class="job-dot"></span><div><strong>${escapeHtml(t("jobs.noActive"))}</strong><span>${escapeHtml(t("jobs.noActiveHint"))}</span></div></div>`;
    return;
  }
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = `job ${job.status}`;
    const mode = job.config.source_mode || "category";
    const source = mode === "keyword" ? job.config.keyword : job.config.category;
    const meta = `${mode} · ${source || "-"} · Amazon US · ${job.config.limit}`;
    const summary = job.result_summary && job.result_summary.summary
      ? `<p class="job-summary">${escapeHtml(job.result_summary.summary.split("\n").slice(0, 3).join(" "))}</p>`
      : "";
    const events = jobEventTimeline(job);
    const nodes = executionNodeList(job);
    row.innerHTML = `
      <span class="job-dot"></span>
      <div>
        <strong>${escapeHtml(statusLabel(job.status).toUpperCase())} · ${escapeHtml(jobMessageLabel(job.message || ""))}</strong>
        <span>${escapeHtml(meta)}${job.queue_position ? ` · #${Number(job.queue_position)}` : ""}${job.error ? ` · ${escapeHtml(jobMessageLabel(job.error))}` : ""}</span>
        ${summary}
        ${events}
        ${nodes}
      </div>
      <div class="job-actions">
        <span class="badge ${job.status === "success" ? "ok" : job.status === "failed" || job.status === "cancelled" ? "err" : "warn"}">${escapeHtml(statusLabel(job.status))}</span>
        ${jobActionButtons(job)}
      </div>
    `;
    list.appendChild(row);
  }
  $$(".job-action").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.action;
      const jobId = button.dataset.jobId;
      button.disabled = true;
      if (action === "cancel") {
        markJobCancelRequested(jobId);
        renderJobs();
      }
      try {
        await postJobAction(jobId, action);
        await refreshJobs();
      } catch (error) {
        button.textContent = error.message;
      }
    });
  });
  $$(".node-action").forEach((button) => {
    button.addEventListener("click", async () => {
      const reason = window.prompt(`${button.textContent}: reason / 原因`);
      if (!reason || !reason.trim()) return;
      button.disabled = true;
      try {
        if (button.dataset.action === "resume") {
          const job = state.jobs.find((item) => item.id === button.dataset.jobId);
          const node = (state.executionNodes[String(job?.run_log_id)] || [])
            .find((item) => String(item.id) === button.dataset.nodeId);
          await refresh1688SessionBeforeResume(node);
        }
        await postJson(
          `/api/jobs/${encodeURIComponent(button.dataset.jobId)}/nodes/${encodeURIComponent(button.dataset.nodeId)}/${button.dataset.action}`,
          { reason: reason.trim(), resume_token: button.dataset.resumeToken },
        );
        await refreshJobs();
      } catch (error) {
        button.textContent = error.message;
      }
    });
  });
}

function executionNodeList(job) {
  if (!job.run_log_id) return "";
  const nodes = state.executionNodes[String(job.run_log_id)] || [];
  if (!nodes.length) return "";
  return `<ul class="execution-nodes">${nodes.map((node) => {
    const scope = node.scope_type === "asin" ? node.scope_key : "run";
    const human = node.human_action_required || {};
    const detail = human.instructions || node.error_detail || node.error_code || "";
    return `<li><div><span><code>${escapeHtml(scope)}</code> · ${escapeHtml(node.stage)} · <b>${escapeHtml(statusLabel(node.status))}</b> · #${Number(node.attempt_count || 0)}</span>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</div>${nodeActionButton(job, node)}</li>`;
  }).join("")}</ul>`;
}

function nodeActionButton(job, node) {
  if (["queued", "running", "cancel_requested"].includes(job.status)) return "";
  const token = escapeAttr(node.resume_token || "");
  if (node.status === "human_required") {
    return `<button class="link-button node-action" data-job-id="${escapeAttr(job.id)}" data-node-id="${Number(node.id)}" data-resume-token="${token}" data-error-code="${escapeAttr(node.error_code || "")}" data-action="resume">${escapeHtml(t("actions.resume"))}</button>`;
  }
  if (["failed", "timed_out"].includes(node.status)) {
    return `<button class="link-button node-action" data-job-id="${escapeAttr(job.id)}" data-node-id="${Number(node.id)}" data-resume-token="${token}" data-action="retry">${escapeHtml(t("actions.retry"))}</button>`;
  }
  if (["succeeded", "skipped", "cancelled"].includes(node.status)) {
    return `<button class="link-button node-action" data-job-id="${escapeAttr(job.id)}" data-node-id="${Number(node.id)}" data-resume-token="${token}" data-action="force-rerun">${escapeHtml(t("actions.forceRerun"))}</button>`;
  }
  return "";
}

function jobEventTimeline(job) {
  const events = Array.isArray(job.events) ? job.events.slice(-3) : [];
  if (!events.length) return "";
  const rows = events.map((event) => {
    const label = event.event || event.stage || "event";
    const asin = event.asin ? ` · ${event.asin}` : "";
    const progress = event.index && event.total ? ` · ${event.index}/${event.total}` : "";
    const message = jobMessageLabel(event.message || label);
    return `<li><span>${escapeHtml(label)}${escapeHtml(asin)}${escapeHtml(progress)}</span><em>${escapeHtml(message)}</em></li>`;
  }).join("");
  return `<ol class="job-events">${rows}</ol>`;
}

function markJobCancelRequested(jobId) {
  const job = state.jobs.find((item) => item.id === jobId);
  if (!job || !["queued", "running", "cancel_requested"].includes(job.status)) return;
  job.status = "cancel_requested";
  job.cancel_requested = true;
  job.message = "Cancellation requested";
  job.events = [
    ...(Array.isArray(job.events) ? job.events : []),
    { event: "cancel_requested", message: "Cancellation requested" },
  ];
}

function jobActionButtons(job) {
  if (job.status === "queued" || job.status === "running" || job.status === "cancel_requested") {
    return `<button class="link-button job-action" data-action="cancel" data-job-id="${escapeAttr(job.id)}">${escapeHtml(t("actions.cancel"))}</button>`;
  }
  if (job.status === "failed" || job.status === "cancelled" || (job.status === "human_required" && !job.run_log_id)) {
    return `<button class="link-button job-action" data-action="retry" data-job-id="${escapeAttr(job.id)}">${escapeHtml(t("actions.retry"))}</button>`;
  }
  return "";
}

async function postJobAction(jobId, action) {
  if (action === "cancel") {
    return postJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {});
  }
  if (action === "retry") {
    return postJson(`/api/jobs/${encodeURIComponent(jobId)}/retry`, {});
  }
  throw new Error(`Unsupported job action: ${action}`);
}

function renderRuns() {
  const list = $("#exportRunList");
  list.innerHTML = "";
  for (const run of state.runs.slice(0, 5)) {
    const row = document.createElement("div");
    row.className = "export-run";
    const quality = run.sourcing_quality || "needs_review";
    row.innerHTML = `
      <span class="job-dot success"></span>
      <div>
        <strong>${escapeHtml(run.id)}</strong>
        <span>${run.count} ${escapeHtml(t("recent.rows"))} · ${escapeHtml(t("recent.ready"))} ${run.review_ready_count ?? 0} · ${escapeHtml(t("recent.manual"))} ${run.review_manual_count ?? 0} · ${escapeHtml(t("recent.market"))} ${marketCoverage(run)} · ${escapeHtml(t("recent.avgScore"))} ${run.avg_score ?? "-"}</span>
      </div>
      <span class="quality-pill ${qualityClass(quality)}">${escapeHtml(qualityLabel(quality))}</span>
      ${run.xlsx_file ? `<a class="ghost-button" href="/api/exports/${encodeURIComponent(run.xlsx_file)}">${escapeHtml(t("actions.export"))}</a>` : ""}
    `;
    list.appendChild(row);
  }
}

function marketCoverage(run) {
  const basic = Number(run.market_data_count ?? 0);
  const rich = Number(run.market_data_rich_count ?? basic);
  return `${Number.isFinite(rich) ? rich : 0}/${Number.isFinite(basic) ? basic : 0}`;
}

function renderManualQueue() {
  const list = $("#manualQueueList");
  const count = $("#manualQueueCount");
  if (!list || !count) return;
  count.textContent = state.manualQueue.length;
  list.innerHTML = "";
  if (!state.manualQueue.length) {
    list.innerHTML = `<div class="manual-empty">${escapeHtml(t("manual.empty"))}</div>`;
    return;
  }
  for (const item of state.manualQueue.slice(0, 5)) {
    const row = document.createElement("div");
    row.className = "manual-item";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(item.asin || "-")}</strong>
        <span title="${escapeAttr(item.title || "")}">${escapeHtml(item.title || "-")}</span>
        <small>${escapeHtml(t("manual.keywords"))}: ${escapeHtml((item.keywords || []).slice(0, 4).join(", ") || "-")}</small>
        <em>${escapeHtml(item.reason || "")}</em>
      </div>
      <div class="manual-actions">
        <button class="link-button manual-update" data-key="${escapeAttr(item.key)}" data-status="resolved">${escapeHtml(t("manual.resolve"))}</button>
        <button class="link-button manual-update" data-key="${escapeAttr(item.key)}" data-status="ignored">${escapeHtml(t("manual.ignore"))}</button>
      </div>
    `;
    list.appendChild(row);
  }
  $$(".manual-update").forEach((button) => {
    button.addEventListener("click", async () => {
      await postJson("/api/manual-queue", {
        key: button.dataset.key,
        status: button.dataset.status,
      });
      await refreshManualQueue();
    });
  });
}

function renderConfigStatus() {
  const grid = $("#configStatusGrid");
  if (!grid) return;
  const status = state.configStatus;
  if (!status) {
    grid.innerHTML = "";
    return;
  }
  const cards = [
    capabilityCard(
      "settings.capability.sellerSprite",
      Boolean(status.seller_sprite?.configured),
      sellerSpriteDetail(status.seller_sprite),
      !status.seller_sprite?.configured,
    ),
    capabilityCard(
      "settings.capability.vision",
      Boolean(status.vision?.configured),
      status.vision?.configured ? status.vision.provider : "PPIO_API_KEY / ANTHROPIC_API_KEY",
    ),
    capabilityCard(
      "settings.capability.alibaba",
      Boolean(status.alibaba_open?.configured),
      alibabaOpenDetail(status.alibaba_open),
    ),
    capabilityCard(
      "settings.capability.scrapling",
      Boolean(status.runtime?.enable_scrapling_matcher),
      status.runtime?.enable_scrapling_matcher ? t("settings.enabled") : t("settings.disabled"),
      true,
    ),
    capabilityCard(
      "settings.capability.cache",
      Boolean(status.runtime?.cache_enabled),
      status.runtime?.cache_enabled ? t("settings.enabled") : t("settings.disabled"),
      true,
    ),
    capabilityCard(
      "settings.capability.browserAgent",
      Boolean(status.browser_agent?.configured),
      browserAgentDetail(status.browser_agent),
    ),
  ];
  grid.innerHTML = cards.join("");
  if (status.vision) {
    $("#visionModelInput").value = status.vision.model || "";
    $("#visionBaseInput").value = status.vision.base_url || "";
  }
  updateRunAvailability();
}

function marketDataGuardError() {
  const requireMarket = Boolean($("#runForm input[name='require_market_data']")?.checked);
  if (!requireMarket) return "";
  const check = state.configStatus?.seller_sprite?.last_check || {};
  if (check.has_market_evidence) return "";
  return t("run.marketDataBlocked");
}

function updateRunAvailability() {
  const button = $("#runButton");
  const hint = $("#runHint");
  if (!button || !hint) return;
  const ready = Boolean(state.preflight?.ready);
  const guard = marketDataGuardError();
  button.disabled = !ready || Boolean(guard);
  if (hint.dataset.queued === "true") {
    hint.textContent = t("run.hintQueued");
    return;
  }
  hint.textContent = guard || t("run.hintDefault");
}

function capabilityCard(labelKey, ok, detail, neutral = false) {
  const stateClass = neutral ? "neutral" : ok ? "ok" : "warn";
  const badge = neutral
    ? (ok ? t("settings.enabled") : t("settings.disabled"))
    : (ok ? t("settings.configured") : t("settings.missing"));
  return `
    <div class="config-card ${stateClass}">
      <div>
        <strong>${escapeHtml(t(labelKey))}</strong>
        <span>${escapeHtml(detail || "-")}</span>
      </div>
      <small>${escapeHtml(badge)}</small>
    </div>
  `;
}

function sellerSpriteDetail(status) {
  if (!status?.configured) return t("settings.sellerSpriteOptional");
  const cap = Number(status.max_products_per_run ?? 0);
  const keyLength = Number(status.key_length ?? 0);
  const check = status.last_check || {};
  const checkText = check.has_market_evidence
    ? `${check.evidence_source || "market"} ok ${check.asin || ""}`.trim()
    : check.error ? "ASIN failed" : "ASIN unchecked";
  return `key ${Number.isFinite(keyLength) ? keyLength : 0} chars · cap ${Number.isFinite(cap) ? cap : 0}/run · ${checkText} · ${status.base_url || "-"}`;
}

function browserAgentDetail(status) {
  const domains = (status?.allowed_domains || []).slice(0, 4).join(", ");
  const cdp = status?.cdp_http_configured ? "CDP HTTP" : status?.cdp_ws_configured ? "CDP WS" : "CDP missing";
  return `${status?.tool || "browser-use"} · ${status?.mode || "local"} · ${cdp} · ${domains || "-"}`;
}

function sellerSpriteAsinSummary(result) {
  const prefix = result.error || !result.has_market_evidence
    ? t("settings.asinCheckFailed")
    : t("settings.asinCheckOk");
  const fields = [
    `${result.asin || "-"} ${result.marketplace || ""}`.trim(),
    `key ${Number(result.key_length || 0)} chars`,
    result.evidence_source ? `source ${result.evidence_source}` : "",
    result.bsr ? `BSR ${result.bsr}` : "",
    result.est_monthly_sales ? `${formatInteger(result.est_monthly_sales)} sales/mo` : "",
    result.review_count ? `${result.review_count} reviews` : "",
    sellerSpriteApiChecks(result.api_checks),
    result.error || "",
  ].filter(Boolean);
  return `${prefix}: ${fields.join(" · ")}`;
}

function sellerSpriteApiChecks(checks) {
  const items = (checks || []).slice(0, 3).map((item) => {
    const state = item.evidence ? "evidence" : item.ok ? "ok" : "failed";
    return `${item.name || "api"} ${state}`;
  });
  return items.join(", ");
}

function alibabaMissingParts(status) {
  if (!status) return "ALIBABA_APP_KEY / ALIBABA_APP_SECRET / ALIBABA_ACCESS_TOKEN";
  const missing = [];
  if (!status.has_app_key) missing.push("ALIBABA_APP_KEY");
  if (!status.has_app_secret) missing.push("ALIBABA_APP_SECRET");
  if (!status.has_access_token) missing.push("ALIBABA_ACCESS_TOKEN");
  return missing.join(" / ") || "-";
}

function alibabaOpenDetail(status) {
  if (!status?.configured) return alibabaMissingParts(status);
  const check = status.last_check || {};
  const apiName = [status.namespace, status.method].filter(Boolean).join("/");
  const checkText = check.has_supplier_evidence
    ? `pifatuan ok ${check.count || 0} suppliers`.trim()
    : check.error ? "pifatuan failed" : "pifatuan unchecked";
  return `${checkText} · ${apiName || "-"} · ${status.gateway || "-"}`;
}

function alibabaPifatuanSummary(result) {
  const prefix = result.error || !result.count
    ? t("settings.pifatuanCheckFailed")
    : t("settings.pifatuanCheckOk");
  const first = (result.suppliers || [])[0] || {};
  const fields = [
    result.keyword || "-",
    [result.namespace, result.method].filter(Boolean).join("/") || "",
    `${Number(result.count || 0)} suppliers`,
    first.supplier || first.title || "",
    first.monthly_sales ? `${formatInteger(first.monthly_sales)} sales` : "",
    alibabaAttemptSummary(result.attempts),
    result.error || "",
  ].filter(Boolean);
  return `${prefix}: ${fields.join(" · ")}`;
}

function alibabaAttemptSummary(attempts) {
  const items = (attempts || []).slice(0, 4).map((item) => {
    const name = [item.namespace, item.method].filter(Boolean).join("/");
    const state = item.ok ? `${Number(item.count || 0)} ok` : "failed";
    return `${name || "api"} ${state}`;
  });
  return items.join(", ");
}

function renderRunSelect() {
  const select = $("#runSelect");
  const current = select.value;
  select.innerHTML = `<option value="">${escapeHtml(t("runSelect.all"))}</option>`;
  for (const run of state.runs) {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = `${run.id} (${run.count})`;
    select.appendChild(option);
  }
  select.value = current;
  updateReviewedDownloadLink();
}

function updateReviewedDownloadLink() {
  const link = $("#downloadReviewedButton");
  if (!link) return;
  const runId = $("#runSelect")?.value || "";
  link.href = `/api/reviewed-suppliers.csv${runId ? `?run=${encodeURIComponent(runId)}` : ""}`;
}

function renderReviewFilter() {
  const select = $("#reviewFilter");
  if (!select) return;
  const current = state.reviewFilter || "all";
  select.innerHTML = ["all", "accepted", "pending", "rejected"].map((value) => (
    `<option value="${value}">${escapeHtml(t(`results.reviewFilter.${value}`))}</option>`
  )).join("");
  select.value = current;
}

function renderResults() {
  const query = $("#searchInput").value.trim().toLowerCase();
  state.reviewFilter = $("#reviewFilter").value || state.reviewFilter || "all";
  const body = $("#resultsBody");
  body.innerHTML = "";

  const filtered = state.results.filter((item) => {
    const textMatch = !query || [item.asin, item.title, item.supplier].some((v) => String(v || "").toLowerCase().includes(query));
    return textMatch && reviewFilterMatch(item);
  }).sort(reviewSort);

  for (const item of filtered) {
    const row = document.createElement("tr");
    row.className = "result-row";
    row.dataset.asin = item.asin || "";
    const status = item.mock ? t("status.mock") : item.passed ? t("status.selected") : t("status.review");
    const statusClass = item.mock ? "rejected" : item.passed ? "selected" : "review";
    row.innerHTML = `
      <td><button class="save-button ${item.saved ? "saved" : ""}" data-key="${escapeAttr(item.key)}">${item.saved ? "✓" : "+"}</button></td>
      <td>${reviewToggle(item)}</td>
      <td><strong>${escapeHtml(item.asin || "-")}</strong></td>
      <td class="title-cell" title="${escapeAttr(item.title || "")}">${escapeHtml(item.title || "-")}</td>
      <td class="supplier-cell" title="${escapeAttr(item.supplier || "")}">${offerLink(item)}${supplierReviewSummaryPill(item)}</td>
      <td>${money(item.buy_cost_cny, "¥")}</td>
      <td>${percent(item.margin)}</td>
      <td>${matchPill(item)}</td>
      <td><span class="score-pill">${number(item.score, 0)}</span></td>
      <td><span class="status ${statusClass}">${status}</span></td>
      <td>${item.xlsx_file ? `<a class="ghost-button" href="/api/exports/${encodeURIComponent(item.xlsx_file)}">${escapeHtml(t("actions.download"))}</a>` : "-"}</td>
      <td><button class="link-button hide-result" data-key="${escapeAttr(item.key)}">${escapeHtml(t("actions.delete"))}</button></td>
    `;
    body.appendChild(row);
    if (state.expandedReviews.has(item.key)) {
      const detailRow = document.createElement("tr");
      detailRow.className = "review-detail-row";
      detailRow.innerHTML = `<td colspan="12">${reviewPanel(item)}</td>`;
      body.appendChild(detailRow);
    }
  }

  $$(".save-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const key = button.dataset.key;
      const saved = !button.classList.contains("saved");
      await postJson("/api/saved", { key, saved });
      const item = state.results.find((r) => r.key === key);
      if (item) item.saved = saved;
      renderResults();
    });
  });
  $$(".review-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.key;
      const item = state.results.find((r) => r.key === key);
      state.selectedAsin = item?.asin || "";
      renderChatContext();
      if (state.expandedReviews.has(key)) {
        state.expandedReviews.delete(key);
      } else {
        state.expandedReviews.add(key);
      }
      renderResults();
    });
  });
  $$(".result-row").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("button, a, input, select")) return;
      state.selectedAsin = row.dataset.asin || "";
      renderChatContext();
    });
  });
  $$(".supplier-review-action").forEach((button) => {
    button.addEventListener("click", async () => {
      await postJson("/api/supplier-review", {
        key: button.dataset.reviewKey,
        status: button.dataset.status,
      });
      updateSupplierReviewState(button.dataset.reviewKey, button.dataset.status);
      renderResults();
    });
  });
  $$(".hide-result").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!window.confirm(t("results.deleteConfirm"))) return;
      await postJson("/api/results/hide", { key: button.dataset.key });
      state.results = state.results.filter((item) => item.key !== button.dataset.key);
      state.expandedReviews.delete(button.dataset.key);
      renderResults();
    });
  });
  bindImageFallbacks();

  $("#resultCount").textContent = state.lang === "zh" ? `${filtered.length} 条结果` : `${filtered.length} results`;
  renderChatContext();
}

function reviewFilterMatch(item) {
  const filter = state.reviewFilter || "all";
  if (filter === "all") return true;
  const summary = item.supplier_review_summary || {};
  return Number(summary[filter] || 0) > 0;
}

function reviewSort(a, b) {
  const acceptedDelta = Number(b.supplier_review_summary?.accepted || 0) - Number(a.supplier_review_summary?.accepted || 0);
  if (acceptedDelta) return acceptedDelta;
  const scoreDelta = Number(b.score || 0) - Number(a.score || 0);
  return scoreDelta || String(a.asin || "").localeCompare(String(b.asin || ""));
}

function supplierReviewSummaryPill(item) {
  const summary = item.supplier_review_summary || {};
  const parts = [
    ["accepted", summary.accepted],
    ["rejected", summary.rejected],
    ["pending", summary.pending],
  ].filter(([, count]) => Number(count || 0) > 0);
  if (!parts.length) return "";
  return `
    <div class="supplier-review-summary">
      ${parts.map(([status, count]) => `<span class="${escapeAttr(status)}">${Number(count)} ${escapeHtml(t(`review.${status}Short`))}</span>`).join("")}
    </div>
  `;
}

async function startRun() {
  const form = new FormData($("#runForm"));
  const source_mode = String(form.get("source_mode") || "category");
  const payload = {
    source_mode,
    marketplace: "US",
    limit: Number(form.get("limit") || 10),
    no_mock: true,
    llm_verification: Boolean(form.get("llm_verification")),
    require_market_data: Boolean(form.get("require_market_data")),
    require_supplier_evidence: Boolean(form.get("require_supplier_evidence")),
  };
  if (source_mode === "keyword") {
    payload.keyword = String(form.get("keyword") || "").trim();
  } else {
    payload.category = String(form.get("category") || "").trim();
  }
  const guard = marketDataGuardError();
  if (guard) {
    $("#runHint").dataset.queued = "false";
    $("#runHint").textContent = guard;
    updateRunAvailability();
    return;
  }
  $("#runButton").disabled = true;
  $("#runHint").dataset.queued = "true";
  $("#runHint").textContent = t("run.hintQueued");
  try {
    await postJson("/api/run", payload);
    await refreshJobs();
  } catch (error) {
    $("#runHint").textContent = error.message;
  } finally {
    setTimeout(() => {
      $("#runHint").dataset.queued = "false";
      updateRunAvailability();
    }, 1200);
  }
}

async function sendChatMessage(event) {
  event.preventDefault();
  const input = $("#chatInput");
  const message = input.value.trim();
  if (!message) return;
  appendChatMessage("user", message);
  input.value = "";
  try {
    const result = await postJson("/api/chat", {
      message,
      run_id: $("#runSelect")?.value || "",
      selected_asin: state.selectedAsin || "",
      current_query: $("#searchInput")?.value || "",
    });
    appendChatMessage("assistant", result.answer || "");
  } catch (error) {
    appendChatMessage("assistant", error.message);
  }
}

function appendChatMessage(role, text) {
  const list = $("#chatMessages");
  if (!list) return;
  const item = document.createElement("div");
  item.className = `chat-message ${role}`;
  item.textContent = text || "";
  list.appendChild(item);
  list.scrollTop = list.scrollHeight;
}

function preflightLabel(check) {
  return PREFLIGHT_LABELS[state.lang]?.[check.key] || check.label;
}

function statusLabel(status) {
  return t(`status.${status}`);
}

function jobMessageLabel(message) {
  if (!message) return "";
  return JOB_MESSAGE_LABELS[state.lang]?.[message] || message;
}

function qualityLabel(quality) {
  return t(`recent.quality.${quality || "needs_review"}`);
}

function qualityClass(quality) {
  if (quality === "ready") return "ok";
  if (quality === "blocked" || quality === "conflict_review") return "err";
  return "warn";
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

// ---- Market research (seller shortlist) ----
async function runResearchImport(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const status = $("#researchImportStatus");
  const payload = {
    file: String(form.get("file") || "").trim(),
    niche_label: String(form.get("niche_label") || "").trim(),
    keyword: String(form.get("keyword") || "").trim(),
    category: String(form.get("category") || "auto"),
    generate_ai_reasons: form.get("generate_ai_reasons") === "on",
  };
  if (!payload.file) {
    status.textContent = "Export file name is required.";
    return;
  }
  status.textContent = "Analyzing export…";
  try {
    const data = await postJson("/api/seller-research/import", payload);
    status.textContent = `Done: ${(data.items || []).length} eligible sellers.`;
    renderResearchResult(data);
    refreshResearchHistory();
  } catch (error) {
    status.textContent = `Failed: ${error.message}`;
  }
}

async function runResearchBrowserExport(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const status = $("#researchBrowserStatus");
  const payload = {
    keyword: String(form.get("keyword") || "").trim(),
    niche_label: String(form.get("niche_label") || "").trim(),
    category: String(form.get("category") || "auto"),
    sellersprite_url: String(form.get("sellersprite_url") || "").trim(),
  };
  if (!payload.keyword) {
    status.textContent = "Keyword is required.";
    return;
  }
  status.textContent = "Running browser export… (Chrome must be attached)";
  try {
    const data = await postJson("/api/seller-research/browser-export", payload);
    if (data.status && data.status !== "SUCCESS") {
      status.textContent = `Needs action: ${data.status}${data.message ? " — " + data.message : ""}`;
      renderResearchResult(data);
      return;
    }
    status.textContent = `Done: ${(data.items || []).length} eligible sellers.`;
    renderResearchResult(data);
    refreshResearchHistory();
  } catch (error) {
    status.textContent = `Failed: ${error.message}`;
  }
}

async function refreshResearchHistory() {
  const container = $("#researchHistory");
  if (!container) return;
  try {
    const data = await getJson("/api/seller-research/lists?limit=20");
    renderResearchHistory(data.items || []);
  } catch (error) {
    container.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function renderResearchHistory(items) {
  const container = $("#researchHistory");
  if (!container) return;
  if (!items.length) {
    container.innerHTML = `<p class="muted">No research runs yet.</p>`;
    return;
  }
  const rows = items.map((item) => `
    <tr>
      <td>${escapeHtml(item.niche_label || "-")}</td>
      <td>${escapeHtml(item.keyword || "-")}</td>
      <td>${item.eligible_count ?? 0}</td>
      <td>${item.excluded_count ?? 0}</td>
      <td>${escapeHtml(String(item.imported_at || "").replace("T", " ").slice(0, 19))}</td>
      <td><button class="link-button" data-run="${escapeAttr(item.id)}">Open</button></td>
    </tr>`).join("");
  container.innerHTML = `
    <table class="research-table">
      <thead><tr><th>Niche</th><th>Keyword</th><th>Eligible</th><th>Excluded</th><th>Imported</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  container.querySelectorAll("button[data-run]").forEach((button) => {
    button.addEventListener("click", () => openResearchRun(button.dataset.run));
  });
}

async function openResearchRun(runId) {
  try {
    const data = await getJson(`/api/seller-research/lists/${encodeURIComponent(runId)}`);
    renderResearchResult(data);
  } catch (error) {
    const summary = $("#researchSummary");
    if (summary) summary.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function renderResearchResult(payload) {
  const summary = $("#researchSummary");
  const results = $("#researchResults");
  if (!payload || (!payload.items && !payload.excluded_items)) {
    if (summary) {
      summary.innerHTML = payload && payload.status
        ? `<p class="muted">Status: ${escapeHtml(payload.status)}${payload.message ? " — " + escapeHtml(payload.message) : ""}</p>`
        : "";
    }
    if (results) results.innerHTML = "";
    return;
  }
  const items = payload.items || [];
  const excluded = payload.excluded_items || [];
  const ai = payload.ai_reasons || {};
  const aiNote = ai.status === "success"
    ? `AI reasons ${ai.applied_count}/${ai.requested_count}`
    : `AI reasons: ${ai.status || "n/a"}`;
  if (summary) {
    summary.innerHTML = `
      <div class="research-summary-head">
        <strong>${escapeHtml(payload.niche_label || payload.keyword || "Seller shortlist")}</strong>
        <span class="muted">${items.length} eligible · ${excluded.length} excluded · ${escapeHtml(aiNote)}</span>
        ${renderResearchExports(payload.exports)}
      </div>`;
  }
  if (results) {
    results.innerHTML = renderResearchTable(items) + (excluded.length ? renderExcludedTable(excluded) : "");
  }
}

function renderResearchExports(exports) {
  if (!exports) return "";
  const links = Object.entries(exports).map(([kind, name]) =>
    `<a class="link-button" href="/api/exports/${encodeURIComponent(name)}">${escapeHtml(String(kind).toUpperCase())}</a>`).join(" ");
  return links ? `<span class="research-exports">${links}</span>` : "";
}

function renderResearchTable(items) {
  if (!items.length) return `<p class="muted">No sellers passed the small-seller rules.</p>`;
  const rows = items.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${escapeHtml(item.seller || "-")}</td>
      <td><span class="research-tag">${escapeHtml(item.fit_category_label || item.fit_category || "-")}</span></td>
      <td>${item.fit_score ?? "-"}</td>
      <td>${escapeHtml(item.representative_title || "-")}</td>
      <td>${escapeHtml(item.brand || "-")}</td>
      <td>${fmtResearchNum(item.price)}</td>
      <td>${fmtResearchNum(item.rating)}</td>
      <td>${item.review_count ?? "-"}</td>
      <td>${escapeHtml(item.launch_date || "-")}</td>
      <td>${item.monthly_sales ?? "-"}</td>
      <td>${fmtResearchNum(item.monthly_revenue)}</td>
      <td>${item.seller_product_count ?? "-"}</td>
      <td class="research-reason">${escapeHtml(researchReason(item))}</td>
    </tr>`).join("");
  return `
    <table class="research-table research-eligible">
      <thead><tr>
        <th>#</th><th>Seller</th><th>Fit</th><th>Score</th><th>Representative product</th>
        <th>Brand</th><th>Price</th><th>Rating</th><th>Reviews</th><th>Launch</th>
        <th>Mo. sales</th><th>Mo. revenue</th><th>#Products</th><th>Why suitable</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderExcludedTable(items) {
  const rows = items.map((item) => `
    <tr>
      <td>${escapeHtml(item.seller || "-")}</td>
      <td>${escapeHtml(item.representative_title || "-")}</td>
      <td>${item.review_count ?? "-"}</td>
      <td>${item.monthly_sales ?? "-"}</td>
      <td>${escapeHtml((item.exclusion_reasons || []).join("；") || "-")}</td>
    </tr>`).join("");
  return `
    <details class="research-excluded"><summary>${items.length} excluded sellers</summary>
    <table class="research-table">
      <thead><tr><th>Seller</th><th>Product</th><th>Reviews</th><th>Mo. sales</th><th>Excluded because</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></details>`;
}

function researchReason(item) {
  if (item.ai_reason && String(item.ai_reason).trim()) return String(item.ai_reason).trim();
  const reasons = item.fit_reasons || [];
  return reasons.length ? reasons.join("；") : "-";
}

function fmtResearchNum(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  return Number.isFinite(num) ? num.toLocaleString() : "-";
}

function offerLink(item) {
  const label = escapeHtml(item.supplier || "-");
  if (!item.offer_url) return label;
  return `<a href="${escapeAttr(item.offer_url)}" target="_blank" rel="noreferrer">${label}</a>`;
}

function reviewToggle(item) {
  const expanded = state.expandedReviews.has(item.key);
  const status = item.review_status || "review";
  return `
    <button class="review-toggle ${escapeAttr(status)}" data-key="${escapeAttr(item.key)}" type="button">
      <span>${escapeHtml(t(`review.status.${status}`))}</span>
      <strong>${escapeHtml(expanded ? t("review.hide") : t("review.details"))}</strong>
    </button>
  `;
}

function reviewPanel(item) {
  return `
    <div class="review-panel">
      <div class="review-block wide">
        <h3>${escapeHtml(t("review.decisionBrief"))}</h3>
        ${decisionBriefPanel(item.decision_brief)}
      </div>
      <div class="review-block">
        <h3>${escapeHtml(t("review.productSpec"))}</h3>
        ${specGrid(item.product_spec)}
      </div>
      <div class="review-block">
        <h3>${escapeHtml(t("review.supplierSpec"))}</h3>
        ${specGrid(item.top_supplier_spec)}
      </div>
      <div class="review-block wide">
        <h3>${escapeHtml(t("review.parameterComparison"))}</h3>
        ${specComparisonTable(item.spec_comparison || [])}
      </div>
      <div class="review-block">
        <h3>${escapeHtml(t("review.matchEvidence"))}</h3>
        ${issueList(item)}
      </div>
      <div class="review-block">
        <h3>${escapeHtml(t("review.marketEvidence"))}</h3>
        ${marketGrid(item.market)}
      </div>
      <div class="review-block">
        <h3>${escapeHtml(t("review.scoreEvidence"))}</h3>
        ${scorePanel(item)}
      </div>
      <div class="review-block">
        <h3>${escapeHtml(t("review.profitEvidence"))}</h3>
        ${specGrid(item.profit_breakdown)}
      </div>
      <div class="review-block wide">
        <h3>${escapeHtml(t("review.visualEvidence"))}</h3>
        ${visualEvidence(item)}
      </div>
      <div class="review-block wide">
        <h3>${escapeHtml(t("review.candidates"))}</h3>
        ${supplierCandidateTable(item.supplier_candidates || [])}
      </div>
    </div>
  `;
}

function decisionBriefPanel(brief) {
  if (!brief || !brief.action) return `<p class="muted-text">${escapeHtml(t("review.noIssues"))}</p>`;
  const positives = brief.positives || [];
  const risks = brief.risks || [];
  const nextSteps = brief.next_steps || [];
  return `
    <div class="decision-brief">
      <div class="decision-summary">
        <strong>${escapeHtml(tx(`review.action.${brief.action}`, brief.action))}</strong>
        <span>${escapeHtml(tx(`review.confidence.${brief.confidence || "medium"}`, brief.confidence || ""))}</span>
      </div>
      <div class="decision-columns">
        ${decisionSignalColumn("review.positiveSignals", positives, "positive")}
        ${decisionSignalColumn("review.riskSignals", risks, "risk")}
        ${decisionNextSteps(nextSteps)}
      </div>
    </div>
  `;
}

function decisionSignalColumn(titleKey, signals, tone) {
  const items = signals && signals.length
    ? signals.map((signal) => `<li>${escapeHtml(decisionSignalText(signal))}</li>`).join("")
    : `<li>${escapeHtml(t("review.noIssues"))}</li>`;
  return `
    <div class="decision-list ${escapeAttr(tone)}">
      <strong>${escapeHtml(t(titleKey))}</strong>
      <ul>${items}</ul>
    </div>
  `;
}

function decisionNextSteps(steps) {
  const items = steps && steps.length
    ? steps.map((step) => `<li>${escapeHtml(tx(`review.next.${step}`, step))}</li>`).join("")
    : `<li>${escapeHtml(t("review.details"))}</li>`;
  return `
    <div class="decision-list next">
      <strong>${escapeHtml(t("review.nextSteps"))}</strong>
      <ul>${items}</ul>
    </div>
  `;
}

function decisionSignalText(signal) {
  const code = String(signal?.code || "");
  const value = signal?.value;
  let label = code;
  if (code.startsWith("rejection:")) {
    const reason = code.slice("rejection:".length);
    label = `${t("review.signal.rejection")}: ${tx(`review.rejection.${reason}`, reason)}`;
  } else if (code.startsWith("conflict:")) {
    label = `${t("review.signal.conflict")}: ${code.slice("conflict:".length)}`;
  } else if (code.startsWith("missing:")) {
    label = `${t("review.signal.missing")}: ${code.slice("missing:".length)}`;
  } else {
    label = tx(`review.signal.${code}`, code);
  }
  const formatted = decisionSignalValue(code, value);
  return formatted ? `${label} ${formatted}` : label;
}

function decisionSignalValue(code, value) {
  if (value === null || value === undefined || value === "") return "";
  if (code === "supplier_evidence") return sourceLabel(value);
  if (["candidate_score", "match_quality", "spec_match"].includes(code)) return compactPercent(value);
  if (code === "margin") return percent(value);
  if (typeof value === "object") {
    const [key, inner] = Object.entries(value)[0] || [];
    if (!key) return "";
    if (["est_monthly_sales", "search_volume_monthly", "monthly_purchases", "bsr"].includes(key)) {
      return `${tx(`review.metric.${key}`, key)} ${formatInteger(inner)}`;
    }
    return specValue(value);
  }
  if (typeof value === "number") return number(value, 2);
  return String(value);
}

function scorePanel(item) {
  const scoreHtml = specGrid(item.score_breakdown);
  const reasons = item.rejection_reasons || [];
  if (!reasons.length) return scoreHtml;
  return `
    ${scoreHtml}
    <h3 class="subhead">${escapeHtml(t("review.rejectionReasons"))}</h3>
    <div class="issue-list">${reasons.map((reason) => `<span class="conflict">${escapeHtml(reason)}</span>`).join("")}</div>
  `;
}

function marketGrid(market) {
  const entries = Object.entries(market || {});
  if (!entries.length) return `<p class="muted-text">${escapeHtml(t("review.noMarket"))}</p>`;
  return specGrid(market);
}

function specGrid(spec) {
  const entries = Object.entries(spec || {});
  if (!entries.length) return `<p class="muted-text">${escapeHtml(t("review.noSpec"))}</p>`;
  return `
    <dl class="spec-grid">
      ${entries.map(([key, value]) => `
        <div>
          <dt>${escapeHtml(key)}</dt>
          <dd>${escapeHtml(specValue(value))}</dd>
        </div>
      `).join("")}
    </dl>
  `;
}

function specComparisonTable(rows) {
  if (!rows.length) return `<p class="muted-text">${escapeHtml(t("review.noSpec"))}</p>`;
  return `
    <div class="spec-comparison">
      <div class="spec-comparison-row header">
        <strong>${escapeHtml(t("review.field"))}</strong>
        <small>${escapeHtml(t("table.status"))}</small>
        <span>${escapeHtml(t("review.targetValue"))}</span>
        <span>${escapeHtml(t("review.supplierValue"))}</span>
      </div>
      ${rows.map((row) => `
        <div class="spec-comparison-row ${escapeAttr(row.status || "unknown")}">
          <strong>${escapeHtml(row.field || row.match_key || "-")}</strong>
          <small>${escapeHtml(specComparisonStatusLabel(row.status))}</small>
          <span>${escapeHtml(specValue(row.target))}</span>
          <span>${escapeHtml(specValue(row.supplier))}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function specComparisonStatusLabel(status) {
  const value = status || "unknown";
  return t(`review.status.${value}`) || value;
}

function issueList(item) {
  const matched = item.spec_match_matched || [];
  const missing = item.spec_match_missing || [];
  const conflicts = item.spec_match_conflicts || [];
  if (!matched.length && !missing.length && !conflicts.length) {
    return `<p class="muted-text">${escapeHtml(t("review.noIssues"))}</p>`;
  }
  return `
    <div class="issue-list">
      ${matched.map((v) => `<span class="ok">${escapeHtml(v)}</span>`).join("")}
      ${missing.map((v) => `<span class="missing">${escapeHtml(v)}</span>`).join("")}
      ${conflicts.map((v) => `<span class="conflict">${escapeHtml(v)}</span>`).join("")}
    </div>
  `;
}

function visualEvidence(item) {
  const candidates = (item.supplier_candidates || []).slice(0, 3);
  return `
    <div class="visual-strip">
      ${visualTile({
        label: t("review.targetImage"),
        title: item.title || item.asin || "-",
        imageUrl: item.image,
        matchScore: null,
        visualScore: null,
        href: item.amazon_url || null,
        isTarget: true,
      })}
      ${candidates.map((candidate) => {
        return visualTile({
          label: `#${candidate.rank ?? "-"}`,
          title: candidate.title || candidate.supplier || "-",
          imageUrl: candidate.offer_image_url,
          matchScore: candidate.match_quality,
          visualScore: candidate.visual_similarity ?? candidate.visual_match?.score,
          href: candidate.offer_url,
          isTarget: false,
        });
      }).join("")}
    </div>
  `;
}

function visualTile({ label, title, imageUrl, matchScore, visualScore, href, isTarget }) {
  const visualScoreText = visualScore === null || visualScore === undefined ? "" : `${t("review.visualScore")} ${Math.round(Number(visualScore) * 100)}%`;
  const matchScoreText = matchScore === null || matchScore === undefined ? "" : `${t("review.matchScore")} ${Math.round(Number(matchScore) * 100)}%`;
  const scoreText = [visualScoreText, matchScoreText].filter(Boolean).join(" · ");
  const image = imageUrl
    ? `<div class="visual-placeholder visual-loading">${escapeHtml(t("review.loadingImage"))}</div><img src="${escapeAttr(imageUrl)}" alt="${escapeAttr(title)}" loading="lazy">`
    : `<div class="visual-placeholder">${escapeHtml(t("review.noImage"))}</div>`;
  const body = `
    <div class="visual-frame ${isTarget ? "target" : ""}">${image}</div>
    <div class="visual-meta">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(title)}</span>
      ${scoreText ? `<small>${escapeHtml(scoreText)}</small>` : ""}
    </div>
  `;
  if (!href) return `<div class="visual-tile">${body}</div>`;
  return `<a class="visual-tile" href="${escapeAttr(href)}" target="_blank" rel="noreferrer">${body}</a>`;
}

function bindImageFallbacks() {
  $$(".visual-frame img").forEach((img) => {
    if (img.dataset.fallbackBound === "true") return;
    img.dataset.fallbackBound = "true";
    const frame = img.closest(".visual-frame");
    const markLoaded = () => frame?.classList.add("loaded");
    const markUnavailable = () => {
      if (!img.isConnected || !frame) return;
      const placeholder = document.createElement("div");
      placeholder.className = "visual-placeholder";
      placeholder.textContent = t("review.noImage");
      frame.innerHTML = "";
      frame.appendChild(placeholder);
    };
    img.addEventListener("load", markLoaded, { once: true });
    img.addEventListener("error", markUnavailable, { once: true });
    if (img.complete) {
      if (img.naturalWidth > 0) {
        markLoaded();
      } else {
        markUnavailable();
      }
    }
    window.setTimeout(() => {
      if (img.isConnected && !img.complete) markUnavailable();
    }, 10000);
  });
}

function supplierCandidateTable(candidates) {
  if (!candidates.length) return `<p class="muted-text">${escapeHtml(t("review.noSpec"))}</p>`;
  return `
    <div class="candidate-strip">
      ${candidates.map((candidate) => {
        const score = candidate.spec_match?.score ?? candidate.match_quality;
        const status = candidate.review_status || "pending";
        const verdict = supplierCandidateVerdict(candidate);
        const issues = [
          ...(candidate.spec_match?.conflicts || []),
          ...(candidate.spec_match?.missing || []),
        ].slice(0, 3);
        return `
          <div class="candidate-card ${escapeAttr(status)}">
            <div class="candidate-card-head">
              <strong>#${escapeHtml(candidate.rank)} ${escapeHtml(candidate.supplier || "-")}</strong>
              <span class="candidate-review-pill ${escapeAttr(status)}">${escapeHtml(reviewDecisionLabel(status))}</span>
            </div>
            <span>${escapeHtml(candidate.title || "-")}</span>
            <div class="candidate-verdict ${escapeAttr(verdict.tone)}">
              <strong>${escapeHtml(verdict.label)}</strong>
              <span>${escapeHtml(verdict.detail)}</span>
            </div>
            <div class="candidate-quality">${supplierQualityPills(candidate)}</div>
            <div class="candidate-evidence">${supplierCandidateEvidence(candidate)}</div>
            ${supplierCandidateSpecSummary(candidate)}
            <small>${supplierCandidateMetrics(candidate, score)}</small>
            ${issues.length ? `<em>${escapeHtml(issues.join(", "))}</em>` : ""}
            <div class="candidate-actions">
              ${candidate.offer_url ? `<a href="${escapeAttr(candidate.offer_url)}" target="_blank" rel="noreferrer">${escapeHtml(t("review.details"))}</a>` : ""}
              <button class="supplier-review-action accept" type="button" data-review-key="${escapeAttr(candidate.review_key)}" data-status="accepted">${escapeHtml(t("review.accept"))}</button>
              <button class="supplier-review-action reject" type="button" data-review-key="${escapeAttr(candidate.review_key)}" data-status="rejected">${escapeHtml(t("review.reject"))}</button>
              ${status !== "pending" ? `<button class="supplier-review-action pending" type="button" data-review-key="${escapeAttr(candidate.review_key)}" data-status="pending">${escapeHtml(t("review.pending"))}</button>` : ""}
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function supplierCandidateVerdict(candidate) {
  const matchScore = numericOrNull(candidate.match_quality);
  const specScore = numericOrNull(candidate.spec_match?.score);
  const rankScore = numericOrNull(candidate.rank_score);
  const candidateScore = numericOrNull(candidate.candidate_score);
  const profitMargin = numericOrNull(candidate.profit_margin);
  const conflicts = candidate.spec_match?.conflicts || [];
  const missing = candidate.spec_match?.missing || [];
  const method = String(candidate.verification_method || "").toLowerCase();

  if (method === "heuristic_rejected" || conflicts.length || (matchScore !== null && matchScore < 0.4)) {
    return {
      tone: "reject",
      label: t("review.verdict.reject"),
      detail: conflicts.length
        ? `${t("match.conflict")} ${conflicts.slice(0, 2).join(", ")}`
        : t("review.reason.rejected"),
    };
  }
  if (
    (rankScore !== null && rankScore >= 0.62)
    || (candidateScore !== null && candidateScore >= 0.6)
    || (matchScore !== null && matchScore >= 0.55 && specScore !== null && specScore >= 0.75)
  ) {
    return {
      tone: "recommend",
      label: t("review.verdict.recommend"),
      detail: [
        matchScore === null ? "" : `${t("review.reason.match")} ${compactPercent(matchScore)}`,
        specScore === null ? "" : `${t("review.reason.spec")} ${compactPercent(specScore)}`,
        profitMargin === null ? "" : `${t("review.reason.profit")} ${percent(profitMargin)}`,
      ].filter(Boolean).join(" · "),
    };
  }
  if (missing.length || specScore !== null) {
    return {
      tone: "verify",
      label: t("review.verdict.verify"),
      detail: missing.length ? `${t("match.missing")} ${missing.slice(0, 2).join(", ")}` : `${t("review.reason.spec")} ${compactPercent(specScore)}`,
    };
  }
  return {
    tone: "review",
    label: t("review.verdict.review"),
    detail: candidate.sourcing_source ? sourceLabel(candidate.sourcing_source) : "",
  };
}

function supplierCandidateEvidence(candidate) {
  const chips = [];
  const matchScore = numericOrNull(candidate.match_quality);
  const specScore = numericOrNull(candidate.spec_match?.score);
  const candidateScore = numericOrNull(candidate.candidate_score);
  const rankScore = numericOrNull(candidate.rank_score);
  const profitMargin = numericOrNull(candidate.profit_margin);
  const monthlySales = numericOrNull(candidate.monthly_sales);
  const repeatRate = numericOrNull(candidate.repeat_buyer_rate);
  if (matchScore !== null) {
    chips.push(evidenceChip("match", `${t("review.reason.match")} ${compactPercent(matchScore)}`));
  }
  if (specScore !== null) {
    chips.push(evidenceChip(candidate.spec_match?.conflicts?.length ? "risk" : "spec", `${t("review.reason.spec")} ${compactPercent(specScore)}`));
  }
  if (candidateScore !== null) {
    chips.push(evidenceChip("score", `${t("review.reason.candidate")} ${compactPercent(candidateScore)}`));
  }
  if (rankScore !== null) {
    chips.push(evidenceChip("score", `${t("review.reason.rank")} ${compactPercent(rankScore)}`));
  }
  if (profitMargin !== null) {
    chips.push(evidenceChip(profitMargin >= 0.2 ? "profit" : "risk", `${t("review.reason.profit")} ${percent(profitMargin)}`));
  }
  if (monthlySales !== null && monthlySales >= 1000) {
    chips.push(evidenceChip("business", `${t("review.reason.highSales")} ${formatInteger(monthlySales)}`));
  }
  if (repeatRate !== null && repeatRate >= 0.3) {
    chips.push(evidenceChip("business", `${t("review.reason.repeat")} ${compactPercent(repeatRate)}`));
  }
  if (candidate.verification_method === "heuristic_rejected") {
    chips.push(evidenceChip("risk", t("review.reason.rejected")));
  }
  return chips.join("");
}

function evidenceChip(tone, label) {
  return `<span class="evidence-chip ${escapeAttr(tone)}">${escapeHtml(label)}</span>`;
}

function supplierCandidateSpecSummary(candidate) {
  const matched = candidate.spec_match?.matched || [];
  const missing = candidate.spec_match?.missing || [];
  const conflicts = candidate.spec_match?.conflicts || [];
  if (!matched.length && !missing.length && !conflicts.length) return "";
  const parts = [
    matched.length ? `<span class="ok">${escapeHtml(t("match.ok"))}: ${escapeHtml(matched.slice(0, 4).join(", "))}</span>` : "",
    missing.length ? `<span class="missing">${escapeHtml(t("match.missing"))}: ${escapeHtml(missing.slice(0, 4).join(", "))}</span>` : "",
    conflicts.length ? `<span class="conflict">${escapeHtml(t("match.conflict"))}: ${escapeHtml(conflicts.slice(0, 4).join(", "))}</span>` : "",
  ].filter(Boolean).join("");
  return `<div class="candidate-spec-summary">${parts}</div>`;
}

function supplierQualityPills(candidate) {
  const pills = [];
  if (candidate.sourcing_source) {
    pills.push(`<span class="quality-tag source">${escapeHtml(t("review.source"))} ${escapeHtml(sourceLabel(candidate.sourcing_source))}</span>`);
  }
  if (candidate.is_factory === true) {
    pills.push(`<span class="quality-tag factory">${escapeHtml(t("review.factory"))}</span>`);
  } else if (candidate.is_factory === false) {
    pills.push(`<span class="quality-tag trader">${escapeHtml(t("review.trader"))}</span>`);
  }
  if (candidate.monthly_sales !== null && candidate.monthly_sales !== undefined) {
    pills.push(`<span class="quality-tag">${escapeHtml(t("review.monthlySales"))} ${escapeHtml(formatInteger(candidate.monthly_sales))}</span>`);
  }
  if (candidate.repeat_buyer_rate !== null && candidate.repeat_buyer_rate !== undefined) {
    pills.push(`<span class="quality-tag">${escapeHtml(t("review.repeatRate"))} ${escapeHtml(compactPercent(candidate.repeat_buyer_rate))}</span>`);
  }
  return pills.join("");
}

function sourceLabel(source) {
  const value = String(source || "");
  const labels = {
    alibaba_pifatuan: "Open API",
    alibaba_import: "Imported",
    alibaba_text_search: "Text API",
    alibaba_playwright: "Playwright",
    alibaba_scrapling: "Scrapling",
    sellersprite_1688: "SellerSprite 1688",
    mock: "Mock",
    unknown: "Unknown",
  };
  return labels[value] || value;
}

function supplierCandidateMetrics(candidate, score) {
  const parts = [
    money(candidate.price_cny, "¥"),
    `MOQ ${candidate.moq ?? "-"}`,
    score === null || score === undefined ? "" : `${t("review.matchScore")} ${Math.round(Number(score) * 100)}%`,
    candidate.rank_score === null || candidate.rank_score === undefined ? "" : `${t("review.reason.rank")} ${Math.round(Number(candidate.rank_score) * 100)}%`,
    candidate.profit_margin === null || candidate.profit_margin === undefined ? "" : `${t("review.reason.profit")} ${percent(candidate.profit_margin)}`,
    candidate.net_profit === null || candidate.net_profit === undefined ? "" : `${t("review.profitEvidence")} ${money(candidate.net_profit, "$")}`,
    candidate.visual_similarity === null || candidate.visual_similarity === undefined ? "" : `${t("review.visualScore")} ${Math.round(Number(candidate.visual_similarity) * 100)}%`,
    candidate.candidate_score === null || candidate.candidate_score === undefined ? "" : `${t("review.candidateScore")} ${Math.round(Number(candidate.candidate_score) * 100)}%`,
    candidate.supplier_quality_score === null || candidate.supplier_quality_score === undefined ? "" : `${t("review.supplierQuality")} ${Math.round(Number(candidate.supplier_quality_score) * 100)}%`,
  ].filter(Boolean);
  return escapeHtml(parts.join(" · "));
}

function reviewDecisionLabel(status) {
  if (status === "accepted") return t("review.accepted");
  if (status === "rejected") return t("review.rejected");
  return t("review.pending");
}

function updateSupplierReviewState(reviewKey, status) {
  for (const item of state.results) {
    for (const candidate of item.supplier_candidates || []) {
      if (candidate.review_key === reviewKey) {
        candidate.review_status = status;
        candidate.review_note = "";
      }
    }
    item.supplier_review_summary = summarizeSupplierReviews(item.supplier_candidates || []);
  }
}

function summarizeSupplierReviews(candidates) {
  const summary = { accepted: 0, rejected: 0, pending: 0 };
  for (const candidate of candidates) {
    const status = candidate.review_status || "pending";
    if (status in summary) summary[status] += 1;
  }
  return summary;
}

function specValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return value ?? "-";
}

function matchPill(item) {
  const value = item.spec_match_score ?? item.match_quality;
  if (value === null || value === undefined || value === "") return "-";
  const conflicts = item.spec_match_conflicts || [];
  const missing = item.spec_match_missing || [];
  const matched = item.spec_match_matched || [];
  const title = [
    matched.length ? `${state.lang === "zh" ? "匹配" : "Matched"}: ${matched.join(", ")}` : "",
    missing.length ? `${state.lang === "zh" ? "缺失" : "Missing"}: ${missing.join(", ")}` : "",
    conflicts.length ? `${state.lang === "zh" ? "冲突" : "Conflicts"}: ${conflicts.join(", ")}` : "",
  ].filter(Boolean).join(" | ");
  const pct = Math.round(Number(value) * 100);
  const cls = conflicts.length ? "warn" : pct >= 75 ? "ok" : "muted";
  const summary = [
    matched.length ? `<span>${matched.length} ${escapeHtml(t("match.ok"))}</span>` : "",
    missing.length ? `<span>${missing.length} ${escapeHtml(t("match.missing"))}</span>` : "",
    conflicts.length ? `<span>${conflicts.length} ${escapeHtml(t("match.conflict"))}</span>` : "",
  ].filter(Boolean).join("");
  return `
    <div class="match-cell" title="${escapeAttr(title)}">
      <span class="match-pill ${cls}">${pct}%</span>
      ${summary ? `<span class="match-summary">${summary}</span>` : ""}
    </div>
  `;
}

function money(value, prefix = "$") {
  if (value === null || value === undefined || value === "") return "-";
  return `${prefix}${Number(value).toFixed(2)}`;
}

function percent(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function compactPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatInteger(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value ?? "-");
  return Math.round(numeric).toLocaleString();
}

function number(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toFixed(digits);
}

function numericOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
