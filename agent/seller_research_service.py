"""Market-research orchestration: competitor export -> seller shortlist.

This ties the deterministic pieces together for the «锁定细分类目 → 找出适合
中小卖家研究的卖家清单» workflow:

    1. import one SellerSprite competitor / market export file
    2. aggregate + classify + score sellers with the rules engine
    3. (optional) attach a grounded AI「适合理由」to the top sellers
    4. (optional) persist the run and export Excel + JSON deliverables

The AI step is strictly non-blocking and evidence-grounded: without a model
key, or on any model error, the rule-based reasons are used instead.  No metric
is ever invented — the model only phrases the numbers it is handed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from agent.tools.competitor_importer import ImportedCompetitorExport, import_competitor_export
from analyzers.seller_research import SellerResearchItem, SellerShortlist, build_seller_shortlist
from config.settings import settings
from domain.target_categories import classify_target_category

try:
    import openai as _openai
    _HAS_OPENAI = True
except ImportError:  # pragma: no cover - optional dependency
    _openai = None  # type: ignore[assignment]
    _HAS_OPENAI = False


_AI_REASON_PROMPT = """\
你是亚马逊选品分析助手。下面是若干卖家的真实指标（来自卖家精灵导出）。
请为每个卖家写一句「是否适合中小卖家研究参考」的理由，中文，30–60 字。

严格规则：
- 只能引用给定字段（价格、评分、评论数、上架月数、月销量、月销售额、在售商品数、适合类型）。
- 不得编造任何未提供的数据，不得给出采购或投资建议。
- 聚焦“为什么适合/值得中小卖家研究”：低竞争、少而精、新品起量、评分有改进空间等。

只输出 JSON：{"reasons": {"<id>": "<一句话理由>", ...}}，id 用给定的编号。
"""

_DEFAULT_AI_MAX_ITEMS = 15


def run_seller_research_from_file(
    path: str | Path,
    *,
    niche_label: str = "",
    keyword: str = "",
    marketplace: str = "US",
    category: str | None = None,
    engine: Any | None = None,
    generate_ai_reasons: bool = True,
    export: bool = True,
) -> dict[str, Any]:
    """Import one competitor export and produce the seller shortlist deliverable."""
    imported = import_competitor_export(
        path,
        niche_label=niche_label,
        keyword=keyword,
        marketplace=marketplace,
    )
    return _finish_research(
        imported,
        category=category,
        engine=engine,
        generate_ai_reasons=generate_ai_reasons,
        export=export,
    )


def run_seller_research_from_import(
    imported: ImportedCompetitorExport,
    *,
    category: str | None = None,
    engine: Any | None = None,
    generate_ai_reasons: bool = True,
    export: bool = True,
) -> dict[str, Any]:
    """Produce the shortlist deliverable from an already-imported export.

    Used by the browser-driven flow, which yields an ``ImportedCompetitorExport``
    from the SellerSprite session before this stage runs.
    """
    return _finish_research(
        imported,
        category=category,
        engine=engine,
        generate_ai_reasons=generate_ai_reasons,
        export=export,
    )


def run_competitor_export(
    keyword: str,
    *,
    niche_label: str = "",
    marketplace: str = "US",
    category: str | None = None,
    sellersprite_url: str = "",
    dependencies: Any | None = None,
    engine: Any | None = None,
    generate_ai_reasons: bool = True,
    export: bool = True,
) -> dict[str, Any]:
    """Drive the SellerSprite competitor export, then build the seller shortlist.

    Returns a human-actionable status when the browser flow or its competitor
    locators are unavailable; it never fabricates seller data.
    """
    from agent.sellersprite_service import SellerSpriteDependencies
    from agent.sellersprite_policy import normalize_sellersprite_error_code
    from agent.tools.sellersprite_browser import SellerSpriteWorkflowError

    keyword = (keyword or "").strip()
    if not keyword:
        raise ValueError("keyword is required")
    label = niche_label or keyword

    deps = dependencies or SellerSpriteDependencies()
    profile = getattr(deps, "profile", None)
    if (
        not getattr(deps, "browser_enabled", False)
        or profile is None
        or getattr(deps, "session_factory", None) is None
        or not profile.has_competitor_locators()
    ):
        return {
            "status": "EXTENSION_UNAVAILABLE",
            "keyword": keyword,
            "niche_label": label,
            "message": (
                "SellerSprite 竞品导出未配置：请先提供 competitor_* 定位符并启用浏览器流程，"
                "或改用导出文件导入。"
            ),
        }

    try:
        with deps.session_factory() as session:
            if sellersprite_url:
                session.open_sellersprite_page(sellersprite_url)
            artifact = session.export_competitor_products(keyword)
    except SellerSpriteWorkflowError as exc:
        return {
            "status": normalize_sellersprite_error_code(exc.error_code),
            "keyword": keyword,
            "niche_label": label,
        }
    except Exception as exc:  # noqa: BLE001 - browser side effects must not crash the API
        logger.warning(f"[seller-research] competitor export failed: {exc}")
        return {"status": "INTERNAL", "keyword": keyword, "niche_label": label}

    imported = import_competitor_export(
        artifact.path,
        niche_label=label,
        keyword=keyword,
        marketplace=marketplace,
    )
    payload = _finish_research(
        imported,
        category=category,
        engine=engine,
        generate_ai_reasons=generate_ai_reasons,
        export=export,
    )
    payload["status"] = "SUCCESS"
    return payload


def _finish_research(
    imported: ImportedCompetitorExport,
    *,
    category: str | None,
    engine: Any | None,
    generate_ai_reasons: bool,
    export: bool,
) -> dict[str, Any]:
    # Auto-derive the target category from the niche/keyword when not given, so
    # the four outdoor categories pick up their tuned thresholds automatically.
    resolved_category = category or classify_target_category(
        imported.niche_label or imported.keyword or ""
    )
    shortlist = build_seller_shortlist(imported.competitor_rows, category=resolved_category)

    ai_status: dict[str, Any] = {"status": "skipped", "reason": "disabled"}
    if generate_ai_reasons and shortlist.items:
        ai_status = attach_ai_reasons(
            shortlist.items,
            niche_label=imported.niche_label,
            keyword=imported.keyword,
        )

    payload = shortlist_payload(imported, shortlist)
    payload["ai_reasons"] = ai_status

    export_paths: dict[str, str] = {}
    if export:
        from reports.seller_research_exporter import export_seller_research

        paths = export_seller_research(payload)
        export_paths = {kind: str(path) for kind, path in paths.items()}
        payload["exports"] = export_paths

    if engine is not None:
        from db.seller_research_repository import save_seller_research

        saved = save_seller_research(
            engine,
            imported,
            shortlist,
            export_file=export_paths.get("xlsx"),
        )
        payload["run_id"] = saved["id"]

    logger.info(
        "seller research: niche=%s sellers=%s eligible=%s excluded=%s"
        % (
            imported.niche_label or imported.keyword or "-",
            shortlist.quality_summary.get("seller_count"),
            shortlist.eligible_count,
            len(shortlist.excluded_items),
        )
    )
    return payload


def shortlist_payload(
    imported: ImportedCompetitorExport,
    shortlist: SellerShortlist,
) -> dict[str, Any]:
    """Serialize one shortlist into the public payload used everywhere else."""
    return {
        "niche_label": imported.niche_label or (imported.keyword or "unknown"),
        "keyword": imported.keyword,
        "marketplace": imported.marketplace,
        "category": shortlist.quality_summary.get("resolved_category"),
        "ruleset_version": shortlist.ruleset_version,
        "quality_summary": shortlist.quality_summary,
        "source": {
            "file_sha256": imported.artifact.sha256,
            "row_count": imported.row_count,
            "source_provider": imported.source_provider,
            "source_type": imported.source_type,
        },
        "items": [item.to_public_dict() for item in shortlist.items],
        "excluded_items": [item.to_public_dict() for item in shortlist.excluded_items],
    }


def attach_ai_reasons(
    items: list[SellerResearchItem],
    *,
    niche_label: str = "",
    keyword: str = "",
    max_items: int = _DEFAULT_AI_MAX_ITEMS,
    client: Any | None = None,
) -> dict[str, Any]:
    """Fill ``item.ai_reason`` for the top sellers; never raise.

    Returns a status dict for the caller/UI.  On skip or error the items keep
    ``ai_reason=None`` so the exporter falls back to rule-based reasons.
    """
    model = settings.ppio_text_model
    if client is None:
        if not settings.ppio_api_key:
            return {"status": "skipped", "provider": "ppio", "model": model, "error": "PPIO_API_KEY is not configured"}
        if not _HAS_OPENAI:
            return {"status": "skipped", "provider": "ppio", "model": model, "error": "openai package is not installed"}

    targets = items[: max(0, int(max_items))]
    if not targets:
        return {"status": "skipped", "provider": "ppio", "model": model, "error": "no eligible sellers"}

    prompt_items = [
        {
            "id": str(index),
            "seller": item.seller,
            "fit_category": item.fit_category_label or item.fit_category,
            "price": item.price,
            "rating": item.rating,
            "review_count": item.review_count,
            "launch_months": item.launch_months,
            "monthly_sales": item.monthly_sales,
            "monthly_revenue": item.monthly_revenue,
            "seller_product_count": item.seller_product_count,
        }
        for index, item in enumerate(targets)
    ]
    context = {"niche": niche_label or keyword or "", "sellers": prompt_items}

    try:
        active_client = client or _openai.OpenAI(
            api_key=settings.ppio_api_key,
            base_url=settings.ppio_api_base,
            timeout=float(settings.llm_request_timeout_seconds),
        )
        response = active_client.chat.completions.create(
            model=model,
            max_tokens=2600,
            temperature=0.3,
            messages=[{
                "role": "user",
                "content": _AI_REASON_PROMPT + "\n\n卖家数据 JSON：\n" + json.dumps(context, ensure_ascii=False),
            }],
        )
        content = (response.choices[0].message.content or "").strip()
        reasons = _parse_reasons(content)
    except Exception as exc:  # noqa: BLE001 - AI phrasing must never break the run
        logger.warning(f"[seller-research] AI reason generation failed: {exc}")
        return {"status": "error", "provider": "ppio", "model": model, "error": str(exc)[:300]}

    applied = 0
    for index, item in enumerate(targets):
        reason = reasons.get(str(index))
        if isinstance(reason, str) and reason.strip():
            item.ai_reason = reason.strip()
            applied += 1
    return {
        "status": "success" if applied else "empty",
        "provider": "ppio",
        "model": model,
        "applied_count": applied,
        "requested_count": len(targets),
    }


def _parse_reasons(content: str) -> dict[str, str]:
    """Extract the reasons mapping from a possibly noisy model response.

    Tolerates markdown code fences and reasoning models that emit more than one
    JSON object (e.g. a bare object followed by a fenced copy): the first
    balanced ``{...}`` that parses and contains a ``reasons`` dict wins.
    """
    text = (content or "").strip()
    if not text:
        return {}
    # Drop markdown code fences while keeping the JSON they wrap.
    text = re.sub(r"```[a-zA-Z0-9]*\s*", "", text).replace("```", "")
    for candidate in _json_object_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("reasons"), dict):
            return {str(key): value for key, value in data["reasons"].items() if isinstance(value, str)}
    return {}


def _json_object_candidates(text: str):
    """Yield each balanced top-level ``{...}`` substring in order."""
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : end + 1]
                    break
