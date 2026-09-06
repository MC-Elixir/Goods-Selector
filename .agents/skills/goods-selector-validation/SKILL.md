---
name: goods-selector-validation
description: Select and run goods-selector regression gates for the changed behavior.
---

# goods-selector 验证

按受影响行为选择下面对应的检查；不因文档编辑而启动完整业务回归。已授权代码修复包含必要的隔离检查、修正及重跑，不逐次请求批准。执行前核对测试配置及数据隔离；不要假定所有 tests/ 都无外部副作用。

## 按改动选择门禁

命令从仓库根目录运行。CI 的准确范围以 `.github/workflows/ci.yml` 为准：
Ruff、Mypy、`pytest tests/ -q`、Docker 镜像构建及 Compose 配置校验均是现有门禁。

- `CODEOWNERS` 保护的 `matchers/__init__.py`、`pipeline/orchestrator.py`、
  `analyzers/scorer.py`：任何修改必须有对应 `tests/` 改动，且合并前通过审阅。
- 修改评分 YAML 必须运行 `pytest tests/test_scoring.py`；修改成本/筛选逻辑同时运行
  `tests/test_profit_model.py`、`tests/test_filters.py` 中相关回归。
- 修改状态、恢复或产物提交：运行 `tests/test_execution_*.py` 和
  `tests/test_recoverable_*.py` 的相关回归，覆盖租约失效、幂等、恢复及部分产物。
  修改数据库结构或迁移必须运行 `tests/test_db_migrations.py`。
- 修改来源或证据合同：运行 `tests/test_pipeline_source_mode.py`、
  `tests/test_pipeline_market_cap.py` 及受影响的 sourcing schema、匹配、导出回归；
  品类合同/人工判定还须运行 `tests/test_target_contract_*.py` 与
  `python -m benchmarks.evaluate_target_contract`。合成合同指标不代表真实搜索准确率。
- 修改 MCP / Hermes 时运行 `tests/test_selector_mcp_*.py`、`tests/test_hermes_profile.py`
  及受影响的配置脚本测试；修改部署时运行 `tests/test_docker_deployment.py`、
  `tests/test_preflight.py` 及相关启动测试，并完成镜像构建和 Compose 校验。
- 普通回归使用隔离数据；`tests/e2e/test_sellersprite_extension.py` 是需明确授权并设置
  `SELLERSPRITE_E2E=1` 的真实浏览器测试，不属于无副作用离线检查。
  不将生产镜像内缺少测试配置或测试替身的运行当作完整源码回归，见部署文档。


检查通过后，除新改动、失败或未解决风险外，不扩大或重复验证。交付时说明本次检查、源码/环境及未执行门禁；真实部署验收另用 [goods-selector-deployment](../goods-selector-deployment/SKILL.md)。
