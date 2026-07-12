# Phase 1–2 Sourcing Quality Verification

执行日期：2026-07-12。本文只记录可复现命令实际证明的行为；没有人工 reviewed
标签时不声称匹配准确率提高。

## Changes

- 引入字段级状态、来源、时间、置信度以及 SQLite 迁移记录；缺失与真实 0 分离。
- 增加 Amazon 商品结构化理解、12 类去品牌中文查询、查询尝试持久化。
- 增加 1688 offer detail 提取、拦截页识别、缓存/重试以及正式 no-mock 过滤。
- 增加结构化 MatchEvidence、硬负面规则、双图视觉验证和 schema fail-closed。
- 增加两轮有界的证据补全/重试 sourcing slice 与证据化推荐状态。
- 保留 `python main.py run` 和 `run_pipeline()` 为 deterministic 默认入口；Phase 3
  `--mode agent` 尚未实现。

## Focused test results

命令：

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest \
  tests/test_smoke_run.py tests/test_pipeline_source_mode.py \
  tests/test_pipeline_runtime_controls.py tests/test_agent_runtime.py \
  tests/test_agent_server.py -v
```

第一次执行时误有三组 pytest 并发争用 I/O，结果为 44 passed、2 个 AgentRuntime
两秒等待断言失败、89 warnings、138.82s。失败用例随后隔离复跑为 2 passed、
10 warnings、4.85s。清除并发进程后的完整聚焦复跑为 **46 passed、87 warnings、
104.84s**。并发负载下的两秒固定等待仍是测试稳定性风险。

新增兼容断言证明无 `--mode` 参数的 `run --category ... --limit ...` 仍调用
`run_pipeline(category=..., limit=..., marketplace="US")`。

## Full test results

提交前使用以下命令进行全量验证，最终统计在命令完成后写入：

```bash
TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/
```

首次精确命令结果为 678 passed、5 skipped、1 failed、210 warnings、236.17s；
唯一失败是 `test_runtime_persists_job_history_to_disk` 的两秒异步等待超时。该用例
立即隔离复跑为 1 passed、4 warnings、1.72s。为排除 pytest capture/I/O 对固定两秒
等待的影响，又执行 `pytest tests/ -q -s` 全量复核，结果为 **679 passed、5 skipped、
210 warnings、238.28s**，exit 0。没有功能测试失败；warnings 主要是既有的
`datetime.utcnow()`、SQLAlchemy 默认时间函数和 lxml `strip_cdata` 弃用提示。

## SQLite migration and integrity

对 `data/amazon_selector.db` 的副本执行迁移，而非修改原库：

```bash
cp data/amazon_selector.db /tmp/amazon_selector_migration_test.db
DATABASE_URL=sqlite:////tmp/amazon_selector_migration_test.db python3 -m db.init_db
```

核验结果：

- `PRAGMA foreign_keys` = `1`；
- `PRAGMA integrity_check` = `ok`；
- `PRAGMA foreign_key_check` 无结果行；
- migration versions 为 `0001_evidence_foundation`、
  `0002_repair_evidence_semantics`；
- 迁移前已存在的 13 张业务/迁移表逐表行数完全一致。

副本迁移时没有待应用版本（`migrations_applied=[]`），因此本次证明当前生产库副本
在最新 schema 上可重复初始化且不改历史行数；更早 schema 到最新版本的原子升级由
migration 失败注入测试覆盖。

## Real no-mock E2E

官方运行路径：

```bash
docker compose up -d --build amazon-selector
docker compose exec -T amazon-selector python main.py smoke-run \
  --category "Home & Kitchen" --marketplace US --limit 1 --top-n 1 \
  --llm-verification --require-market-data --require-supplier-evidence \
  --timeout-seconds 180
```

容器成功重建并监听 `127.0.0.1:8765`。试跑配置确认 `no_mock=true`、市场证据和
供应商证据均为必需。终态为 `market_data_unavailable`（CLI exit 2）：SellerSprite
ASIN detail 与 competitor lookup 均返回“秘钥无效”。Preflight 同时报告 1688
pifatuan `HTTP 400 [gw.APIUnsupported]`，但 1688 cookie 检查通过（69 cookies）。

该门禁在 pipeline 启动前停止，因此：

- crawled products = 0；query attempts、详情字段、match decision、retry、export path
  均不存在；
- mock supplier count = 0，但这是因为没有产生候选，不能作为真实供应商质量成功；
- 没有用 mock 或旧导出替代本次结果；本次是外部市场数据基础设施阻断，不是
  `recommend` / `needs_manual_review` / `reject` / `insufficient_data` 质量终态；
- 人工队列为 open=1、total=1。修复 SellerSprite 凭证后必须重跑同一命令，随后才能
  检验 1688 查询、详情、双图验证及最终状态。

## Field completeness before and after

Phase 0 固定 cohort：60 个 Amazon products、288 个 suppliers、latest run 49。
按 artifact 的同一字段定义计算：

| 指标 | Phase 0 | Phase 1–2 real E2E 后 |
|---|---:|---:|
| Amazon 字段可用率（33 字段） | 27.47% (544/1980) | not measurable: E2E 在入库前被市场门禁阻断 |
| 1688 字段可用率（32 字段） | 21.94% (2022/9216) | not measurable: 未产生本次 supplier cohort |
| 市场字段缺失率（search volume/trend/competition） | 100% | not measurable: SellerSprite key invalid |
| 真实 supplier rate | 仅 offer identity 288/288；不代表详情已验证 | not measurable: 0 suppliers crawled |
| mock contamination | artifact 未提供可信 mock denominator | 0 observed / 0 suppliers；不得解释为 rate=0% |

代码能够保存新增证据字段不等于历史数据已被补全。由于真实运行没有越过市场门禁，
本报告不虚构“after”完整率，也不把 schema coverage 当数据 coverage。

## Match metrics from reviewed labels

命令：

```bash
python3 scripts/evaluate_sourcing_quality.py \
  --labels benchmarks/fixtures/sourcing_quality_seed.json \
  --predictions benchmarks/fixtures/empty_predictions.json \
  --output /tmp/task13_benchmark.json
```

`reviewed_case_count=0`。supplier precision@1、precision@5、false match rate、
no-match accuracy、recommendation precision、field completeness、real supplier rate、
mock contamination、manual-review rate、cost per approved candidate、average retries 和
quality pipeline success rate 全部为 `null`。

结论：**not measurable: no reviewed labels**。不能声称匹配准确率或推荐准确率提高。

## Mock contamination before and after

Phase 0 artifact 只把 288 个 offer 标为 `real_offer_identity`，并明确该状态不验证
供应商属性、价格、MOQ 或新鲜度；它没有给出可审计的 mock denominator。因此历史
mock contamination 不可测。本次正式 E2E 配置禁止 mock，且在候选生成前停止，观察
到 0 个 mock / 0 个 suppliers；不能以零分母报告 0% 污染率。

## Remaining blockers and human verification

1. 更新并验证 SellerSprite/MJJL 凭证，再跑要求 market evidence 的真实小样本。
2. 1688 pifatuan 当前返回 API unsupported；需确认权限/接口或依赖 Playwright 真实搜索，
   并对登录、captcha、TMD 人工交接做现场验证。
3. 为 benchmark seed 完成人工 reviewed 标签；在此之前所有 accuracy delta 不可测。
4. 在成功生成 supplier cohort 后，以完全相同字段定义重新生成 after completeness，
   不能把新列存在视为字段已补抓。
5. Phase 3 finite-state Agentic Sourcing Loop 和 `--mode agent` 未实现；当前 agent runtime
   仍主要编排 deterministic pipeline。

## Post-review evidence hardening

整分支复审后又补充了以下 fail-closed 约束：

- 推荐级关键证据必须具有可接受的 `extracted` / `verified` provenance、状态、新鲜度和置信度；
- 未计算的 confidence 保持 `NULL`，失败查询的 count / hit rate 保持 `NULL`，真实零仍为 `0`；
- Amazon 售价缺失或非法时不再生成利润快照；
- 视觉验证保留 provider 稳定错误码，仅瞬态 `PROVIDER_FAILURE` 有界重试一次，schema 错误和图片证据缺失立即转人工复核。

最终提交内容全量复核为 **696 passed、5 skipped、exit 0**；整分支复审结论为 READY。
