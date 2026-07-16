# SellerSprite CDP 市场分析中心设计

日期：2026-07-16
状态：已确认设计，待书面规格审阅

## 1. 目标

将 SellerSprite 浏览器插件从独立的关键词反查工具升级为 Amazon Selector 的市场分析主数据源，并完成 3-ASIN 小批量 no-mock 自动化全流程。

首批范围包括：

1. Product Data 批量采集；
2. Reverse ASIN 关键词反查；
3. Market Analysis Excel 导出；
4. 统一导入 SQLite；
5. 从每个 ASIN 选择最多 5 个真实流量词，生成有来源约束的中文采购词；
6. 使用现有 1688 Playwright 搜索和验证供应商；
7. 继续利润、评分、筛选和原子导出；
8. 复用 ASIN 级可恢复执行基础设施处理重试、人工介入、取消和进程恢复。

SellerSprite 浏览器插件是默认且唯一的自动市场数据路径。现有 SellerSprite API key、客户端和配置界面保留，但默认不调用，只作为人工启用的兼容回退。

1688 开放平台 API 不再使用。删除其运行代码、配置、preflight、CLI/WebUI 检查入口和专用测试；历史数据库和导出中的 `alibaba_pifatuan` 来源值继续可读。

## 2. 首批明确不包含

以下能力后续分别接入，不阻塞首批小批量全流程：

- Keepa 历史；
- Variation 分析；
- Review 下载与评论分析；
- 主图、A+ 和评论图片下载；
- Index Checker；
- SellerSprite 收藏夹；
- 1688 图片搜索、淘宝搜索和 Google Lens；
- 自由循环扩展到 100–300 ASIN；
- 插件私有接口、网络请求或内部鉴权协议逆向。

首批为后续能力保留受控 workflow registry，但不创建语义虚假的执行节点。

## 3. 数据源与运行边界

### 3.1 数据源优先级

- Amazon BSR/关键词采集继续负责发现初始 ASIN 和保存原始 Amazon 快照。
- SellerSprite 浏览器插件负责 Product Data、Reverse ASIN 和 Market Analysis。
- SellerSprite API 默认关闭；只有人工显式启用兼容回退时才允许调用。
- 供应商匹配只使用 1688 Playwright，不调用 1688 开放平台 API。
- no-mock 模式禁止任何 mock 供应商进入正式结果。

### 3.2 自动化边界

允许人工处理：

- 首次启动带 remote debugging 的 Chrome；
- 安装或登录 SellerSprite 插件；
- 自然出现的验证码、权限或配额问题。

必须自动完成：

- 选择正确 Amazon 页面；
- 打开并等待插件面板；
- 点击功能、填写 ASIN 或关键词；
- 等待结果；
- 触发导出并控制下载目录；
- 校验、导入和持久化文件；
- 恢复原 Run；
- 继续 1688 搜索、利润、评分、筛选和最终导出。

除明确的人工阻塞外，真实小批量验收期间不允许依赖手动插件点击。

## 4. 可恢复调用链

```text
AgentRuntime / CLI / WebUI
  -> run_pipeline compatibility entry
  -> run:source_discovery
  -> asin:ingest
  -> asin:sellersprite_product
  -> asin:sellersprite_reverse_asin
  -> asin:match
       -> selected English traffic terms
       -> constrained Chinese sourcing translations
       -> 1688 Playwright searches
  -> asin:profit
  -> asin:sellersprite_market
  -> asin:score
  -> run:filter
  -> run:export
```

执行继续使用阶段屏障：`pending`、`running` 和 `retry_wait` 节点未结束时不得提前推进下一阶段。`human_required` 或确定性失败的 ASIN 不伪造结果，但其他 ASIN 可以完成独立节点；Run 顶层保持真实的人工或失败状态。

恢复继续使用原 `run_id`。成功且输入、workflow、locator、parser 和上游指纹均未变化的节点不得重复执行。

## 5. 模块设计

新增或重构为以下边界：

```text
agent/tools/sellersprite_cdp.py
  SellerSpriteCDPClient

agent/tools/sellersprite_extension.py
  SellerSpriteExtensionAdapter

agent/tools/sellersprite_workflows/
  registry.py
  product_research.py
  reverse_asin.py
  market_research.py

agent/tools/sellersprite_exports.py
  SellerSpriteExportManager

agent/tools/sellersprite_parsers/
  product_research.py
  reverse_asin.py
  market_research.py
```

### 5.1 SellerSpriteCDPClient

只负责浏览器连接和 CDP 生命周期：

- 从受控 HTTP 或 WebSocket endpoint 解析 CDP；
- 连接用户已运行的 Chrome；
- 选择匹配 Amazon US ASIN 的页面，禁止误用其他 tab；
- 在同一批次安全复用连接；
- 创建和释放 CDP session；
- 使用 `Browser.setDownloadBehavior` 设置受控下载目录；
- 检测断线并执行一次有界重连；
- 不包含 SellerSprite DOM、业务字段或 pipeline 决策。

### 5.2 SellerSpriteExtensionAdapter

只负责插件通用交互：

- 打开插件面板；
- 等待异步加载完成后再次检查 ready；
- 在 iframe、shadow root 或普通 DOM 中解析已审查 locator；
- 识别登录、验证码、权限和配额状态；
- 执行通用 click、fill、wait 和 export 动作；
- 不自动发现、猜测或生成 selector。

### 5.3 Workflow registry

三个 workflow 只描述各自的确定性步骤和输出类型：

- `ProductResearchWorkflow`：从当前 Amazon 商品页的 SellerSprite 面板读取已审查的结构化 DOM 字段，不依赖下载；
- `ReverseAsinWorkflow`：导出完整关键词反查 Excel；
- `MarketResearchWorkflow`：以首选流量词导出一次市场分析 Excel。

后续能力通过 registry 增加独立 workflow，不复制 CDP、下载、错误处理或审计逻辑。

### 5.4 SellerSpriteExportManager

统一执行：

1. 创建 `writing` artifact manifest；
2. 对下载目录做基线快照；
3. 触发一次导出；
4. 等待临时下载扩展名消失和文件大小稳定；
5. flush、fsync、计算大小与 SHA-256；
6. 校验预期文件类型和 parser schema；
7. 原子发布文件；
8. 保存解析结果；
9. 将 manifest 标记为 `committed`；
10. 节点才允许成功。

rename 后、manifest 提交前崩溃时，恢复逻辑根据最终文件、大小、哈希和预期 schema 对账。残缺或不一致文件标记 `invalid` 并重新生成。

## 6. 数据契约

所有快照均为 JSON 可序列化对象并带 `schema_version`、`workflow_version`、`parser_version` 和 evidence references。

### 6.1 Product Data

每个 ASIN 至少支持以下可空字段：

- `asin`
- `title`
- `brand`
- `price`
- `bsr`
- `estimated_monthly_sales`
- `estimated_monthly_revenue`
- `review_count`
- `rating`
- `listed_at` 或可验证的 listing age
- `fulfillment_mode`
- `seller_count`
- `buy_box_state`
- `variation_count`

ASIN 必须与执行节点一致，否则以 `ASIN_MISMATCH` 失败。

原 Amazon 快照不会被静默覆盖：

- ASIN 是不可变身份；
- SellerSprite 的估算销量、销售额、Seller 数等保存为独立市场证据；
- 标题、品牌、价格存在差异时同时保存来源、观察时间和值；
- 归一化业务字段必须记录最终来源；
- 未知值保持 `NULL`，真实零值保持 `0`。

### 6.2 Reverse ASIN

原始导出完整保存，结构化数据至少支持：

- keyword；
- search volume；
- traffic share；
- organic rank；
- sponsored rank；
- PPC 指标；
- click share；
- exposure evidence；
- source row reference。

进入供应商搜索的关键词最多 5 个，选择规则固定：

1. 删除品牌、竞品名、ASIN 和明显导航词；
2. 归一化大小写和空白并去重；
3. 优先存在自然排名、搜索量和流量占比的词；
4. 使用稳定排序和明确 tie-breaker；
5. 保存未选中原因；
6. 保留英文原词和指标；
7. 模型只执行有来源约束的中文采购词翻译，不允许重新想象产品属性。

翻译输出必须能追溯到一个英文流量词。不得只使用图片描述生成新的采购查询。

### 6.3 Market Analysis

每个 ASIN 只对首选流量词运行一次，3-ASIN 批次最多导出 3 份报告。

首批解析字段包括：

- market capacity；
- average price；
- average sales；
- review threshold；
- new-product ratio；
- Top 10 concentration；
- brand concentration；
- FBA ratio；
- FBM ratio；
- advertising competition。

字段映射到现有 `MarketAnalysisDTO` 或新增可空扩展字段。缺失指标不得用零代替。原始 Excel 和字段映射版本必须保留。

## 7. 输入指纹与幂等

SellerSprite 节点输入指纹包括：

- stage 和 handler schema version；
- ASIN 或首选关键词；
- 上游 generation 和 output fingerprint；
- workflow version；
- locator profile 内容哈希；
- parser version；
- 可观测插件版本；
- 与字段选择相关的配置。

业务结果使用稳定 `result_key = node_id + generation + input_fingerprint`。成功节点只有在业务结果或 artifact manifest 仍通过完整性检查时才可跳过。

浏览器连接可以复用，但节点提交必须携带当前 generation 和 lease token。旧页面、旧 worker 或旧下载不能覆盖新尝试。

## 8. 错误分类

| 错误码 | 分类 | 行为 |
|---|---|---|
| `CDP_DISCONNECTED` | retryable | 有界重连，最多重试一次 |
| `PAGE_LOAD_FAILED` | retryable | 有上限退避 |
| `DOWNLOAD_TIMEOUT` | retryable | 有上限退避 |
| `SELLERSPRITE_LOGIN_REQUIRED` | human_required | 登录后继续原节点 |
| `CAPTCHA` | human_required | 人工完成后继续 |
| `SELLERSPRITE_PERMISSION_REQUIRED` | human_required | 停止并说明权限要求 |
| `SELLERSPRITE_QUOTA_EXCEEDED` | human_required | 停止并说明配额要求 |
| `EXTENSION_VERSION_CHANGED` | human_required | 更新审查后的 locator/parser profile |
| `ASIN_MISMATCH` | permanent | 禁止提交错误页面数据 |
| `INVALID_EXPORT` | retryable | 仅重试一次；再次无效则最终失败，不提交不完整数据 |
| `PARSER_SCHEMA_INCOMPATIBLE` | permanent | 保留原文件并更新 parser |
| `CANCELLED` | cancelled | 遵循 Run 级取消语义 |

人工节点不自动重试。权限和配额 selector 只在状态首次自然出现时用脱敏 DOM 证据补录，不消耗配额、不修改订阅、不主动诱发限制。

## 9. 移除 1688 开放平台运行路径

实施时删除：

- `AlibabaPifatuanSearch` 和通用 1688 Open API 的运行调用；
- `ALIBABA_APP_KEY`、`ALIBABA_APP_SECRET`、`ALIBABA_ACCESS_TOKEN` 的主动配置要求；
- 对应 preflight、diagnostic、CLI 和 WebUI 检查操作；
- 专用 API client 测试和不再可达的 mock；
- pipeline 中 `alibaba_text_search`/`pifatuan` API 调用计数和降级分支。

保留：

- 旧数据库和导出中 `alibaba_pifatuan`、`alibaba_text_search` 来源值的显示和读取；
- 与历史 supplier evidence 兼容的 schema；
- 1688 Playwright、cookies、详情补采、验证码/TMD 人工处理和 no-mock 门禁。

不做破坏性数据迁移，不改写旧来源标签。

## 10. SellerSprite API 兼容保留

保留现有：

- API key 配置字段和安全写入能力；
- API client；
- 已有历史诊断记录；
- 人工显式检查入口。

改变默认行为：

- pipeline 不因 key 存在而自动调用 API；
- preflight 不把无效或缺失 key 作为插件主路径警告；
- `seller_sprite_browser` 单独报告 CDP、profile、下载目录、插件就绪和登录状态；
- 只有显式兼容回退开关允许 API 调用，并在 Run 审计中记录数据源。

## 11. 安全和隐私

- 不复制或持久化 Chrome profile、插件 cookie、账号和 token；
- 不把 SellerSprite API key 写入日志、快照或浏览器配置；
- 不暴露宿主机绝对下载路径；
- 不保存完整 DOM，只保存脱敏 locator 证据引用；
- 只允许 Amazon US 页面和已审查的 SellerSprite 插件区域；
- 不调用插件私有 API，不拦截或复用内部鉴权请求；
- locator profile 和 parser profile 由本机受控文件提供并进入版本指纹。

## 12. 测试设计

### 12.1 单元测试

- CDP endpoint 解析和 target 选择；
- ASIN/tab 匹配与拒绝；
- 插件异步 panel ready；
- iframe/shadow/DOM locator；
- 三个 workflow 的步骤和输出契约；
- Top 5 关键词过滤、排序和 tie-break；
- 英文词到中文采购词的来源约束；
- Product Data 字段 provenance；
- `NULL` 与真实零值；
- 三类 parser schema；
- 所有错误分类和状态转换。

### 12.2 集成测试

- 固定页面/Excel fixture 的点击到导入链路；
- 下载目录快照、稳定文件检测和 SHA-256；
- artifact manifest 原子提交和崩溃对账；
- SQLite 幂等结果；
- SellerSprite API 默认调用数为 0；
- 1688 开放平台调用数为 0；
- 1688 Playwright 接收选定关键词和来源。

### 12.3 故障注入

- CDP 在连接前和处理中断开；
- Chrome 重启后重连；
- 插件面板延迟打开；
- 登录、验证码、权限和配额；
- 下载只写一半；
- rename 后、manifest 提交前崩溃；
- Excel schema 变化；
- 单 ASIN 成功后进程退出；
- 旧 worker 或旧页面晚返回；
- 人工继续后只恢复原失败节点。

### 12.4 真实 3-ASIN E2E

从官方 Docker WebUI 启动固定 Amazon US 小批量：

- 发现 3 个 ASIN；
- 每个 ASIN 尝试 Product Data 和 Reverse ASIN；
- 每个 ASIN 最多选择 5 个采购关键词；
- 每个 ASIN 最多 1 份 Market Analysis；
- 供应商只由 1688 Playwright 提供；
- no-mock；
- 自动完成利润、评分、筛选和统一导出；
- 无 SellerSprite API 和 1688 开放平台调用；
- 除明确人工节点外无手动插件点击；
- 业务证据不足保持 `NULL` 或明确不足状态；
- 每个成功节点和 artifact 均可验证；
- 恢复不创建新 Run，不重复执行其他成功 ASIN。

候选数量不是执行成功标准。登录、验证码、权限、配额、外部页面不可用或数据不足必须按真实状态报告。

## 13. 实施阶段

### Phase 1：清理和兼容边界

- 删除 1688 开放平台运行路径；
- 保留历史来源读取；
- 将 SellerSprite API 改为显式兼容回退；
- 更新 preflight、配置状态、CLI、WebUI 和文档。

### Phase 2：CDP 公共适配层

- 抽取 CDP client；
- 实现 target 选择、重连和 session 生命周期；
- 抽取 extension adapter 和 workflow registry；
- 迁移现有 Reverse ASIN 工作流，保持现有行为。

### Phase 3：Product Data 与 Market Analysis

- 现场审查并记录 locator；
- 实现两个新 workflow；
- 建立 parser fixture 和 SQLite 结果模型；
- 接入 artifact manifest。

### Phase 4：关键词驱动的供应商搜索

- 实现 Top 5 选择；
- 实现有来源约束的中文采购词翻译；
- 将 match 输入改为 Reverse ASIN 词源；
- 保持 1688 Playwright、详情验证和 no-mock 门禁。

### Phase 5：恢复执行和产品界面

- 增加三个 SellerSprite 节点；
- 接入 heartbeat、timeout、人工继续和取消；
- WebUI 展示每个 ASIN 的插件状态、导出和错误；
- 保持 CLI 和现有启动方式兼容。

### Phase 6：验证和交付

- 单元、集成和故障注入；
- 全量 pytest；
- 复制 SQLite 迁移检查；
- Docker 重建和 WebUI/API 回归；
- 真实 3-ASIN no-mock 自动化运行；
- 输出运行节点、数据来源、artifact、阻塞和不足证据摘要。

## 14. 验收标准

只有同时满足以下条件才算首批完成：

- SellerSprite 插件是 Product Data、Reverse ASIN 和 Market Analysis 的默认自动数据源；
- SellerSprite API key 保留但默认不调用；
- 1688 开放平台运行能力已删除，历史来源仍可读；
- 3 个 ASIN 的插件操作可通过 CDP 自动执行；
- Reverse ASIN 最多 5 个词确定性进入 1688 Playwright；
- 单 ASIN 失败可恢复，其他成功节点不重复；
- 文件、业务结果和节点状态具有可验证幂等性；
- 人工状态、取消、timeout、断线和旧 worker 可审计；
- no-mock、Amazon US、评分规则、YAML 参数和导出兼容性保持；
- 全量测试、故障注入、迁移演练和 Docker 回归通过；
- 真实 3-ASIN 小批量完成，或停在如实记录的外部/人工阻塞节点；
- 不对没有人工 benchmark 标签的数据声称准确率提升。
