"""Null-safe normalization for SellerSprite competitor / market exports.

The «查竞品 / 选市场» export is a product-level table.  Each row carries a
seller (or brand) identity plus price, rating, reviews, launch date, monthly
sales and monthly revenue.  This importer mirrors the reverse-keyword importer:
it never fabricates a missing metric, it validates the file it is handed, and
it exposes both a normalized projection (for the rules engine) and the raw
payload (for the audit manifest).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from analyzers.seller_research import CompetitorRow
from agent.tools.browser_downloads import ALLOWED_EXPORT_SUFFIXES, DownloadError, DownloadedArtifact


_SCHEMA_VERSION = "1.0"
_SOURCE_PROVIDER = "sellersprite"
_SOURCE_TYPE = "browser_extension_export"
_MEASUREMENT_KIND = "vendor_estimate"
_NULL_TEXT = frozenset({"", "-", "--", "n/a", "na", "none", "null", "—"})

_TEXT_FIELDS = ("seller", "asin", "title", "brand", "launch_date")
_NUMERIC_FIELDS = (
    "price",
    "rating",
    "review_count",
    "monthly_sales",
    "monthly_revenue",
    "seller_product_count",
)


class CompetitorImportError(ValueError):
    """A terminal, safe-to-report import error."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code if error_code in _SAFE_CODES else "INVALID_EXPORT"
        super().__init__(self.error_code)


_SAFE_CODES = frozenset({"INVALID_EXPORT", "EMPTY_EXPORT", "MISSING_IDENTITY"})


def _header_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ").strip().casefold())


# Canonical field <- observed header text (EN + 中文), tuned to the SellerSprite
# competitor / market exports.  Unknown columns are preserved in the raw payload
# but never coerced into a normalized metric.
_HEADER_ALIASES = {
    # seller identity
    "seller": "seller", "sellers": "seller", "store": "seller", "store name": "seller",
    "seller name": "seller", "卖家": "seller", "卖家名称": "seller", "店铺": "seller",
    "店铺名称": "seller", "商家": "seller",
    # brand
    "brand": "brand", "brand name": "brand", "品牌": "brand", "品牌名称": "brand",
    # asin
    "asin": "asin", "商品asin": "asin", "product asin": "asin", "parent asin": "asin",
    # title
    "title": "title", "product title": "title", "product name": "title",
    "商品标题": "title", "标题": "title", "产品名称": "title", "商品名称": "title",
    # price
    "price": "price", "avg price": "price", "average price": "price",
    "价格": "price", "售价": "price", "均价": "price", "平均价格": "price",
    # rating
    "rating": "rating", "ratings": "rating", "star": "rating", "stars": "rating",
    "review rating": "rating", "评分": "rating", "星级": "rating", "星评": "rating",
    # review count
    "reviews": "review_count", "review count": "review_count", "review counts": "review_count",
    "num reviews": "review_count", "ratings count": "review_count",
    "评论数": "review_count", "评价数": "review_count", "评分数": "review_count", "评论数量": "review_count",
    # launch date
    "launch date": "launch_date", "listing date": "launch_date",
    "date first available": "launch_date", "first available": "launch_date",
    "上架时间": "launch_date", "上架日期": "launch_date", "首次上架": "launch_date", "上架": "launch_date",
    # monthly sales
    "monthly sales": "monthly_sales", "sales": "monthly_sales", "units sold": "monthly_sales",
    "monthly units": "monthly_sales", "月销量": "monthly_sales", "销量": "monthly_sales",
    "月销": "monthly_sales", "月销售量": "monthly_sales",
    # monthly revenue
    "monthly revenue": "monthly_revenue", "revenue": "monthly_revenue", "sales revenue": "monthly_revenue",
    "月销售额": "monthly_revenue", "销售额": "monthly_revenue", "月营收": "monthly_revenue", "月销额": "monthly_revenue",
    # seller product count
    "seller products": "seller_product_count", "seller product count": "seller_product_count",
    "product count": "seller_product_count", "products": "seller_product_count",
    "卖家商品数": "seller_product_count", "在售商品数": "seller_product_count",
    "商品数": "seller_product_count", "在售数": "seller_product_count",
}
_CURRENCY_TOKEN_RE = re.compile(r"\b(?:usd|cny|rmb|eur|gbp|jpy|cad|aud|hkd)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"^(?P<sign>[+-]?)(?P<number>(?:\d+(?:\.\d*)?|\.\d+))(?P<unit>[kKmMbB]|万|千|百万|亿)?(?P<plus>\+)?$"
)


@dataclass(frozen=True)
class ImportedCompetitorExport:
    """Parsed competitor export plus metadata later persisted as a manifest."""

    niche_label: str
    keyword: str
    marketplace: str
    artifact: DownloadedArtifact
    headers: list[str]
    competitor_rows: list[CompetitorRow]
    normalized_rows: list[dict[str, Any]]
    raw_rows: list[dict[str, Any]]
    quality_summary: dict[str, int]
    source_provider: str = _SOURCE_PROVIDER
    source_type: str = _SOURCE_TYPE
    measurement_kind: str = _MEASUREMENT_KIND
    schema_version: str = _SCHEMA_VERSION
    status: str = "imported"

    @property
    def row_count(self) -> int:
        return len(self.normalized_rows)


def import_competitor_export(
    path: str | Path,
    *,
    niche_label: str = "",
    keyword: str = "",
    marketplace: str = "US",
) -> ImportedCompetitorExport:
    """Read one CSV/XLSX SellerSprite competitor export into normalized rows."""

    artifact = _artifact_from_path(path)
    if artifact.size_bytes <= 0:
        raise CompetitorImportError("EMPTY_EXPORT")

    suffix = artifact.path.suffix.lower()
    if suffix not in ALLOWED_EXPORT_SUFFIXES or suffix == ".xls":
        raise CompetitorImportError("INVALID_EXPORT")

    try:
        if suffix == ".csv":
            headers, source_rows = _read_csv(artifact.path)
        elif suffix == ".xlsx":
            headers, source_rows = _read_xlsx(artifact.path)
        else:  # Defensive future-proofing if the allow-list changes.
            raise CompetitorImportError("INVALID_EXPORT")
        canonical_headers = _validate_headers(headers)
        return _normalize(
            artifact,
            headers,
            canonical_headers,
            source_rows,
            niche_label=str(niche_label or "").strip(),
            keyword=str(keyword or "").strip(),
            marketplace=str(marketplace or "US").strip().upper() or "US",
        )
    except CompetitorImportError:
        raise
    except (csv.Error, OSError, UnicodeError, ValueError, InvalidFileException) as exc:
        raise CompetitorImportError("INVALID_EXPORT") from exc


def _artifact_from_path(path: str | Path) -> DownloadedArtifact:
    try:
        return DownloadedArtifact.from_path(Path(path))
    except DownloadError as exc:
        raise CompetitorImportError("INVALID_EXPORT") from exc


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise CompetitorImportError("INVALID_EXPORT")
            headers = [str(header) if header is not None else "" for header in reader.fieldnames]
            rows: list[dict[str, Any]] = []
            for row in reader:
                if None in row:
                    raise CompetitorImportError("INVALID_EXPORT")
                rows.append({header: _json_value(row.get(header)) for header in headers})
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CompetitorImportError("INVALID_EXPORT") from exc
    return headers, rows


def _read_xlsx(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    workbook = None
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        header_values = next(values, None)
        if header_values is None:
            raise CompetitorImportError("INVALID_EXPORT")
        headers = [str(header) if header is not None else "" for header in header_values]
        rows: list[dict[str, Any]] = []
        for source_row in values:
            rows.append(
                {
                    header: _json_value(source_row[index]) if index < len(source_row) else None
                    for index, header in enumerate(headers)
                }
            )
    except CompetitorImportError:
        raise
    except Exception as exc:
        raise CompetitorImportError("INVALID_EXPORT") from exc
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass
    return headers, rows


def _validate_headers(headers: list[str]) -> dict[str, str]:
    if not headers or any(not header.strip() for header in headers):
        raise CompetitorImportError("INVALID_EXPORT")

    canonical_headers: dict[str, str] = {}
    for header in headers:
        canonical = _HEADER_ALIASES.get(_header_key(header))
        if canonical is None:
            continue
        # First mapped header wins; later duplicate synonyms are ignored rather
        # than rejected, since real exports sometimes repeat a display label.
        canonical_headers.setdefault(canonical, header)
    if "seller" not in canonical_headers and "brand" not in canonical_headers:
        # Without a seller or brand column there is no identity to aggregate on.
        raise CompetitorImportError("MISSING_IDENTITY")
    return canonical_headers


def _normalize(
    artifact: DownloadedArtifact,
    headers: list[str],
    canonical_headers: dict[str, str],
    source_rows: Iterable[dict[str, Any]],
    *,
    niche_label: str,
    keyword: str,
    marketplace: str,
) -> ImportedCompetitorExport:
    normalized_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    competitor_rows: list[CompetitorRow] = []
    empty_row_count = 0
    missing_identity_count = 0

    for source_row in source_rows:
        raw_payload = {header: _json_value(source_row.get(header)) for header in headers}
        if all(value is None for value in raw_payload.values()):
            empty_row_count += 1
            continue
        row = _empty_row()
        for canonical, header in canonical_headers.items():
            _assign(row, canonical, raw_payload[header])

        identity = row["seller"] or row["brand"]
        if not identity:
            missing_identity_count += 1
            continue
        # Seller identity falls back to brand when the export only labels brand.
        if not row["seller"]:
            row["seller"] = row["brand"]

        raw_rows.append(raw_payload)
        normalized_rows.append(row)
        competitor_rows.append(_to_competitor_row(row, raw_payload))

    if not normalized_rows:
        raise CompetitorImportError("EMPTY_EXPORT")

    quality_summary = {
        "source_row_count": len(raw_rows) + empty_row_count + missing_identity_count,
        "normalized_row_count": len(normalized_rows),
        "empty_row_count": empty_row_count,
        "missing_identity_count": missing_identity_count,
        "header_count": len(headers),
    }
    return ImportedCompetitorExport(
        niche_label=niche_label,
        keyword=keyword,
        marketplace=marketplace,
        artifact=artifact,
        headers=list(headers),
        competitor_rows=competitor_rows,
        normalized_rows=normalized_rows,
        raw_rows=raw_rows,
        quality_summary=quality_summary,
    )


def competitor_rows_from_normalized(rows: list[dict[str, Any]]) -> list[CompetitorRow]:
    """Rebuild typed rows from a persisted normalized payload."""
    return [_to_competitor_row(row, row.get("raw_payload") or {}) for row in rows if isinstance(row, dict)]


def _to_competitor_row(row: dict[str, Any], raw_payload: dict[str, Any]) -> CompetitorRow:
    return CompetitorRow(
        seller=row.get("seller"),
        asin=row.get("asin"),
        title=row.get("title"),
        brand=row.get("brand"),
        price=row.get("price"),
        rating=row.get("rating"),
        review_count=_as_int(row.get("review_count")),
        launch_date=row.get("launch_date"),
        monthly_sales=_as_int(row.get("monthly_sales")),
        monthly_revenue=row.get("monthly_revenue"),
        seller_product_count=_as_int(row.get("seller_product_count")),
        raw=raw_payload if isinstance(raw_payload, dict) else {},
    )


def _empty_row() -> dict[str, Any]:
    row: dict[str, Any] = {field: None for field in (*_TEXT_FIELDS, *_NUMERIC_FIELDS)}
    row["measurement_kind"] = _MEASUREMENT_KIND
    row["source_provider"] = _SOURCE_PROVIDER
    row["source_type"] = _SOURCE_TYPE
    return row


def _assign(row: dict[str, Any], canonical: str, value: Any) -> None:
    if canonical == "launch_date":
        row[canonical] = _normalize_date(value)
        return
    if canonical in _TEXT_FIELDS:
        row[canonical] = _normalized_text(value)
        return
    if canonical in _NUMERIC_FIELDS:
        row[canonical] = _parse_numeric(value)


def _normalized_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.casefold() in _NULL_TEXT:
        return None
    return re.sub(r"\s+", " ", text)


def _normalize_date(value: Any) -> str | None:
    text = _normalized_text(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m", "%Y年%m月%d日", "%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        # Keep the trimmed original so downstream parsing can still try, rather
        # than discarding a real (if unusual) launch date.
        return text


def _parse_numeric(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _number_or_none(value)

    text = _normalized_text(value)
    if text is None:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    text = _CURRENCY_TOKEN_RE.sub("", text)
    for token in ("￥", "¥", "$", "€", "£", "₹", "%", ",", " "):
        text = text.replace(token, "")
    match = _NUMBER_RE.fullmatch(text)
    if match is None:
        return None

    number = float(f"{match.group('sign')}{match.group('number')}")
    unit = (match.group("unit") or "").casefold()
    multiplier = {
        "": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000,
        "万": 10_000, "千": 1_000, "百万": 1_000_000, "亿": 100_000_000,
    }[unit]
    return _number_or_none(number * multiplier)


def _number_or_none(value: int | float) -> int | float | None:
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else round(number, 4)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == value and value not in (float("inf"), float("-inf")):
        return int(value)
    return None


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)
