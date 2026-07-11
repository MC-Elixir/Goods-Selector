import json
from types import SimpleNamespace

import openpyxl

from reports.exporter import export_excel, export_json, export_markdown


LEGACY_JSON_KEYS = [
    "review_status", "rejection_reasons", "product", "source_mode", "source_query",
    "source_keyword", "keyword_normalized", "source_rank", "source_warning", "profit",
    "score", "market", "suppliers",
]


def _record():
    recommendation = SimpleNamespace(
        status=SimpleNamespace(value="needs_manual_review"),
        recommendation_reasons=[], rejection_reasons=["missing_logistics_basis"],
        manual_verification_tasks=["verify_logistics_basis"],
    )
    match = SimpleNamespace(model_dump=lambda mode=None: {
        "supplier_ref": "offer:1001", "decision": "keep", "overall_confidence": 0.9,
    })
    slice_result = SimpleNamespace(
        run_ref="evidence-run", query_attempts=[{"hit_rate": 0.5}],
        accepted_matches=[match], rejected_matches=[], recommendation=recommendation,
    )
    return SimpleNamespace(
        product=SimpleNamespace(
            asin="B0EVIDENCE", title="Evidence Item", brand="Generic",
            category="Home", price=20, bsr_rank=100, rating=4.5,
            review_count=50, marketplace="US", raw_data={},
        ), profit=None, score=None, market=None, suppliers=[],
        rejection_reasons=["legacy_insufficient"], sourcing_slice=slice_result,
    )


def test_json_preserves_legacy_order_and_appends_evidence(tmp_path):
    path = export_json([_record()], output_path=tmp_path / "evidence.json")
    payload = json.loads(path.read_text(encoding="utf-8"))[0]
    assert list(payload)[:len(LEGACY_JSON_KEYS)] == LEGACY_JSON_KEYS
    assert list(payload)[len(LEGACY_JSON_KEYS):] == [
        "schema_version", "run_ref", "query_plan_and_hit_rates", "match_evidence",
        "recommendation_status", "recommendation_reasons", "evidence_rejection_reasons",
        "manual_verification_tasks",
    ]
    assert payload["review_status"] == "insufficient_evidence"
    assert payload["run_ref"] == "evidence-run"
    assert payload["recommendation_status"] == "needs_manual_review"


def test_excel_preserves_legacy_headers_then_appends_evidence(tmp_path):
    path = export_excel([_record()], output_path=tmp_path / "evidence.xlsx")
    sheet = openpyxl.load_workbook(path).active
    headers = [cell.value for cell in sheet[1]]
    assert headers[:3] == ["ASIN", "标题", "品牌"]
    assert headers[-8:] == [
        "Schema版本", "Run Ref", "查询计划与命中率", "匹配证据", "推荐状态",
        "推荐原因", "证据拒绝原因", "人工核验任务",
    ]
    row = [cell.value for cell in sheet[2]]
    assert row[headers.index("推荐状态")] == "needs_manual_review"
    assert "missing_logistics_basis" in row[headers.index("证据拒绝原因")]


def test_markdown_appends_evidence_without_losing_insufficient_status(tmp_path):
    text = export_markdown([_record()], output_dir=tmp_path)[0].read_text(encoding="utf-8")
    assert "insufficient_evidence" in text
    assert "legacy_insufficient" in text
    assert "## 证据链" in text
    assert "evidence-run" in text
    assert "needs_manual_review" in text
    assert "verify_logistics_basis" in text
