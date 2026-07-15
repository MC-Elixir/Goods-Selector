# ASIN 级可恢复执行基础设施设计

日期：2026-07-15
状态：已确认，待实施计划

## 1. 目标

在不改变 Amazon Selector 现有选品业务逻辑的前提下，为固定的 7 阶段 deterministic pipeline 增加细粒度、持久化、可审计的恢复能力。

本批完成后，单个 ASIN 在 `match`、`profit`、`market`、`score` 或浏览器相关调用失败时，可以只恢复该 ASIN 的失败节点。服务或浏览器进程异常退出后，系统可以识别失效的运行记录，并从安全节点继续。已成功且输入未变化的节点不得重复执行。

设计必须保持：

- `main.py run` 与 `run_pipeline()` 兼容入口；
- Amazon US 固定站点；
- 现有业务阶段顺序、评分规则和 YAML 参数；
- no-mock 与证据门禁；
- SellerSprite、Amazon、1688 的现有数据契约；
- DTO 与 ORM 的边界；
- 当前 CLI、WebUI、Docker 启动方式和导出内容格式。

## 2. 现状审计结论

当前实现已经具备部分基础能力，但还不是可恢复执行系统：

- `AgentRuntime` 有单进程队列、整次任务取消、整次任务重试和 JSON 状态保存；重启时会把运行中任务标记为中断失败，而不是恢复原 Run。
- `pipeline/orchestrator.py` 会发送带 ASIN 的进度事件，但 `RunEvent` 是遥测时间线，不是 checkpoint，也不能决定节点是否跳过或重试。
- pipeline 已按产品循环执行 match、profit、market 和 score，但仍按整批 Stage 推进，内存中的 `PipelineRecord` 是下游主要上下文。
- 当前 timeout 主要在调用前后检查整阶段累计耗时，不能可靠中断正在执行的浏览器、HTTP 或 LLM 调用。
- `Supplier` 通过产品和 offer 唯一键 upsert；`ProfitSnapshot`、`Score`、`MarketAnalysis` 没有执行级幂等键，恢复可能重复追加。
- Excel、Markdown、JSON 分别写出，没有统一 artifact manifest；部分导出失败仍可能让 Run 标记成功。
- 结构化 Python 迁移、迁移版本表、SQLite 事务回滚和 foreign-key 连接监听已经存在，应复用而不是重建。
- 现有部分持久化代码仍用 `or 0.0` 合并缺失值。执行基础设施不得继续扩大这种语义；未知值必须保留为 `NULL` 或显式缺失状态。

## 3. 已评估方案

### 3.1 仅在现有阶段循环外增加 checkpoint

优点是改动最小。缺点是阶段仍按整批推进，恢复时难以重建单个 ASIN 的完整上下文，也无法为后续长链路提供可靠节点边界。因此不采用。

### 3.2 增量状态层与确定性 ASIN 节点调度器

保留现有业务函数和兼容入口，在调用层增加节点状态、尝试历史、租约、快照、幂等提交和 artifact 管理。改动可控，并能满足真实恢复要求。采用此方案。

### 3.3 通用 DAG 或外部分布式任务系统

扩展性更强，但会引入不必要的调度复杂度，并接近重写 orchestrator。Celery、Redis、多机 worker 和自由规划 Agent 均不属于本批范围。因此不采用。

## 4. 调用链设计

现有调用链：

```text
AgentRuntime / CLI / WebUI
  -> run_pipeline
  -> crawl whole batch
  -> match whole batch
  -> profit whole batch
  -> market whole batch
  -> score whole batch
  -> filter
  -> three independent exporters
```

新调用链：

```text
AgentRuntime / CLI / WebUI
  -> run_pipeline compatibility entry
  -> RecoverableRunCoordinator
       -> run:source_discovery
       -> asin:ingest
       -> asin:match
       -> asin:profit
       -> asin:market
       -> asin:score
       -> run:filter
       -> run:export
  -> StageExecutor
       -> atomic claim and lease
       -> handler call outside transaction
       -> atomic result and state commit
       -> retry, human handoff, cancellation, audit
```

`source_discovery` 是 Run 级节点，因为类目或关键词 crawl 在完成前还不知道 ASIN 集合。每个被发现的商品从 `ingest` 开始进入 ASIN 级节点。不得创建语义虚假的 ASIN `crawl` 节点。

执行继续使用阶段屏障，以保持现有业务顺序：

```text
source_discovery
-> all ingest terminal
-> all match terminal
-> all profit terminal
-> all market terminal
-> all score terminal
-> filter
-> export
```

恢复时只领取未完成、允许重试或输入指纹发生变化的节点。

## 5. 模块边界

新增独立执行基础设施包：

```text
execution/
  models.py       statuses, commands, errors, StageContext
  repository.py   claims, transitions, snapshots, audit writes
  coordinator.py  deterministic scheduling and recovery
  handlers.py     thin adapters over existing business functions
  policies.py     retry, backoff, timeout and error classification
  artifacts.py    artifact manifests and atomic publication
```

职责约束：

- coordinator 只决定哪个节点可运行，不实现选品业务。
- handler 从快照或数据库重建 DTO，调用现有业务函数并返回可序列化结果。
- repository 是状态转换和持久化的唯一写入口。
- artifacts 负责文件完整性，不参与候选判断。
- `pipeline/orchestrator.py` 保留兼容入口和高层业务顺序，不继续承载状态机细节。

每个 handler 接收：

```python
StageContext(
    run_id=run_id,
    asin=asin,
    attempt_no=attempt_no,
    generation=generation,
    deadline=deadline,
    cancel_check=cancel_check,
    heartbeat=heartbeat,
    input_snapshot=input_snapshot,
)
```

## 6. 数据模型

### 6.1 execution_nodes

保存节点当前状态，每个逻辑节点只有一行：

- `id`
- `run_id`, foreign key to `run_logs.id`
- `scope_type`: `run` or `asin`
- `scope_key`: Run 固定键或 ASIN
- `stage`
- `status`
- `attempt_count`
- `generation`
- `input_fingerprint`
- `output_fingerprint`
- `input_snapshot`
- `output_snapshot`
- `evidence_refs`
- `worker_id`
- `heartbeat_at`
- `lease_expires_at`
- `next_retry_at`
- `timeout_seconds`
- `error_code`
- `error_detail`
- `human_action_required`
- `resume_token`
- `started_at`, `finished_at`, `created_at`, `updated_at`

唯一约束：

```text
(run_id, scope_type, scope_key, stage)
```

`resume_token` 是并发和版本校验令牌，不保存登录态、cookie、账号或其他敏感信息，也不承担用户鉴权。

### 6.2 execution_attempts

保存不可变的尝试历史：

- `node_id`
- `attempt_no`
- `generation`
- `status`
- `worker_id`
- `lease_token`
- `input_fingerprint`, `output_fingerprint`
- `input_snapshot`, `output_snapshot`
- `started_at`, `heartbeat_at`, `finished_at`
- `error_code`, `error_detail`
- `finish_reason`

唯一约束：

```text
(node_id, attempt_no)
```

### 6.3 execution_operations

保存 `resume`、`retry`、`force_rerun`、`cancel` 和 `stale_recovery` 等操作：

- `run_id`, optional `node_id`
- `operation`
- `actor_type`, `actor_ref`
- `reason`
- `before_status`, `after_status`
- `payload`
- `created_at`

强制重跑必须提供原因。

### 6.4 artifact_manifests

保存文件引用和完整性信息：

- `run_id`, `node_id`, `attempt_id`
- `artifact_set_id`
- `logical_name`, `artifact_type`
- `temporary_path`, `final_path`
- `size_bytes`, `sha256`
- `status`: `writing`, `committed`, `invalid`
- `created_at`, `committed_at`

数据库不保存完整图片、HTML、Excel 或其他大文件。

### 6.5 业务结果幂等键

为 `ProfitSnapshot`、`Score`、`MarketAnalysis` 增加可空但唯一的 `result_key`。旧记录保持 `NULL`，新执行使用以下稳定组成生成键：

```text
node_id + generation + input_fingerprint
```

`Supplier` 继续使用现有产品与 offer 唯一键 upsert。正常恢复不重复写业务快照；显式 force rerun 增加 generation，允许保留新的业务快照。

## 7. 状态与转换

节点支持：

```text
pending
running
succeeded
failed
retry_wait
human_required
cancelled
skipped
timed_out
```

合法转换：

```text
pending -> running
running -> succeeded | failed | retry_wait | human_required | cancelled | timed_out
retry_wait -> pending
human_required -> pending
failed -> pending
```

规则：

- `pending -> running` 必须通过带条件的数据库原子更新，并在同一事务中创建 attempt 和 lease。
- `human_required` 恢复时先回到 `pending`，再由调度器领取。
- `failed -> pending` 只能由显式 retry 操作触发。
- `succeeded` 默认不可变。force rerun 会记录操作、增加 generation 并回到 `pending`。
- `skipped` 只表示阶段明确不适用，例如 market 未配置或超出明确配额。
- 数据不足属于业务输出，不属于执行状态。
- `timed_out` 和 `stale` 优先作为 attempt 的结束原因。节点根据策略进入 `retry_wait`、`timed_out` 或最终 `failed`。

## 8. 恢复、租约与 fencing

运行节点持有 `worker_id`、`lease_token`、heartbeat 和 lease 到期时间。

服务启动或周期扫描时：

1. 找出 `running` 且 lease 过期的节点。
2. 使用条件更新确认 lease 仍然属于旧 worker。
3. 将旧 attempt 结束为 `worker_lost` 或 `stale`，绝不标记成功。
4. 未超过上限时进入 `retry_wait`，否则进入最终失败。
5. 所有回收写入 `execution_operations`。

业务结果提交必须携带当前 `generation + lease_token`。旧 worker 即使晚返回，也不能覆盖已被重新领取或强制重跑的节点。

同一逻辑任务恢复时继续使用原 `run_id`。每次尝试新增 attempt，不创建新的 Run，也不覆盖旧尝试。

## 9. 输入、输出快照与依赖指纹

所有快照必须可 JSON 序列化，并带 schema version。大文件只保存 manifest 或 evidence reference。

节点输入指纹由以下内容稳定计算：

- stage 与 handler schema version；
- Run 配置中与该阶段相关的字段；
- 上游节点 generation 和 output fingerprint；
- 与结果相关的 YAML 参数版本或内容哈希。

跳过条件必须同时满足：

- 当前节点为 `succeeded`；
- 当前输入指纹等于成功时的输入指纹；
- 已提交业务结果或 artifact 仍能通过完整性检查。

如果 B 的 match 在恢复后成功，B 的 profit、market 和 score 会因新输入被执行。Run 级 filter/export 的聚合输入指纹也会变化，因此重新执行。A、C 输入未变的节点继续跳过。

## 10. 事务与幂等提交

浏览器、HTTP 和 LLM 调用不得位于数据库事务中。

handler 完成计算后，repository 在一个短事务中：

1. 验证 generation 和 lease token；
2. 以 result key upsert 或插入业务结果；
3. 保存 output snapshot 和 fingerprint；
4. 结束 attempt；
5. 将节点标记为 `succeeded`。

这样可以避免“业务结果已经写入、节点状态尚未更新”的不一致窗口。事务失败时所有本地写入回滚。

如果外部调用已经返回但本地事务尚未开始时进程退出，恢复后允许重新调用外部服务，但最终本地结果仍由 result key 和 fencing 去重。

## 11. 导出协议

Excel、JSON、Markdown 组成一个 artifact set：

1. 创建 `writing` manifest。
2. 在最终目录内写临时文件。
3. flush、fsync 并计算 SHA-256。
4. 使用 `os.replace` 原子发布各文件。
5. 校验全部预期文件的存在性、大小和哈希。
6. 将 manifest 改为 `committed`，然后 export 节点才能成功。

如果在 rename 后、manifest 提交前崩溃，恢复逻辑根据最终文件和预期哈希进行对账；完整则补提交，缺失或不一致则标记 invalid 并重新生成。

继续保留 `candidates_*.json`、`candidates_*.xlsx` 和当前字段格式，以兼容 `agent.history`。单个 ASIN Markdown 不再作为无审计的独立成功信号，而是 artifact set 的组成部分。

## 12. 错误、重试与人工节点

错误分类：

- `retryable`: 临时网络错误、限流、短暂浏览器失败；
- `human_required`: 登录、验证码、TMD、权限或人工确认；
- `permanent`: 输入无效、schema 不兼容、确定性业务错误；
- `cancelled`;
- `timed_out`;
- `worker_lost`。

重试策略必须有最大次数和有上限的指数退避。人工节点不自动重试。

当前 timeout 实现不能可靠中断正在运行的调用，因此改为：

- HTTP、浏览器和 LLM 使用各自原生 timeout；
- 长循环接收 deadline、cancel check 和 heartbeat；
- 不使用超时后仍让后台线程继续运行的通用包装；
- 进程直接退出依靠 lease 过期恢复。

人工阻塞统一转换为结构化 `HumanActionRequired`，保存稳定 error code、操作说明和 evidence refs。现有 manual queue 可作为兼容展示，但 SQLite 节点是恢复事实来源。

## 13. 取消语义

取消 Run 时：

- 未领取的 pending/retry_wait 节点进入 cancelled；
- 运行节点通过现有 cancel check 尽快停止；
- 已成功节点保留成功状态；
- 晚返回结果必须通过 lease fencing 拒绝；
- Run 汇总状态只有在所有运行节点终止后才进入 cancelled。

取消单节点不是本批公开 UI 操作，避免破坏依赖一致性。

## 14. AgentRuntime、API 与 WebUI

SQLite 是执行状态唯一事实来源。`agent_jobs.json` 只保留队列和 UI 遥测，不决定恢复结果。

Run 顶层状态由节点聚合得到，并写回 `RunLog`：

- 存在运行节点时为 `running`；
- 没有运行节点但存在人工节点时为 `human_required`；
- 没有可运行节点但存在等待重试节点时为 `retry_wait`；
- 收到取消请求且仍有运行节点时为 `cancel_requested`；
- 全部应运行节点成功或按规则跳过，且 export artifact set 已提交时为 `success`；
- 取消完成时为 `cancelled`；
- 存在不可恢复失败、且已无可运行或等待节点时为 `failed`。

旧消费者仍可继续识别 `running`、`success`、`failed` 和 `cancelled`；新增状态由 WebUI 显式展示，不能被映射成假失败。

需要提供：

- `resume_pipeline(run_id)`；
- `retry_node(run_id, asin, stage)`；
- `force_rerun_node(run_id, asin, stage, reason)`；
- 节点与 attempt 查询 API；
- Run 级取消和重试兼容行为。

WebUI 只增加最小功能：

- 节点状态列表；
- attempt 次数、最近错误和人工操作说明；
- 继续节点、重试和强制重跑按钮；
- 强制重跑原因输入。

不引入新前端框架，也不重写服务层。

## 15. 迁移设计

新增结构通过下一个结构化 Python migration 创建，不使用 `raw.split(";")`。

当前 `init_db()` 先运行 `Base.metadata.create_all()`，新 ORM 模型可能抢先创建本应由迁移管理的表。实施时需要调整初始化边界：只由 legacy baseline 创建原有核心表，新执行表必须由版本化 migration 创建，再由 ORM 映射使用。

迁移要求：

- 对现有数据库仅做 additive change；
- 新增 result key 对旧数据允许 `NULL`；
- 失败时原子回滚且不推进迁移版本；
- 重复执行无副作用；
- 所有连接正确启用 SQLite foreign keys；
- 不使用 `DEFAULT 0` 表示缺失证据或未知结果；
- 在复制的真实数据库上检查 `integrity_check`、`foreign_key_check` 和迁移前后行数。

## 16. 测试设计

### 16.1 单元测试

- 所有合法和非法状态转换；
- 原子领取与重复领取竞争；
- attempt_count、attempt_no 和 generation；
- stale lease 检测与回收；
- retry_wait 到期前后行为；
- human_required 回补；
- succeeded 默认跳过；
- force rerun 与审计；
- 唯一约束和 result key 幂等；
- 快照序列化和 schema version；
- `NULL` 与真实零值；
- 上游指纹变化触发下游失效；
- 旧 lease 的延迟结果被 fencing 拒绝。

### 16.2 迁移测试

- 新库初始化；
- 现有库增量升级；
- 重复迁移；
- 失败原子回滚；
- foreign keys 对现有和后续连接均开启；
- SQL 中分号安全；
- 既有数据和行数保留。

### 16.3 故障注入

- match 调用前崩溃；
- match 返回后、本地事务前崩溃；
- 本地结果与状态提交时数据库失败；
- succeeded 后、下游激活前崩溃；
- 浏览器超时；
- human_required；
- SQLite 写入失败；
- 导出文件只写一半；
- rename 后、manifest 提交前崩溃；
- heartbeat 更新失败；
- 并发领取同一节点；
- force rerun 后旧 worker 延迟返回。

### 16.4 最小 E2E

使用 3 个确定性 ASIN：

- A、C 首次 match 成功；
- B 首次 match 失败；
- 恢复时只重试 B 的 match；
- A、C 的 ingest 和 match 不重复；
- B 的已成功上游不重复；
- B 在恢复后继续 profit、market 和 score；
- filter/export 因聚合输入变化重新执行；
- 最终业务表和导出没有重复；
- no-mock 门禁继续生效。

真实浏览器 no-mock E2E 单列执行。登录、验证码、凭证或外部数据阻塞必须报告为基础设施阻塞，不能包装为成功。

## 17. 实施阶段

### Phase 1: 基线、迁移和状态 repository

- 补现有行为 character tests；
- 新增数据库结构、约束和索引；
- 调整初始化与迁移边界；
- 完成状态转换、领取、lease、attempt 和 operation repository。

### Phase 2: 最小可恢复纵切

- 接入 `source_discovery -> ingest -> match`；
- 接入 heartbeat、retry、human_required、resume 和取消；
- 用 3 ASIN 证明只恢复 B。

### Phase 3: 下游 ASIN 节点

- 接入 profit、market 和 score；
- 增加 result key；
- 完成输入输出指纹和下游失效；
- 明确 market skipped 与数据不足语义。

### Phase 4: Run 聚合节点与 artifacts

- 接入 filter 和 export；
- 完成 artifact set、原子发布、完整性校验和崩溃对账；
- 保持历史导出读取兼容。

### Phase 5: Runtime、API 与 WebUI

- AgentRuntime 从 SQLite 恢复；
- 增加节点查询和操作 API；
- 增加最小 WebUI 状态与恢复入口。

### Phase 6: 验证与交付

- 完整故障注入；
- 3 ASIN E2E；
- 全量测试；
- Docker 镜像内验证；
- 复制真实 SQLite 数据库迁移演练；
- 输出调用链、状态图、迁移和测试结果。

## 18. 明确不在本批范围

- 1688/Pailitao 图片搜索业务；
- 文本召回与图搜融合；
- 新评分或选品规则；
- Celery、Redis 和多机 worker；
- 通用 DAG 引擎；
- React、Next.js、Vue 或 FastAPI 重写；
- 自由规划 Agent；
- 未经人工标签支持的 benchmark 提升声明。

可以预留受控 stage registry，使下一阶段添加 `image_recall`、`supplier_detail`、`visual_verify` 等名称，但本批不创建或运行这些节点。

## 19. 验收标准

本批只有同时满足以下条件才算完成：

- 单 ASIN 单节点能够安全恢复；
- 成功上游不重复执行；
- 业务结果、状态和文件产物具备可验证幂等性；
- stale、timeout、human_required、cancel 和 force rerun 可审计；
- 当前 CLI、WebUI 基本调用、Docker 启动、业务顺序和导出格式保持兼容；
- 3 ASIN E2E 与全部故障注入通过；
- 全量测试通过；
- 复制数据库迁移检查通过；
- 真实 no-mock 外部阻塞被如实报告。
