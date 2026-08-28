"""LLM summary for completed sourcing runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from config.settings import settings

try:
    import openai as _openai
    _HAS_OPENAI = True
except ImportError:
    _openai = None  # type: ignore[assignment]
    _HAS_OPENAI = False


_PROMPT = """\
你是 Amazon Selector 的选品分析助手。请只基于给定 JSON 总结本次任务结果，不要编造缺失数据。

输出中文，格式固定：
结论：推荐 / 暂缓 / 淘汰 / 需要人工复核
关键发现：
- ...
风险与数据缺口：
- ...
下一步建议：
- ...

判断规则：
- 如果 passed 候选为 0，不能强推荐。
- 如果 mock_count > 0，提醒不能用于正式采购决策。
- 如果 market_data_rate 或 market_data_rich_rate 为 0，说明缺卖家精灵销量/竞争数据。
- 如果 supplier_evidence_ready 为 false，说明缺真实 1688 货源证据。
- 如果导出的是 rejected review records，要明确这是复核清单，不是正式推荐清单。
"""


def summarize_run_result(
    *,
    run_log_id: int | None,
    config: dict[str, Any],
    exports: dict[str, str],
    audit: dict[str, Any],
    max_candidates: int = 5,
) -> dict[str, Any]:
    """Summarize a completed run using the configured PPIO text model.

    This is intentionally non-blocking for the pipeline: callers should persist
    the returned status even when the model is unavailable.
    """
    provider = settings.openai_compatible_provider
    model = settings.openai_compatible_text_model
    if not settings.openai_compatible_api_key:
        return {
            "status": "skipped",
            "provider": provider,
            "model": model,
            "error": "OpenAI-compatible API key is not configured",
        }
    if not _HAS_OPENAI:
        return {
            "status": "skipped",
            "provider": provider,
            "model": model,
            "error": "openai package is not installed",
        }

    payload = {
        "run_log_id": run_log_id,
        "config": config,
        "exports": exports,
        "audit": audit,
        "candidates": _read_export_candidates(exports.get("json"), max_candidates=max_candidates),
    }
    try:
        client = _openai.OpenAI(
            api_key=settings.openai_compatible_api_key,
            base_url=settings.openai_compatible_api_base,
            timeout=float(settings.llm_request_timeout_seconds),
        )
        response = client.chat.completions.create(
            model=model,
            max_tokens=1200,
            temperature=0.2,
            messages=[{
                "role": "user",
                "content": _PROMPT + "\n\n任务数据 JSON：\n" + json.dumps(payload, ensure_ascii=False, indent=2),
            }],
        )
        content = (response.choices[0].message.content or "").strip()
        return {
            "status": "success",
            "provider": provider,
            "model": model,
            "summary": content,
        }
    except Exception as exc:
        logger.warning(f"[run-summary] LLM summary failed run={run_log_id}: {exc}")
        return {
            "status": "error",
            "provider": provider,
            "model": model,
            "error": str(exc)[:500],
        }


def _read_export_candidates(path: str | None, max_candidates: int) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    candidates: list[dict[str, Any]] = []
    for row in rows[:max_candidates]:
        if not isinstance(row, dict):
            continue
        product = row.get("product") or {}
        score = row.get("score") or {}
        profit = row.get("profit") or {}
        suppliers = row.get("suppliers") or []
        top_supplier = suppliers[0] if suppliers and isinstance(suppliers[0], dict) else {}
        candidates.append({
            "asin": product.get("asin"),
            "title": product.get("title"),
            "score": score.get("total_score"),
            "passed": score.get("passed_hard_filter"),
            "rejection_reasons": score.get("rejection_reasons") or [],
            "profit_margin": profit.get("profit_margin"),
            "net_profit": profit.get("net_profit"),
            "supplier": top_supplier.get("supplier_name"),
            "supplier_source": top_supplier.get("sourcing_source"),
            "invalid_for_decision": top_supplier.get("invalid_for_decision"),
        })
    return candidates
