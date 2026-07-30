"""Null-safe normalization for SellerSprite reverse-keyword exports."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from agent.sellersprite_models import SellerSpriteContext
from agent.sellersprite_policy import normalize_sellersprite_error_code
from agent.tools.browser_downloads import ALLOWED_EXPORT_SUFFIXES, DownloadedArtifact, DownloadError

_SCHEMA_VERSION = "1.0"
_SOURCE_PROVIDER = "sellersprite"
_SOURCE_TYPE = "browser_extension_export"
_MEASUREMENT_KIND = "vendor_estimate"
_NULL_TEXT = frozenset({"", "-", "--", "n/a", "na", "none", "null", "—"})
_NUMERIC_FIELDS = (
    "search_volume",
    "purchase_volume",
    "purchase_rate",
    "competing_products",
    "spr",
    "organic_rank",
    "ad_rank",
)


def _header_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ").strip().casefold())


_HEADER_ALIASES = {
    "keyword": "keyword",
    "keywords": "keyword",
    "search term": "keyword",
    "search terms": "keyword",
    "关键词": "keyword",
    "关键字": "keyword",
    "搜索词": "keyword",
    "流量词": "keyword",
    "search volume": "search_volume",
    "monthly search volume": "search_volume",
    "searches": "search_volume",
    "搜索量": "search_volume",
    "月搜索量": "search_volume",
    "purchase volume": "purchase_volume",
    "monthly purchase volume": "purchase_volume",
    "purchases": "purchase_volume",
    "购买量": "purchase_volume",
    "月购买量": "purchase_volume",
    "purchase rate": "purchase_rate",
    "conversion rate": "purchase_rate",
    "购买率": "purchase_rate",
    "转化率": "purchase_rate",
    "competing products": "competing_products",
    "competing product": "competing_products",
    "product count": "competing_products",
    "competition": "competing_products",
    "竞品数": "competing_products",
    "竞争商品数": "competing_products",
    "商品数": "competing_products",
    "spr": "spr",
    "organic rank": "organic_rank",
    "natural rank": "organic_rank",
    "自然排名": "organic_rank",
    "ad rank": "ad_rank",
    "sponsored rank": "ad_rank",
    "广告排名": "ad_rank",
    "trend": "trend",
    "search trend": "trend",
    "趋势": "trend",
    "搜索趋势": "trend",
    # Duration is retained as an optional, explicitly derived field when an
    # export supplies it.  It does not turn an otherwise missing metric into a
    # made-up value.
    "duration": "duration",
    "time period": "duration",
    "period": "duration",
    "时长": "duration",
    "周期": "duration",
}
_CURRENCY_TOKEN_RE = re.compile(r"\b(?:usd|cny|rmb|eur|gbp|jpy|cad|aud|hkd)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"^(?P<sign>[+-]?)(?P<number>(?:\d+(?:\.\d*)?|\.\d+))(?P<unit>[kKmMbB]|万|千|百万|亿)?(?P<plus>\+)?$"
)
_DURATION_TOKEN_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>days?|day|d|hours?|hour|h|minutes?|minute|mins?|min|m|seconds?|second|secs?|sec|s|天|小时|时|分钟|分|秒)"
)
_DURATION_UNIT_SECONDS = {
    "d": 86_400,
    "day": 86_400,
    "days": 86_400,
    "天": 86_400,
    "h": 3_600,
    "hour": 3_600,
    "hours": 3_600,
    "小时": 3_600,
    "时": 3_600,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "分钟": 60,
    "分": 60,
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "秒": 1,
}


class SellerSpriteImportError(ValueError):
    """A terminal, safe-to-report import error."""

    def __init__(self, error_code: str) -> None:
        self.error_code = normalize_sellersprite_error_code(error_code)
        super().__init__(self.error_code)


@dataclass(frozen=True)
class ImportedSellerSpriteExport:
    """Parsed export plus the metadata later persisted as an import manifest."""

    context: SellerSpriteContext
    artifact: DownloadedArtifact
    headers: list[str]
    rows: list[dict[str, Any]]
    raw_rows: list[dict[str, Any]]
    quality_summary: dict[str, int]
    source_provider: str = _SOURCE_PROVIDER
    source_type: str = _SOURCE_TYPE
    measurement_kind: str = _MEASUREMENT_KIND
    schema_version: str = _SCHEMA_VERSION
    status: str = "imported"

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def first_20_rows(self) -> list[dict[str, Any]]:
        return self.rows[:20]


def import_sellersprite_export(
    context: SellerSpriteContext,
    artifact: DownloadedArtifact,
) -> ImportedSellerSpriteExport:
    """Read one hash-addressed CSV/XLSX SellerSprite keyword export.

    Legacy ``.xls`` downloads are allow-listed by the observer so they can be
    reported accurately, but this runtime deliberately rejects them here:
    ``openpyxl`` cannot read BIFF ``.xls`` and no approved reader is present.
    """

    _validate_artifact_integrity(artifact)
    if artifact.size_bytes <= 0:
        raise SellerSpriteImportError("INVALID_EXPORT")

    suffix = artifact.path.suffix.lower()
    if suffix not in ALLOWED_EXPORT_SUFFIXES or suffix == ".xls":
        raise SellerSpriteImportError("INVALID_EXPORT")

    try:
        if suffix == ".csv":
            headers, source_rows = _read_csv(artifact.path)
        elif suffix == ".xlsx":
            headers, source_rows = _read_xlsx(artifact.path)
        else:  # Defensive future-proofing if the allow-list changes.
            raise SellerSpriteImportError("INVALID_EXPORT")
        canonical_headers = _validate_headers(headers)
        return _normalize_import(context, artifact, headers, canonical_headers, source_rows)
    except SellerSpriteImportError:
        raise
    except (csv.Error, OSError, UnicodeError, ValueError, InvalidFileException) as exc:
        raise SellerSpriteImportError("INVALID_EXPORT") from exc


def _validate_artifact_integrity(artifact: DownloadedArtifact) -> None:
    try:
        current = DownloadedArtifact.from_path(artifact.path)
    except DownloadError as exc:
        raise SellerSpriteImportError("INVALID_EXPORT") from exc
    if current.sha256 != artifact.sha256 or current.size_bytes != artifact.size_bytes:
        raise SellerSpriteImportError("INVALID_EXPORT")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise SellerSpriteImportError("INVALID_EXPORT")
            headers = [str(header) if header is not None else "" for header in reader.fieldnames]
            rows: list[dict[str, Any]] = []
            for row in reader:
                if None in row:
                    raise SellerSpriteImportError("INVALID_EXPORT")
                rows.append({header: _json_value(row.get(header)) for header in headers})
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SellerSpriteImportError("INVALID_EXPORT") from exc
    return headers, rows


def _read_xlsx(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    workbook = None
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        header_values = next(values, None)
        if header_values is None:
            raise SellerSpriteImportError("INVALID_EXPORT")
        headers = [str(header) if header is not None else "" for header in header_values]
        rows: list[dict[str, Any]] = []
        for source_row in values:
            if len(source_row) > len(headers) and any(value is not None for value in source_row[len(headers) :]):
                raise SellerSpriteImportError("INVALID_EXPORT")
            rows.append(
                {
                    header: _json_value(source_row[index]) if index < len(source_row) else None
                    for index, header in enumerate(headers)
                }
            )
    except SellerSpriteImportError:
        raise
    except Exception as exc:
        # OOXML is untrusted input.  ``openpyxl`` and its XML/zip backends can
        # surface different exception classes for malformed members, missing
        # required parts, or parser failures; none may escape to the API.
        raise SellerSpriteImportError("INVALID_EXPORT") from exc
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                # Closing a partially initialized workbook must not turn a
                # safe import failure into an unhandled server exception.
                pass
    return headers, rows


def _validate_headers(headers: list[str]) -> dict[str, str]:
    if not headers or any(not header.strip() for header in headers):
        raise SellerSpriteImportError("INVALID_EXPORT")

    canonical_headers: dict[str, str] = {}
    for header in headers:
        canonical = _HEADER_ALIASES.get(_header_key(header))
        if canonical is None:
            continue
        if canonical in canonical_headers:
            raise SellerSpriteImportError("INVALID_EXPORT")
        canonical_headers[canonical] = header
    if "keyword" not in canonical_headers:
        raise SellerSpriteImportError("INVALID_EXPORT")
    return canonical_headers


def _normalize_import(
    context: SellerSpriteContext,
    artifact: DownloadedArtifact,
    headers: list[str],
    canonical_headers: dict[str, str],
    source_rows: Iterable[dict[str, Any]],
) -> ImportedSellerSpriteExport:
    rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    seen_keywords: set[str] = set()
    duplicate_keyword_count = 0
    missing_keyword_count = 0
    empty_row_count = 0

    for source_row in source_rows:
        raw_payload = {header: _json_value(source_row.get(header)) for header in headers}
        if all(value is None for value in raw_payload.values()):
            empty_row_count += 1
            continue
        raw_rows.append(raw_payload)
        row = _empty_normalized_row(raw_payload)
        for canonical, header in canonical_headers.items():
            _assign_normalized_value(row, canonical, raw_payload[header])

        keyword = row["keyword"]
        if keyword is None:
            missing_keyword_count += 1
            continue
        dedupe_key = keyword.casefold()
        if dedupe_key in seen_keywords:
            duplicate_keyword_count += 1
            continue
        seen_keywords.add(dedupe_key)
        rows.append(row)

    if not rows:
        raise SellerSpriteImportError("INVALID_EXPORT")

    return ImportedSellerSpriteExport(
        context=context,
        artifact=artifact,
        headers=list(headers),
        rows=rows,
        raw_rows=raw_rows,
        quality_summary={
            "source_row_count": len(raw_rows),
            "normalized_row_count": len(rows),
            "duplicate_keyword_count": duplicate_keyword_count,
            "missing_keyword_count": missing_keyword_count,
            "empty_row_count": empty_row_count,
            "header_count": len(headers),
        },
    )


def _empty_normalized_row(raw_payload: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "keyword": None,
        "trend": None,
        "trend_lower_bound": None,
        "duration": None,
        "duration_seconds": None,
        "measurement_kind": _MEASUREMENT_KIND,
        "source_provider": _SOURCE_PROVIDER,
        "source_type": _SOURCE_TYPE,
        "raw_payload": raw_payload,
    }
    for field in _NUMERIC_FIELDS:
        row[field] = None
        row[f"{field}_lower_bound"] = None
    return row


def _assign_normalized_value(row: dict[str, Any], canonical: str, value: Any) -> None:
    if canonical == "keyword":
        row[canonical] = _normalize_keyword(value)
        return
    if canonical in _NUMERIC_FIELDS:
        exact, lower_bound = _parse_numeric(value)
        row[canonical] = exact
        row[f"{canonical}_lower_bound"] = lower_bound
        return
    if canonical == "trend":
        duration_seconds = _parse_duration_seconds(value)
        if duration_seconds is not None:
            row[canonical] = _normalized_text(value)
            row["trend_duration_seconds"] = duration_seconds
            return
        exact, lower_bound = _parse_numeric(value)
        if exact is not None or lower_bound is not None:
            row[canonical] = exact
            row["trend_lower_bound"] = lower_bound
        else:
            row[canonical] = _normalized_text(value)
        return
    if canonical == "duration":
        row[canonical] = _normalized_text(value)
        row["duration_seconds"] = _parse_duration_seconds(value)


def _normalize_keyword(value: Any) -> str | None:
    text = _normalized_text(value)
    return re.sub(r"\s+", " ", text) if text is not None else None


def _normalized_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.casefold() in _NULL_TEXT:
        return None
    return text


def _parse_numeric(value: Any) -> tuple[int | float | None, int | float | None]:
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        return _number_or_none(value), None

    text = _normalized_text(value)
    if text is None:
        return None, None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    text = _CURRENCY_TOKEN_RE.sub("", text)
    text = text.replace("￥", "").replace("¥", "").replace("$", "")
    text = text.replace("€", "").replace("£", "").replace("₹", "")
    text = text.replace("%", "").replace(",", "").replace(" ", "")
    match = _NUMBER_RE.fullmatch(text)
    if match is None:
        return None, None

    number = float(f"{match.group('sign')}{match.group('number')}")
    unit = (match.group("unit") or "").casefold()
    multiplier = {
        "": 1,
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "万": 10_000,
        "千": 1_000,
        "百万": 1_000_000,
        "亿": 100_000_000,
    }[unit]
    normalized = _number_or_none(number * multiplier)
    if normalized is None:
        return None, None
    if match.group("plus"):
        return None, normalized
    return normalized, None


def _number_or_none(value: int | float) -> int | float | None:
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    return int(value) if float(value).is_integer() else value


def _parse_duration_seconds(value: Any) -> int | float | None:
    text = _normalized_text(value)
    if text is None:
        return None
    total = 0.0
    position = 0
    matched = False
    for match in _DURATION_TOKEN_RE.finditer(text):
        if text[position : match.start()].strip():
            return None
        matched = True
        unit = match.group("unit")
        normalized_unit = unit.casefold() if unit.isascii() else unit
        total += float(match.group("number")) * _DURATION_UNIT_SECONDS[normalized_unit]
        position = match.end()
    if not matched or text[position:].strip():
        return None
    return _number_or_none(total)


def _json_value(value: Any) -> Any:
    """Keep source values serializable without turning blanks into false data."""

    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
