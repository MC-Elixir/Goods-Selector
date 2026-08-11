"""校验卖家精灵 MCP 通道的字段完整性，判断能否等价替换 REST。

官方 MCP 页面宣传「Token 消耗直降 90%+」，返回内容有被裁剪的可能。若裁掉的
恰好是 `analyzers/scorer.py` 依赖的字段，Stage 4 就会静默降级——本脚本用来在
切换前把这件事验证清楚。

默认只走 MCP：REST 侧「每个服务仅可提交一次试用申请」，不该被验证脚本消耗。
确实需要逐字段对账时再加 --compare-rest。

用法：
    python -m scripts.verify_sellersprite_mcp B08GHW4TBS
    python -m scripts.verify_sellersprite_mcp B08GHW4TBS --keyword "kitchen mat"
    python -m scripts.verify_sellersprite_mcp B08GHW4TBS --compare-rest
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, fields
from typing import Any, Optional

from analyzers.maijiajingling import MaijiajinglingClient, MarketAnalysisDTO

# analyze_market_evidence 的门槛字段：缺任何一个，市场证据就不算 success
CRITICAL_FIELDS = (
    "est_monthly_sales",
    "competing_listings",
    "search_volume_monthly",
    "top10_revenue_share",
)

# 仍会进 demand / risk 维度打分，缺失只是精度下降
OPTIONAL_FIELDS = (
    "est_daily_sales",
    "opportunity_score",
    "seasonality",
)

# 逐字段对账时跳过：原始报文和诊断信息本就随通道不同
_UNCOMPARED_FIELDS = frozenset({"raw_data"})


@dataclass
class FieldReport:
    asin: str = ""
    marketplace: str = ""
    present: dict[str, Any] = field(default_factory=dict)
    missing_critical: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.missing_critical:
            return "unusable"
        if self.missing_optional:
            return "degraded"
        return "equivalent"


@dataclass
class FieldDiff:
    field: str
    kind: str  # missing_in_mcp | missing_in_rest | value_mismatch
    mcp_value: Any = None
    rest_value: Any = None


def _is_missing(value: Any) -> bool:
    """None 与空容器算缺失；0 / False 是合法取值。"""
    if value is None:
        return True
    if isinstance(value, (dict, list, tuple, set, str)) and len(value) == 0:
        return True
    return False


def check_market_fields(dto: MarketAnalysisDTO) -> FieldReport:
    report = FieldReport(asin=dto.asin, marketplace=dto.marketplace)
    for name in CRITICAL_FIELDS + OPTIONAL_FIELDS:
        value = getattr(dto, name, None)
        if _is_missing(value):
            if name in CRITICAL_FIELDS:
                report.missing_critical.append(name)
            else:
                report.missing_optional.append(name)
        else:
            report.present[name] = value
    return report


def compare_market_dtos(mcp: MarketAnalysisDTO, rest: MarketAnalysisDTO) -> list[FieldDiff]:
    diffs: list[FieldDiff] = []
    for spec in fields(MarketAnalysisDTO):
        if spec.name in _UNCOMPARED_FIELDS:
            continue
        mcp_value = getattr(mcp, spec.name, None)
        rest_value = getattr(rest, spec.name, None)
        mcp_missing, rest_missing = _is_missing(mcp_value), _is_missing(rest_value)
        if mcp_missing and rest_missing:
            continue
        if mcp_missing:
            diffs.append(FieldDiff(spec.name, "missing_in_mcp", mcp_value, rest_value))
        elif rest_missing:
            diffs.append(FieldDiff(spec.name, "missing_in_rest", mcp_value, rest_value))
        elif mcp_value != rest_value:
            diffs.append(FieldDiff(spec.name, "value_mismatch", mcp_value, rest_value))
    return diffs


_VERDICT_NOTE = {
    "equivalent": "MCP 字段齐全，可以等价替换 REST",
    "degraded": "MCP 可用，但 demand/risk 维度精度会下降",
    "unusable": "MCP 缺少评分必需字段，尚不能替换 REST",
}


def format_report(report: FieldReport, diffs: Optional[list[FieldDiff]]) -> str:
    lines = [
        "SellerSprite MCP 字段完整性检查",
        f"ASIN: {report.asin or '-'}  站点: {report.marketplace or '-'}",
        "",
        f"结论: {report.verdict} — {_VERDICT_NOTE[report.verdict]}",
        "",
        "必需字段（市场证据门槛 + 硬筛依赖）:",
    ]
    for name in CRITICAL_FIELDS:
        if name in report.present:
            lines.append(f"  [OK]      {name} = {report.present[name]!r}")
        else:
            lines.append(f"  [MISSING] {name}")

    lines += ["", "可选字段（影响 demand / risk 打分精度）:"]
    for name in OPTIONAL_FIELDS:
        if name in report.present:
            lines.append(f"  [OK]      {name} = {report.present[name]!r}")
        else:
            lines.append(f"  [MISSING] {name}")

    if diffs is not None:
        lines += ["", "与 REST 通道逐字段对账:"]
        if not diffs:
            lines.append("  两条通道结果一致")
        for diff in diffs:
            if diff.kind == "value_mismatch":
                lines.append(f"  [DIFF]    {diff.field}: mcp={diff.mcp_value!r} rest={diff.rest_value!r}")
            elif diff.kind == "missing_in_mcp":
                lines.append(f"  [MCP 缺]  {diff.field}: rest={diff.rest_value!r}")
            else:
                lines.append(f"  [REST 缺] {diff.field}: mcp={diff.mcp_value!r}")

    return "\n".join(lines)


def _analyze(asin: str, marketplace: str, keyword: Optional[str], transport: str) -> MarketAnalysisDTO:
    with MaijiajinglingClient(transport=transport) as client:
        if not client._configured:
            raise SystemExit("MJJL_API_KEY 未配置：先把密钥写进 .env 再运行本脚本")
        return client.analyze_market(asin, marketplace=marketplace, keyword=keyword)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="校验卖家精灵 MCP 通道的字段完整性")
    parser.add_argument("asin", help="用于验证的 Amazon ASIN")
    parser.add_argument("--marketplace", default="US")
    parser.add_argument("--keyword", default=None, help="关键词选品的查询词，默认取类目名")
    parser.add_argument(
        "--compare-rest",
        action="store_true",
        help="额外跑一次 REST 并逐字段对账（会消耗 REST 配额）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非文本报告")
    args = parser.parse_args(argv)

    mcp_dto = _analyze(args.asin, args.marketplace, args.keyword, "mcp")
    report = check_market_fields(mcp_dto)

    diffs = None
    if args.compare_rest:
        rest_dto = _analyze(args.asin, args.marketplace, args.keyword, "rest")
        diffs = compare_market_dtos(mcp_dto, rest_dto)

    if args.json:
        print(json.dumps(
            {
                "asin": report.asin,
                "marketplace": report.marketplace,
                "verdict": report.verdict,
                "present": {k: str(v) for k, v in report.present.items()},
                "missing_critical": report.missing_critical,
                "missing_optional": report.missing_optional,
                "diffs": [
                    {
                        "field": d.field,
                        "kind": d.kind,
                        "mcp": str(d.mcp_value),
                        "rest": str(d.rest_value),
                    }
                    for d in (diffs or [])
                ],
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(format_report(report, diffs))

    return 1 if report.verdict == "unusable" else 0


if __name__ == "__main__":
    sys.exit(main())
