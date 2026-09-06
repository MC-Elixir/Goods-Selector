# AGENTS.md

本文件只规定 Amazon Selector 的项目不变量；跨项目开发行为由全局 AGENTS 管理。
`agent/runner.py` 的提示词及 `deployment/hermes/amazon-selector-profile/SOUL.md`
是产品运行时规则，不是开发助手的工具或工作范围限制。

## 架构与正式数据路径

- 正式流程：Amazon US 类目/关键词采集 → 逐 ASIN 卖家精灵市场证据 →
  卖家精灵插件“1688 找货” → 详情取证与验证 → 确定性利润、评分、筛选 → 导出。
  Amazon crawler 不可被预制 `seed_products` 绕过；其他 matcher 可用于隔离诊断，
  不得成为正式候选发现的回退来源。对插件返回的 offer URL 补全详情不属于更换来源。
- `pipeline/orchestrator.py::run_pipeline` 是兼容入口，实际委托给
  `pipeline/recoverable.py`；`execution/` 管理节点状态、租约和产物提交。
  修改编排时同时检查这三处，不要只改文件中保留的旧线性实现。
- 采集、匹配和分析之间传递 DTO / schema，不传递 ORM 实体。业务持久化由编排与
  repository 层负责；`matchers/sourcing_slice.py` 的既有证据持久化是局部例外，
  不应扩散成通用 matcher 的数据库依赖。普通 ORM 访问使用 `db/session.py::session_scope()`；
  迁移、证据和执行层已有的显式事务边界应保留。
- `agent/sellersprite_*.py` 管理独立的浏览器导出、导入、额度及人工介入流程，
  正式流水线消费其逐 ASIN 证据。`MJJL_MAX_PRODUCTS_PER_RUN` 为正时覆盖所有采集商品，
  不再按该数值截断；零只用于显式离线诊断。

## 证据、评分与数据兼容

- 正式 No-Mock 不允许 mock 供应商进入候选、持久化结果或导出；登录/验证码拦截页
  不能解析为商品证据。供应商发现来源和详情证据来源须可追溯。
- 品类合同与结构化证据边界在 `domain/target_categories.py`、`schemas/sourcing.py`
  和 `matchers/match_evidence.py`。保留规格冲突、整品/配件关系、厂家证据和人工复核判定；
  缺少关键成本或市场证据不能补成零、默认可信值或强推荐。真实零与未知值必须区分。
- 成本参数与评分规则分别由 `config/profit_params.yaml`、`config/scoring_weights.yaml`
  驱动；保持配置缓存的 `reload_*()` 行为。评分权重之和必须为 1.0。
  硬筛选先于排名，淘汰结果仍保留 `passed_hard_filter=False` 及原因。
- `ProfitSnapshot` / `Score` 追加保存，并携带当次 `params_snapshot` / `weights_snapshot`；
  不覆盖历史决策。数据库升级走 `db/migrate.py` 与 `db/migrations/` 的版本化增量迁移，
  保持旧库数据、幂等升级、失败回滚及 SQLite 外键约束；不能仅靠 ORM `create_all` 绕过迁移。
- 正式交付为一个 Excel，包含 `运行摘要`、`Amazon商品`、`卖家精灵市场数据`、
  `Amazon×1688完整匹配`、`未通过及待核验`；JSON 是后台机器数据，Markdown 是兼容工具。
  导出和历史读取需保留通过、拒绝及待核验的区分；呈现候选前审计导出证据。

## 产品运行时状态与恢复

以下状态均指产品任务或执行节点，不表示开发助手应停止整个开发任务。

- 启动正式选品前必须通过 preflight，并确认正式路径所需的卖家精灵插件就绪。
  Amazon 发现阶段未成功时不能进入下游。后续错误按 `execution/models.py` 和
  `execution/policies.py` 分类，不使用“除第一阶段外全部忽略并继续”的概括。
  `human_required`、`retry_wait` 等屏障必须保留；1688 受阻时不在整批 ASIN 上重复触发。
- 登录、验证码、权限或额度问题通过 `HumanActionRequired` 和人工处理路径表达，
  不能降级成“无供应商”或切换来源。人工处理后恢复原 `run_id`，保留已完成的 ASIN 节点。
- 节点恢复保留输入指纹、generation、租约及恢复令牌校验：有效成功结果默认复用，
  输入变化或显式重跑使相关下游失效，旧 worker 不得提交。强制重跑须留下原因和尝试历史。
- 业务结果与节点成功状态必须在同一事务提交。导出通过 `execution/artifacts.py`
  完成整组文件发布、校验与对账；缺失或部分产物不能算作导出成功。
- Hermes / MCP 产品写操作保留明确同意与 `confirm=true` 门禁；同一请求重试沿用
  持久化 `request_id`。保持 Bearer 鉴权、精确工具白名单，以及不外泄 Cookie、密钥、
  恢复令牌的响应边界；规则详见 profile 与 `selector_mcp/`，不以工具数量代替契约。

## 项目验证门禁

按改动范围使用 [.agents/skills/goods-selector-validation/SKILL.md](.agents/skills/goods-selector-validation/SKILL.md) 中对应的回归门禁；完整 CI 以 `.github/workflows/ci.yml` 为准。
`CODEOWNERS` 保护的三个核心文件修改仍须有对应测试改动并在合并前通过审阅。
普通检查使用隔离数据；真实浏览器测试与正式业务运行须在授权范围内，不能用离线检查替代。

## 部署验收边界

- 正式 WebUI 运行于 Compose 的 `amazon-selector`；本地 Python 只作调试备用。
  Hermes 与 `assistant` profile 下的 MCP 为可选能力，不是普通 WebUI 启动前提。
  入口、地址和环境值从 `docker-compose.yml`、`config/settings.py`、`.env.example`
  及 `start.ps1` 发现；浏览器辅助环境按 Dockerfile 与主依赖隔离。
- WebUI 与专用 Chrome 默认仅本机访问；不能为解决容器连接问题将 Chrome 改成监听所有网卡。
  CDP 必须从实际调用环境验证，Windows 宿主可访问不等于容器可访问。
- 分别验收 WebUI HTTP、容器内 CDP、preflight 与卖家精灵插件就绪。
  启用 MCP 时再验证未认证拒绝、认证初始化及当前白名单。
  服务可用不等于正式选品可用；真实业务验收还需获授权的任务完成并生成真实证据工作簿。

## 详细资料入口

- `ARCHITECTURE.md`：正式数据流；`docs/PRD.md`：需求与历史设计背景。
- `docs/scoring_spec.md`、`docs/database_schema.md`：评分与数据设计细节。
- `docs/DEPLOYMENT.md`、`docs/ZERO_TO_RUN.md`：部署操作与验收流程。
- `deployment/hermes/amazon-selector-profile/README.md`：可选客户端契约与部署。
- `docs/UI_DESIGN.md`：仅 `webui/` 的视觉规范。

部署或验收时使用 [.agents/skills/goods-selector-deployment/SKILL.md](.agents/skills/goods-selector-deployment/SKILL.md)；其他资料按改动涉及的领域读取。
旧入口文档中的线性失败策略、通用 matcher 回退链和“仅 create_all”说明，
不能覆盖上述可恢复、来源受限及版本化迁移约束。
