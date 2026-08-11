"""MCP 字段完整性验证脚本的单测（离线，不连卖家精灵）。"""
from __future__ import annotations

from analyzers.maijiajingling import MarketAnalysisDTO
from scripts import verify_sellersprite_mcp as verify


def _complete_dto() -> MarketAnalysisDTO:
    return MarketAnalysisDTO(
        asin="B0TEST1234",
        est_monthly_sales=540,
        est_daily_sales=18,
        competing_listings=10,
        top10_revenue_share=0.31,
        search_volume_monthly=4200,
        opportunity_score=0.12,
        seasonality={"month_1": 100},
    )


def test_complete_dto_reports_no_missing_fields():
    report = verify.check_market_fields(_complete_dto())

    assert report.missing_critical == []
    assert report.missing_optional == []
    assert report.verdict == "equivalent"


def test_missing_critical_field_is_flagged_as_unusable():
    dto = _complete_dto()
    dto.top10_revenue_share = None

    report = verify.check_market_fields(dto)

    assert report.missing_critical == ["top10_revenue_share"]
    assert report.verdict == "unusable"


def test_missing_optional_field_is_only_a_degradation():
    dto = _complete_dto()
    dto.opportunity_score = None

    report = verify.check_market_fields(dto)

    assert report.missing_critical == []
    assert report.missing_optional == ["opportunity_score"]
    assert report.verdict == "degraded"


def test_empty_seasonality_counts_as_missing():
    dto = _complete_dto()
    dto.seasonality = {}

    report = verify.check_market_fields(dto)

    assert "seasonality" in report.missing_optional


def test_zero_is_a_real_value_not_a_missing_field():
    dto = _complete_dto()
    dto.est_monthly_sales = 0

    report = verify.check_market_fields(dto)

    assert report.missing_critical == []


def test_empty_dto_flags_every_critical_field():
    report = verify.check_market_fields(MarketAnalysisDTO())

    assert set(report.missing_critical) == set(verify.CRITICAL_FIELDS)
    assert report.verdict == "unusable"


def test_comparison_reports_fields_only_the_rest_channel_returned():
    mcp = _complete_dto()
    mcp.opportunity_score = None
    rest = _complete_dto()

    diffs = verify.compare_market_dtos(mcp, rest)

    assert [d.field for d in diffs if d.kind == "missing_in_mcp"] == ["opportunity_score"]


def test_comparison_reports_value_mismatches():
    mcp = _complete_dto()
    rest = _complete_dto()
    rest.est_monthly_sales = 610

    diffs = verify.compare_market_dtos(mcp, rest)
    mismatch = [d for d in diffs if d.kind == "value_mismatch"]

    assert len(mismatch) == 1
    assert mismatch[0].field == "est_monthly_sales"
    assert mismatch[0].mcp_value == 540
    assert mismatch[0].rest_value == 610


def test_comparison_ignores_raw_data_and_transport_noise():
    mcp = _complete_dto()
    rest = _complete_dto()
    mcp.raw_data = {"asin_detail": {"a": 1}}
    rest.raw_data = {"asin_detail": {"b": 2}, "seller_sprite_diagnostics": []}

    assert verify.compare_market_dtos(mcp, rest) == []


def test_identical_dtos_compare_clean():
    assert verify.compare_market_dtos(_complete_dto(), _complete_dto()) == []


def test_report_renders_the_verdict_and_missing_fields():
    dto = _complete_dto()
    dto.top10_revenue_share = None

    text = verify.format_report(verify.check_market_fields(dto), diffs=None)

    assert "unusable" in text
    assert "top10_revenue_share" in text


def test_report_never_prints_the_api_key():
    text = verify.format_report(verify.check_market_fields(_complete_dto()), diffs=None)

    assert "secret-key" not in text.lower()
