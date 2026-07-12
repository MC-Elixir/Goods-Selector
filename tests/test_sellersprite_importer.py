from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from agent.sellersprite_models import SellerSpriteContext
from agent.tools.browser_downloads import DownloadedArtifact
from agent.tools.sellersprite_importer import (
    SellerSpriteImportError,
    import_sellersprite_export,
)


def make_artifact(tmp_path: Path, content: str, name: str = "keywords.csv") -> DownloadedArtifact:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return DownloadedArtifact.from_path(path)


def test_import_preserves_missing_and_compact_lower_bound(tmp_path):
    artifact = make_artifact(
        tmp_path,
        "Keyword,Search Volume,Purchase Rate\numbrella,10K+,\n",
    )

    imported = import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    row = imported.rows[0]
    assert row["keyword"] == "umbrella"
    assert row["search_volume"] is None
    assert row["search_volume_lower_bound"] == 10000
    assert row["purchase_rate"] is None
    assert row["measurement_kind"] == "vendor_estimate"
    assert imported.source_type == "browser_extension_export"
    assert imported.status == "imported"


def test_import_keeps_unknown_columns_in_raw_payload_and_deduplicates_keyword_rows(tmp_path):
    artifact = make_artifact(
        tmp_path,
        "Keyword,Search Volume,Unmapped Column\n"
        " Patio   Umbrella ,1200,one\n"
        "patio umbrella,1300,two\n",
    )

    imported = import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    assert len(imported.rows) == 1
    assert imported.rows[0]["keyword"] == "Patio Umbrella"
    assert imported.rows[0]["search_volume"] == 1200
    assert imported.rows[0]["raw_payload"]["Unmapped Column"] == "one"
    assert len(imported.raw_rows) == 2
    assert imported.raw_rows[1]["Unmapped Column"] == "two"
    assert imported.quality_summary["duplicate_keyword_count"] == 1


def test_import_parses_currency_percent_and_duration_conservatively(tmp_path):
    artifact = make_artifact(
        tmp_path,
        "Keyword,Search Volume,Purchase Rate,Duration\n"
        'umbrella,"$1,200.50",12.5%,2d 3h 15m\n',
    )

    imported = import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    row = imported.rows[0]
    assert row["search_volume"] == 1200.5
    assert row["purchase_rate"] == 12.5
    assert row["duration"] == "2d 3h 15m"
    assert row["duration_seconds"] == 184500


def test_import_preserves_compact_chinese_metric_as_a_lower_bound(tmp_path):
    artifact = make_artifact(tmp_path, "关键词,搜索量\n雨伞,1百万+\n")

    imported = import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    assert imported.rows[0]["search_volume"] is None
    assert imported.rows[0]["search_volume_lower_bound"] == 1_000_000


def test_import_exposes_original_headers_for_csv_and_xlsx(tmp_path):
    csv_artifact = make_artifact(tmp_path, "Keyword,Search Volume\numbrella,1\n")
    csv_import = import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), csv_artifact)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["关键词", "购买量"])
    sheet.append(["雨伞", 42])
    xlsx_path = tmp_path / "keywords.xlsx"
    workbook.save(xlsx_path)
    xlsx_artifact = DownloadedArtifact.from_path(xlsx_path)
    xlsx_import = import_sellersprite_export(
        SellerSpriteContext.create("B00Q7OAN50"), xlsx_artifact
    )

    assert csv_import.headers == ["Keyword", "Search Volume"]
    assert xlsx_import.headers == ["关键词", "购买量"]
    assert xlsx_import.rows[0]["keyword"] == "雨伞"
    assert xlsx_import.rows[0]["purchase_volume"] == 42


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("empty.csv", ""),
        ("no_keyword.csv", "Search Volume\n100\n"),
    ],
)
def test_import_rejects_empty_or_schema_invalid_csv_exports(tmp_path, name, content):
    artifact = make_artifact(tmp_path, content, name)

    with pytest.raises(SellerSpriteImportError, match="INVALID_EXPORT") as error:
        import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    assert error.value.error_code == "INVALID_EXPORT"


def test_import_rejects_unreadable_xlsx(tmp_path):
    artifact = make_artifact(tmp_path, "not a workbook", "broken.xlsx")

    with pytest.raises(SellerSpriteImportError, match="INVALID_EXPORT") as error:
        import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    assert error.value.error_code == "INVALID_EXPORT"


def test_import_rejects_legacy_xls_without_a_supported_runtime_reader(tmp_path):
    artifact = make_artifact(tmp_path, "not a legacy workbook", "legacy.xls")

    with pytest.raises(SellerSpriteImportError, match="INVALID_EXPORT") as error:
        import_sellersprite_export(SellerSpriteContext.create("B00Q7OAN50"), artifact)

    assert error.value.error_code == "INVALID_EXPORT"
