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
    assert payload["rejection_reasons"] == ["legacy_insufficient", "missing_logistics_basis"]


def test_excel_preserves_legacy_headers_then_appends_evidence(tmp_path):
    path = export_excel([_record()], output_path=tmp_path / "evidence.xlsx")
    sheet = openpyxl.load_workbook(path).active
    headers = [cell.value for cell in sheet[1]]
    assert headers[:3] == ["ASIN", "标题", "品牌"]
    assert headers[37:45] == [
        "Schema版本", "Run Ref", "查询计划与命中率", "匹配证据", "推荐状态",
        "推荐原因", "证据拒绝原因", "人工核验任务",
    ]
    assert headers[45:] == [
        "包装重量(kg)", "包装长(cm)", "包装宽(cm)", "包装高(cm)",
        "包装证据来源", "包装证据采集时间", "包装原文", "物流缺失字段",
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


def test_mock_search_identity_does_not_leak_to_any_export(tmp_path):
    record = _record()
    record.sourcing_slice.query_attempts = [{
        "result_count": 0, "relevant_count": 0, "result_refs": [], "mock_filtered_count": 1,
        "error_code": "NO_RESULTS", "hit_rate": 0.0,
    }]
    record.sourcing_slice.suppliers = []
    json_text = export_json([record], tmp_path / "safe.json").read_text(encoding="utf-8")
    excel = export_excel([record], tmp_path / "safe.xlsx")
    excel_text = " ".join(str(c.value) for row in openpyxl.load_workbook(excel).active for c in row)
    markdown = export_markdown([record], tmp_path / "md")[0].read_text(encoding="utf-8")
    for content in (json_text, excel_text, markdown):
        assert "SECRET-MOCK" not in content
        assert "SECRET TITLE" not in content
        assert "https://mock/SECRET" not in content


def test_formal_pipeline_raw_sourcing_evidence_is_exported_without_slice_attribute(tmp_path):
    record = _record()
    del record.sourcing_slice
    record.product.raw_data["sourcing_evidence"] = {
        "schema_version": "target-sourcing-evidence-v1",
        "run_ref": "run:88",
        "query_attempts": [{"status": "not_started", "result_count": None}],
        "evaluated_matches": [{
            "supplier_ref": "offer:factory-1",
            "decision": "keep",
            "overall_confidence": 0.91,
        }],
        "recommendation": {
            "status": "needs_manual_review",
            "recommendation_reasons": ["strict_supplier_match_passed"],
            "rejection_reasons": ["missing_market_evidence"],
            "manual_verification_tasks": ["evaluate_market"],
        },
    }

    payload = json.loads(
        export_json([record], output_path=tmp_path / "formal.json").read_text(encoding="utf-8")
    )[0]

    assert payload["schema_version"] == "target-sourcing-evidence-v1"
    assert payload["run_ref"] == "run:88"
    assert payload["query_plan_and_hit_rates"][0]["result_count"] is None
    assert payload["match_evidence"][0]["decision"] == "keep"
    assert payload["recommendation_status"] == "needs_manual_review"
    assert "missing_market_evidence" in payload["rejection_reasons"]
