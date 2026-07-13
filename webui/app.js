const state = {
  preflight: null,
  categories: [],
  jobs: [],
  runs: [],
  results: [],
  manualQueue: [],
  importedSuppliers: [],
  configStatus: null,
  reviewFilter: "all",
  expandedReviews: new Set(),
  selectedAsin: "",
  activeSection: "run",
  sellerSpriteKeywordRows: [],
  lang: localStorage.getItem("agentLang") || "en",
};

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
    "nav.run": "Run Agent",
    "nav.settings": "Settings",
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
    "settings.capability.sellerSprite": "SellerSprite market data",
    "settings.capability.vision": "Vision model",
    "settings.configured": "Configured",
    "settings.disabled": "Disabled",
    "settings.enabled": "Enabled",
    "settings.missing": "Missing",
    "settings.promptTitle": "Runtime Prompt",
    "settings.saveSellerSprite": "Save SellerSprite",
    "settings.sellerSpriteBase": "API base",
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
    "nav.run": "运行 Agent",
    "nav.settings": "设置",
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
    "settings.capability.sellerSprite": "卖家精灵市场数据",
    "settings.capability.vision": "视觉模型",
    "settings.configured": "已配置",
    "settings.disabled": "已关闭",
    "settings.enabled": "已启用",
    "settings.missing": "缺失",
    "settings.promptTitle": "运行提示词",
    "settings.saveSellerSprite": "保存卖家精灵",
    "settings.sellerSpriteBase": "API 地址",
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
    seller_sprite: "卖家精灵 API Key 已配置",
  },
};

const JOB_MESSAGE_LABELS = {
  zh: {
    "No candidates passed filters": "无候选通过筛选",
    "No candidates passed hard filters; no export was generated": "无候选通过硬筛选，未生成正式候选导出",
    "Cancellation requested": "取消中",
    "Cancelled before start": "启动前已取消",
    "Cancelled before pipeline": "进入流水线前已取消",
    "Cancelled after pipeline": "流水线结束后已取消",
    "Run cancelled": "已取消",
    "Supplier evidence missing": "缺少真实货源证据",
    "Real supplier match evidence required but missing from export": "导出中缺少真实 1688 货源匹配证据",
    "Market data missing": "缺少市场数据",
    "SellerSprite rich market data required but missing from export": "导出中缺少卖家精灵富市场数据",
  },
  en: {},
};

document.addEventListener("DOMContentLoaded", () => {
  applyLanguage();
  bindNavigation();
  bindActions();
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
      $("#runSection").style.display = state.activeSection === "run" ? "grid" : "none";
      $("#resultsSection").style.display = state.activeSection === "settings" ? "none" : "grid";
      $("#settingsSection").style.display = state.activeSection === "settings" ? "block" : "none";
    });
  });
}

function bindActions() {
  $("#languageButton").addEventListener("click", toggleLanguage);
  $("#refreshButton").addEventListener("click", refreshAll);
  $("#loadRunsButton").addEventListener("click", refreshRuns);
  $("#reloadResultsButton").addEventListener("click", refreshResults);
  $("#runButton").addEventListener("click", startRun);
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
  $("#chatForm").addEventListener("submit", sendChatMessage);
}

async function refreshAll() {
  await Promise.all([
    refreshCategories(),
    refreshPreflight(),
    refreshConfigStatus(),
    refreshJobs(),
    refreshRuns(),
    refreshPrompt(),
    refreshManualQueue(),
    refreshImportedSuppliers(),
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

async function refreshJobs() {
  const data = await getJson("/api/jobs");
  state.jobs = data.jobs || [];
  renderJobs();
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
    submitButton.disabled = false;
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
  if (errorCode === "EXTENSION_UNAVAILABLE") return t("sellersprite.reverseKeywords.disabled");
  if (errorCode === "CANCELLED") return t("sellersprite.reverseKeywords.cancelled");
  if (result?.status === "NEEDS_HUMAN") return t("sellersprite.reverseKeywords.needsHuman");
  return t("sellersprite.reverseKeywords.failed");
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
  const select = $("#categorySelect");
  if (!select || !state.categories.length) return;
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
  updateRunAvailability();
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
    row.innerHTML = `
      <span class="job-dot"></span>
      <div>
        <strong>${escapeHtml(statusLabel(job.status).toUpperCase())} · ${escapeHtml(jobMessageLabel(job.message || ""))}</strong>
        <span>${escapeHtml(meta)}${job.queue_position ? ` · #${Number(job.queue_position)}` : ""}${job.error ? ` · ${escapeHtml(jobMessageLabel(job.error))}` : ""}</span>
        ${summary}
        ${events}
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
  if (job.status === "failed" || job.status === "cancelled") {
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
  if (!status?.configured) return status?.env || "MJJL_API_KEY";
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
