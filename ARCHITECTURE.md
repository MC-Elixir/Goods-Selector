# Architecture

Amazon Selector 是一个面向 B2B 外贸的 Amazon 选品自动化系统，采用 7 阶段线性管线架构。

## 系统数据流

```
用户输入 (category, limit, marketplace)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  pipeline/orchestrator.py :: run_pipeline()                      │
│                                                                   │
│  Stage 1: crawlers/     Amazon BSR 爬取      → ProductDTO[]      │
│  Stage 2: matchers/     1688 供应商匹配      → SupplierDTO[]     │
│  Stage 3: analyzers/    利润预测             → ProfitBreakdown    │
│  Stage 4: analyzers/    市场分析             → MarketAnalysisDTO  │
│  Stage 5: analyzers/    综合评分             → ScoreBreakdown     │
│  Stage 6: pipeline/     硬门禁 + 排序        → PipelineRecord[]  │
│  Stage 7: reports/      导出                 → Excel/MD/JSON      │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
data/exports/candidates_*.json + Excel
```

## 核心模块

### crawlers/

Amazon Best Sellers 数据采集层。支持四种后端自动切换：

- `amazon_scrapling.py` — 默认后端（Scrapling StealthySession，无需 API key）
- `amazon_playwright.py` — Playwright 浏览器兜底
- `amazon_keepa.py` — Keepa API（需 `KEEPA_API_KEY`）
- `amazon_rainforest.py` — Rainforest API（需 `RAINFOREST_API_KEY`）

输出 `ProductDTO` dataclass，不接触 ORM。

### matchers/

1688 供应商匹配层。多路径级联：

- `vision_analyzer.py` — LLM 视觉分析生成中文搜索关键词
- `alibaba_playwright.py` — 主路径（Playwright + 注入 cookies）
- `alibaba_text_search.py` — 官方 API（已弃用）
- `alibaba_scrapling.py` — HTTP 路径（默认禁用，被 TMD 拦截）
- `verifier.py` — 启发式过滤 + 可选 LLM 视觉验证

输出 `SupplierDTO` dataclass。模块级单例复用浏览器会话。

### analyzers/

数据分析层，包含三个独立分析器：

- `profit_model.py` — 利润模型（FBA 费用、佣金、广告、退货）
- `maijiajingling.py` — 买家精灵市场分析 API
- `scorer.py` — 6 维评分 + 硬门禁过滤

评分权重来自 `config/scoring_weights.yaml`，**权重和必须为 1.0**。

### pipeline/

管线编排层：

- `orchestrator.py` — 7 阶段调度、RunLog 生命周期、失败策略
- `filters.py` — 硬门禁过滤 + 总分排序
- `recoverable.py` — 可恢复执行（中断续跑）

Stage 1 失败中止整个运行；其余阶段 per-product 失败继续。

### db/

数据持久层（SQLAlchemy + SQLite）：

- `models.py` — 6 个 ORM 模型：Product, Supplier, ProfitSnapshot, Score, MarketAnalysis, RunLog
- `session.py` — `session_scope()` 上下文管理器（auto-commit/rollback）
- `migrate.py` — 版本化迁移（upgrade-only）

**快照模式**：ProfitSnapshot/Score 为 append-only，携带参数快照 JSON。

### execution/

ASIN 级可恢复执行协调：

- `coordinator.py` — 执行协调器
- `models.py` — LeaseLost 等执行异常
- `policies.py` — 重试/跳过策略
- `repository.py` — 执行状态持久化

### agent/

本地 Agent WebUI 层：

- `server.py` — ThreadingHTTPServer + JSON API + 静态资源
- `runner.py` — AgentRuntime（preflight → pipeline → audit）
- `preflight.py` — 环境自检（API keys, cookies, DB, cooldown）
- `history.py` — 历史导出读取 + 保存选品

### config/

配置系统：

- `settings.py` — pydantic-settings 单例，读取 `.env`
- `profit_params.yaml` — 成本费率参数
- `scoring_weights.yaml` — 评分权重和曲线参数

YAML 文件支持热加载（`reload_*()`），无需重启。

## 模块依赖关系

```
config/ ─────────────────────────────────────────────┐
    │                                                 │
    ▼                                                 ▼
crawlers/ ──→ pipeline/ ──→ reports/          agent/ (WebUI)
    │              │                              │
    ▼              ▼                              ▼
matchers/ ──→ analyzers/                    db/ (ORM)
    │              │                              ▲
    └──────────────┴──────────────────────────────┘
                    db/ (ORM)
```

**关键约束**：
- crawlers/matchers/analyzers 只产出 DTO dataclass，不导入 SQLAlchemy
- ORM 写入仅发生在 pipeline/orchestrator 每阶段结束时
- agent/ 包装 pipeline 而非替代它
- execution/ 提供 ASIN 级状态机，独立于 pipeline 线性流

## 辅助模块

| 模块 | 职责 |
|------|------|
| `domain/` | 目标品类合同（品类参数归一化 + 硬门禁） |
| `schemas/` | 选品 DTO schema 定义 |
| `reports/` | Excel/Markdown/JSON 多格式导出 |
| `benchmarks/` | 评估脚本和基准 fixture |
| `webui/` | 静态前端（HTML/CSS/JS，无框架） |

## 文档索引

- `docs/PRD.md` — 产品需求与模块规格
- `docs/scoring_spec.md` — 评分公式与阈值说明
- `docs/database_schema.md` — 数据库设计理由
- `docs/DEPLOYMENT.md` — Docker 部署指南
- `docs/UI_DESIGN.md` — WebUI 设计令牌（Linear 暗色主题）
