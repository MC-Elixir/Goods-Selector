"""Deterministic packaging evidence from a reviewed SellerSprite panel."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from crawlers._amazon_extractors import _parse_dimensions_from_text, _parse_weight_from_text
from schemas.sourcing import EvidenceStatus, FieldEvidence


def parse_packaging_panel(text: str, *, asin: str, source_ref: str) -> dict:
    """Accept only explicit package labels on the matching Amazon US ASIN."""
    url = urlparse(source_ref)
    if url.hostname not in {"amazon.com", "www.amazon.com"} or not re.match(
        rf"^/dp/{re.escape(asin)}(?:/|$)", url.path
    ):
        raise ValueError("packaging evidence ASIN mismatch")
    if not re.search(rf"\bASIN\s*[:：]\s*{re.escape(asin)}\b", text, re.I):
        return {}

    # Keep only the labelled physical values, not the surrounding account UI.
    dimensions = re.search(
        r"包装尺寸\s*[:：]\s*([\d.]+\s*[x×]\s*[\d.]+\s*[x×]\s*[\d.]+\s*(?:inches?|cm|centimeters?))",
        text, re.I,
    )
    weight = re.search(
        r"包装重量\s*[:：]\s*([\d.]+\s*(?:pounds?|lbs?|ounces?|oz|kilograms?|kg|grams?|g)\b)",
        text, re.I,
    )
    observed = {
        "package_dimensions": dimensions.group(1) if dimensions else "",
        "package_weight_kg": weight.group(1) if weight else "",
    }
    values = {
        "package_dimensions": _parse_dimensions_from_text(observed["package_dimensions"].replace("×", "x")),
        "package_weight_kg": _parse_weight_from_text(observed["package_weight_kg"]),
    }
    now = datetime.now(timezone.utc)
    fields = {}
    for name, value in values.items():
        numbers = value if isinstance(value, tuple) else (value,)
        if any(n is None or not math.isfinite(n) or n <= 0 for n in numbers):
            value = None
        fields[name] = FieldEvidence(
            value=value,
            status=EvidenceStatus.EXTRACTED if value is not None else EvidenceStatus.MISSING,
            source_provider="sellersprite_browser_extension",
            source_type="product_packaging",
            source_ref=f"https://www.amazon.com/dp/{asin}",
            observed_at=now,
            expires_at=now + timedelta(days=1),
            confidence=0.9 if value is not None else 0.0,
            extraction_method="sellersprite_explicit_package_label",
        ).model_dump(mode="json")
    return {"asin": asin, "fields": fields, "observed_text": observed}


def apply_packaging_evidence(product, payload: dict) -> None:
    """Hydrate shipping inputs only from a complete, current package bundle."""
    if not payload or payload.get("asin") != product.asin:
        return
    fields = {
        name: FieldEvidence.model_validate(value)
        for name, value in payload.get("fields", {}).items()
    }
    raw = product.raw_data
    raw["logistics_evidence"] = payload
    raw["logistics_evidence"]["applied"] = False
    # A partial package bundle must not mix unpacked item measurements with
    # package measurements. Original item facts remain in field_evidence.
    product.weight_kg = product.length_cm = product.width_cm = product.height_cm = None
    required = ("package_dimensions", "package_weight_kg")
    if not all(
        name in fields
        and fields[name].effective_status() in {EvidenceStatus.EXTRACTED, EvidenceStatus.VERIFIED}
        and fields[name].value is not None
        for name in required
    ):
        return
    dims = fields["package_dimensions"].value
    weight = fields["package_weight_kg"].value
    if not isinstance(dims, (list, tuple)) or len(dims) != 3:
        return
    try:
        values = [float(weight), *(float(value) for value in dims)]
    except (TypeError, ValueError):
        return
    if not all(math.isfinite(value) and value > 0 for value in values):
        return
    product.weight_kg, product.length_cm, product.width_cm, product.height_cm = values
    raw["logistics_evidence"]["applied"] = True
    # Preserve original item evidence; packaging has its own field names.
    raw.setdefault("field_evidence", {}).update(payload["fields"])
    raw["package_dimensions"] = list(dims)
    raw["package_weight_kg"] = weight
