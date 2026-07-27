"""Deterministic data tools for the product selection chat assistant."""
from __future__ import annotations

import json
import re
from typing import Any

from agent import history
from config.settings import settings
from db.models import MarketAnalysis, Product, ProfitSnapshot, RunLog, Score, Supplier
from db.session import session_scope

try:
    import openai as _openai
    _HAS_OPENAI = True
except ImportError:
    _openai = None  # type: ignore[assignment]
    _HAS_OPENAI = False


_ASIN_RE = re.compile(r"\b[A-Z0-9]{10}\b", re.I)
_CHAT_PROMPT = """\
你是 Amazon Selector 的选品聊天助手。必须只基于工具数据回答，不要编造。

回答格式固定：
结论：推荐 / 暂缓 / 淘汰 / 需要人工复核
依据：利润、需求、竞争、货源、物流、风险
数据缺口
下一步建议

规则：
- 如果工具数据为空或数据不足，不允许强推荐。
- 如果 supplier 是 mock 或 invalid_for_decision，必须提醒不能直接采购决策。
- 必须明确真实 1688 货源、MOQ、卖家精灵销量/竞争、包装尺寸、品牌/专利风险等缺口。
"""


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    runs = history.list_export_runs(limit=limit)
    if runs:
        return runs[:limit]
    try:
        with session_scope() as session:
            rows = (
                session.query(RunLog)
                .order_by(RunLog.started_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": str(row.id),
                    "category": row.category,
                    "marketplace": row.marketplace,
                    "status": row.status,
                    "source_mode": (row.api_calls or {}).get("source_mode"),
                    "source_query": (row.api_calls or {}).get("source_query"),
                    "count": row.candidates_after_filter,
                }
                for row in rows
            ]
    except Exception:
        return []


def get_run_summary(run_id: str) -> dict[str, Any] | None:
    for run in history.list_export_runs(limit=100):
        if str(run.get("id")) == str(run_id):
            return run
    try:
        with session_scope() as session:
            row = session.get(RunLog, int(run_id))
            if not row:
                return None
            return {
                "id": str(row.id),
                "category": row.category,
                "marketplace": row.marketplace,
                "status": row.status,
                "api_calls": row.api_calls or {},
                "products_crawled": row.products_crawled,
                "candidates_after_filter": row.candidates_after_filter,
            }
    except Exception:
        return None


def search_candidates(query: str, run_id: str | None = None) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    items = _candidate_items(run_id)
    if not q:
        return items
    return [
        item for item in items
        if any(q in str(item.get(key) or "").lower() for key in ("asin", "title", "supplier"))
    ]


def get_candidate_detail(asin: str, run_id: str | None = None) -> dict[str, Any] | None:
    target = (asin or "").strip().upper()
    for item in _candidate_items(run_id):
        if str(item.get("asin") or "").upper() == target:
            return item
    return None


def compare_candidates(asins: list[str], run_id: str | None = None) -> list[dict[str, Any]]:
    details = []
    for asin in asins:
        detail = get_candidate_detail(asin, run_id=run_id)
        if detail:
            details.append(detail)
    return details


def get_saved_items() -> list[dict[str, Any]]:
    return [item for item in _candidate_items(None) if item.get("saved")]


def explain_rejection(asin: str, run_id: str | None = None) -> dict[str, Any]:
    detail = get_candidate_detail(asin, run_id=run_id)
    if not detail:
        return {"asin": asin, "found": False, "reasons": ["候选数据不存在"], "data_gaps": ["数据不足"]}
    reasons = detail.get("rejection_reasons") or []
    return {
        "asin": detail.get("asin"),
        "found": True,
        "reasons": reasons or ["未记录明确淘汰原因"],
        "review_status": detail.get("review_status"),
        "data_gaps": _data_gaps(detail),
    }


def get_top_candidates(
    run_id: str | None = None,
    sort_by: str = "decision_score",
    limit: int = 5,
) -> list[dict[str, Any]]:
    key_map = {
        "decision_score": "score",
        "score": "score",
        "profit_margin": "margin",
        "net_profit": "net_profit",
    }
    field = key_map.get(sort_by, "score")
    items = _candidate_items(run_id)
    items.sort(key=lambda item: _numeric(item.get(field)), reverse=True)
    return items[:limit]


def answer_chat(
    message: str,
    run_id: str | None = None,
    selected_asin: str | None = None,
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    used_tools: list[str] = []
    msg = message or ""
    asins = [m.group(0).upper() for m in _ASIN_RE.finditer(msg)]

    detail = None
    if len(asins) >= 2:
        used_tools.append("compare_candidates")
        compared = compare_candidates(asins, run_id=run_id)
        if compared:
            deterministic = _format_compare_answer(compared)
            payload = {"tool": "compare_candidates", "items": compared, "message": message}
            llm = _llm_answer_if_available(use_llm, payload, deterministic)
            return {
                "answer": llm["answer"],
                "used_tools": [*used_tools, *llm["used_tools"]],
                **llm["meta"],
                "context": {"run_id": run_id, "asins": asins},
            }

    if selected_asin:
        used_tools.append("get_candidate_detail")
        detail = get_candidate_detail(selected_asin, run_id=run_id)
    elif asins:
        used_tools.append("get_candidate_detail")
        detail = get_candidate_detail(asins[0], run_id=run_id)

    if detail:
        deterministic = _format_candidate_answer(detail)
        payload = {"tool": "get_candidate_detail", "item": detail, "message": message}
        llm = _llm_answer_if_available(use_llm, payload, deterministic)
        return {
            "answer": llm["answer"],
            "used_tools": [*used_tools, *llm["used_tools"]],
            **llm["meta"],
            "context": {"asin": detail.get("asin"), "run_id": run_id},
        }

    used_tools.append("get_top_candidates")
    candidates = get_top_candidates(run_id=run_id, limit=5)
    if not candidates:
        return {
            "answer": "\n".join([
                "结论：需要人工复核（数据不足）",
                "",
                "依据：当前任务或历史导出中没有可读取的候选商品，无法判断利润、需求、竞争、货源、物流或风险。",
                "",
                "数据缺口：缺候选商品、缺真实 1688 货源、缺 MOQ、缺卖家精灵销量、缺包装尺寸、缺品牌风险检查。",
                "",
                "下一步建议：先运行一次类目或关键词选品任务；若 1688 被登录/验证码阻塞，先完成人工登录后再复核。",
            ]),
            "used_tools": used_tools,
            "context": {"run_id": run_id},
        }

    deterministic = _format_top_candidates_answer(candidates)
    payload = {"tool": "get_top_candidates", "items": candidates, "message": message}
    llm = _llm_answer_if_available(use_llm, payload, deterministic)
    return {
        "answer": llm["answer"],
        "used_tools": [*used_tools, *llm["used_tools"]],
        **llm["meta"],
        "context": {"run_id": run_id, "count": len(candidates)},
    }


def _llm_answer_if_available(
    use_llm: bool,
    tool_payload: dict[str, Any],
    deterministic_answer: str,
) -> dict[str, Any]:
    if not use_llm:
        return {"answer": deterministic_answer, "used_tools": [], "meta": {}}
    if not settings.ppio_api_key or not _HAS_OPENAI:
        return {"answer": deterministic_answer, "used_tools": [], "meta": {"llm_status": "skipped"}}
    try:
        client = _openai.OpenAI(
            api_key=settings.ppio_api_key,
            base_url=settings.ppio_api_base,
            timeout=float(settings.llm_request_timeout_seconds),
        )
        response = client.chat.completions.create(
            model=settings.ppio_text_model,
            temperature=0.2,
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": "\n\n".join([
                    _CHAT_PROMPT,
                    "工具数据 JSON：",
                    json.dumps(tool_payload, ensure_ascii=False, indent=2),
                    "确定性基线回答：",
                    deterministic_answer,
                ]),
            }],
        )
        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            raise ValueError("empty LLM response")
        model = settings.ppio_text_model
        return {
            "answer": answer,
            "used_tools": [f"llm:{model}"],
            "meta": {"llm_status": "success", "model": model},
        }
    except Exception as exc:
        return {
            "answer": deterministic_answer,
            "used_tools": [],
            "meta": {"llm_status": "error", "llm_error": str(exc)[:300]},
        }


def _candidate_items(run_id: str | None) -> list[dict[str, Any]]:
    try:
        items = list(history.list_results(run_id=run_id, limit=1000).get("items") or [])
        if items:
            return items
    except Exception:
        pass
    if run_id and not _db_run_exists(run_id):
        return []
    return _db_candidate_items(limit=1000)


def _db_run_exists(run_id: str) -> bool:
    try:
        numeric_run_id = int(run_id)
    except (TypeError, ValueError):
        return False
    try:
        with session_scope() as session:
            return session.get(RunLog, numeric_run_id) is not None
    except Exception:
        return False


def _db_candidate_items(limit: int = 1000) -> list[dict[str, Any]]:
    try:
        with session_scope() as session:
            products = session.query(Product).order_by(Product.last_updated_at.desc()).limit(limit).all()
            suppliers = session.query(Supplier).all()
            profits = session.query(ProfitSnapshot).all()
            scores = session.query(Score).all()
            markets = session.query(MarketAnalysis).all()

            suppliers_by_product = _group_by(suppliers, "product_id")
            profits_by_product = _group_by(profits, "product_id")
            scores_by_product = _group_by(scores, "product_id")
            markets_by_product = _group_by(markets, "product_id")

            items: list[dict[str, Any]] = []
            for product in products:
                product_id = getattr(product, "id", None)
                supplier = _latest(suppliers_by_product.get(product_id, []), "matched_at")
                profit = _latest(profits_by_product.get(product_id, []), "snapshot_at")
                score = _latest(scores_by_product.get(product_id, []), "scored_at")
                market = _latest(markets_by_product.get(product_id, []), "analyzed_at")
                supplier_raw = getattr(supplier, "raw_data", None) or {}
                item = {
                    "key": f"db:{getattr(product, 'marketplace', 'US')}:{getattr(product, 'asin', '')}",
                    "asin": getattr(product, "asin", None),
                    "marketplace": getattr(product, "marketplace", None),
                    "title": getattr(product, "title", None),
                    "brand": getattr(product, "brand", None),
                    "category": getattr(product, "category", None),
                    "price": getattr(product, "price", None),
                    "supplier": getattr(supplier, "supplier_name", None),
                    "offer_url": getattr(supplier, "offer_url", None),
                    "buy_cost_cny": getattr(supplier, "base_price_cny", None),
                    "moq": getattr(supplier, "moq", None),
                    "delivery_days": getattr(supplier, "delivery_days", None) or (supplier_raw.get("detail") or {}).get("delivery_days"),
                    "supplier_match_quality": getattr(supplier, "match_quality_score", None),
                    "product_spec": {
                        "dimensions_cm": getattr(supplier, "product_dimensions_cm", None)
                            or _product_dimensions(product),
                        "material": getattr(supplier, "material", None),
                        "risk_flags": supplier_raw.get("risk_flags") or [],
                    },
                    "margin": getattr(profit, "profit_margin", None),
                    "net_profit": getattr(profit, "net_profit", None),
                    "score": getattr(score, "total_score", None),
                    "passed": getattr(score, "passed_hard_filter", None),
                    "rejection_reasons": getattr(score, "rejection_reasons", None) or [],
                    "score_dimensions": {
                        "profit": getattr(score, "profit_score", None),
                        "demand": getattr(score, "demand_score", None),
                        "competition": getattr(score, "competition_score", None),
                        "supply": getattr(score, "supply_score", None),
                        "logistics": getattr(score, "logistics_score", None),
                        "risk": getattr(score, "risk_score", None),
                    },
                    "market": {
                        "main_keyword": getattr(market, "main_keyword", None),
                        "search_volume_monthly": getattr(market, "search_volume_monthly", None),
                        "competing_listings": getattr(market, "competing_listings", None),
                        "top10_revenue_share": getattr(market, "top10_revenue_share", None),
                        "opportunity_score": getattr(market, "opportunity_score", None),
                    },
                }
                items.append(item)
            return items
    except Exception:
        return []


def _group_by(rows: list[Any], key: str) -> dict[Any, list[Any]]:
    grouped: dict[Any, list[Any]] = {}
    for row in rows:
        grouped.setdefault(getattr(row, key, None), []).append(row)
    return grouped


def _latest(rows: list[Any], date_attr: str) -> Any | None:
    if not rows:
        return None
    return sorted(rows, key=lambda row: getattr(row, date_attr, None) or 0, reverse=True)[0]


def _product_dimensions(product: Any) -> str | None:
    dims = [
        getattr(product, "length_cm", None),
        getattr(product, "width_cm", None),
        getattr(product, "height_cm", None),
    ]
    if not all(dims):
        return None
    return "x".join(f"{float(value):.1f}" for value in dims) + "cm"


def _numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _format_candidate_answer(item: dict[str, Any]) -> str:
    conclusion = _conclusion(item)
    gaps = _data_gaps(item)
    return "\n".join([
        f"结论：{conclusion}",
        "",
        "依据：",
        f"- 利润：净利率 {history_value_percent(item.get('margin'))}，净利润 {history_value_money(item.get('net_profit'))}。",
        f"- 需求：{_demand_text(item)}",
        f"- 竞争：{_competition_text(item)}",
        f"- 货源：{_supply_text(item)}",
        f"- 物流：{_logistics_text(item)}",
        f"- 风险：{_risk_text(item)}",
        "",
        "决策解释：",
        _decision_explanation(item, conclusion),
        "",
        "数据缺口：",
        _bullet_list(gaps),
        "",
        "下一步建议：",
        _bullet_list(_next_steps(item, gaps)),
    ])


def _format_top_candidates_answer(candidates: list[dict[str, Any]]) -> str:
    best = candidates[0]
    rows = [
        f"- {item.get('asin') or '-'}：{item.get('title') or '-'}，评分 {item.get('score') or '-'}，净利率 {history_value_percent(item.get('margin'))}"
        for item in candidates[:5]
    ]
    gaps = _data_gaps(best)
    conclusion = _conclusion(best)
    return "\n".join([
        f"结论：{conclusion}",
        "",
        "依据：",
        *rows,
        "",
        "数据缺口：",
        _bullet_list(gaps),
        "",
        "下一步建议：",
        _bullet_list(_next_steps(best, gaps)),
    ])


def _format_compare_answer(candidates: list[dict[str, Any]]) -> str:
    ranked = sorted(
        candidates,
        key=lambda item: (_numeric(item.get("score")), _numeric(item.get("margin")), -len(_data_gaps(item))),
        reverse=True,
    )
    best = ranked[0]
    rows = [
        (
            f"- {item.get('asin') or '-'}：评分 {item.get('score') or '-'}，"
            f"净利率 {history_value_percent(item.get('margin'))}，"
            f"MOQ {item.get('moq') or '-'}，缺口 {len(_data_gaps(item))} 项"
        )
        for item in ranked
    ]
    return "\n".join([
        f"结论：优先看 {best.get('asin') or '-'}，其余候选暂缓或人工复核",
        "",
        "候选对比：",
        *rows,
        "",
        "依据：优先级按综合评分、利润率、真实货源/MOQ/尺寸/风险数据完整度排序。",
        "",
        "数据缺口：",
        _bullet_list(_data_gaps(best)),
        "",
        "下一步建议：",
        _bullet_list(_next_steps(best, _data_gaps(best))),
    ])


def generate_decision_report(asin: str, run_id: str | None = None) -> dict[str, Any]:
    detail = get_candidate_detail(asin, run_id=run_id)
    if not detail:
        return {
            "asin": asin,
            "found": False,
            "conclusion": "需要人工复核",
            "report": "结论：需要人工复核（数据不足）\n\n决策解释：候选数据不存在，无法生成淘汰/暂缓原因。",
        }
    conclusion = _conclusion(detail)
    if conclusion == "推荐" and (_numeric(detail.get("score")) < 80 or _numeric(detail.get("margin")) < 0.30):
        conclusion = "暂缓"
    report = "\n".join([
        f"结论：{conclusion}",
        "",
        "依据：",
        f"- 利润：净利率 {history_value_percent(detail.get('margin'))}，净利润 {history_value_money(detail.get('net_profit'))}。",
        f"- 需求：{_demand_text(detail)}",
        f"- 竞争：{_competition_text(detail)}",
        f"- 货源：{_supply_text(detail)}",
        f"- 物流：{_logistics_text(detail)}",
        f"- 风险：{_risk_text(detail)}",
        "",
        "决策解释：",
        _decision_explanation(detail, conclusion),
        "",
        "数据缺口：",
        _bullet_list(_data_gaps(detail)),
        "",
        "下一步建议：",
        _bullet_list(_next_steps(detail, _data_gaps(detail))),
    ])
    return {
        "asin": detail.get("asin") or asin,
        "found": True,
        "conclusion": conclusion,
        "report": report,
        "data_gaps": _data_gaps(detail),
    }


def _conclusion(item: dict[str, Any]) -> str:
    if item.get("invalid_for_decision") or item.get("mock"):
        return "需要人工复核（货源不可直接用于采购决策）"
    if _data_gaps(item):
        return "需要人工复核"
    if item.get("passed") and _numeric(item.get("score")) >= 75 and _numeric(item.get("margin")) >= 0.25:
        return "推荐"
    if not item.get("passed") and item.get("rejection_reasons"):
        return "淘汰"
    return "暂缓"


def _decision_explanation(item: dict[str, Any], conclusion: str) -> str:
    reasons = item.get("rejection_reasons") or []
    if conclusion == "淘汰":
        reason_text = "、".join(str(reason) for reason in reasons) or "硬性筛选未通过"
        return f"为什么淘汰：{reason_text}。当前分数 {item.get('score') or '-'}，净利率 {history_value_percent(item.get('margin'))}，不适合进入正式推荐。"
    if conclusion == "暂缓":
        return "为什么暂缓：已有一定候选信息，但评分、利润或供应链证据未达到推荐阈值，适合补数据后再判断。"
    if "人工复核" in conclusion:
        return "为什么需要人工复核：关键数据缺口或供应商有效性会影响采购决策，不能仅凭当前自动化结果下结论。"
    return "为什么推荐：当前利润、评分和供应链证据达到推荐门槛，但仍需样品、合规和供应商账期复核。"


def _data_gaps(item: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if item.get("mock") or item.get("invalid_for_decision"):
        gaps.append("mock/无效供应商不能直接用于采购决策")
    if not item.get("supplier") or not item.get("offer_url"):
        gaps.append("缺真实 1688 货源")
    if item.get("moq") in (None, "", 0):
        gaps.append("缺 MOQ")
    market = item.get("market") or {}
    if not market.get("est_monthly_sales") and not market.get("search_volume_monthly"):
        gaps.append("缺卖家精灵销量/搜索量")
    product_spec = item.get("product_spec") or {}
    if not any(item.get(k) for k in ("length_cm", "width_cm", "height_cm")) and not product_spec.get("dimensions_cm"):
        gaps.append("缺包装尺寸")
    if not product_spec.get("risk_flags"):
        gaps.append("缺品牌风险检查")
    return list(dict.fromkeys(gaps))


def _next_steps(item: dict[str, Any], gaps: list[str]) -> list[str]:
    steps = []
    if any("1688" in gap or "供应商" in gap for gap in gaps):
        steps.append("补采或人工确认 1688 真实货源链接、价格阶梯和供应商资质")
    if any("MOQ" in gap for gap in gaps):
        steps.append("确认 MOQ、阶梯价和首单打样数量")
    if any("卖家精灵" in gap for gap in gaps):
        steps.append("补充卖家精灵销量、搜索量和竞品集中度")
    if any("包装尺寸" in gap for gap in gaps):
        steps.append("补齐包装尺寸和重量后重算 FBA/头程物流")
    if any("品牌风险" in gap for gap in gaps):
        steps.append("做品牌、专利、合规风险人工检查")
    if not steps:
        steps.append("进入供应商询价、样品验证和小批量测试")
    return steps


def _demand_text(item: dict[str, Any]) -> str:
    market = item.get("market") or {}
    return f"月销量 {market.get('est_monthly_sales') or '-'}，月搜索量 {market.get('search_volume_monthly') or '-'}"


def _competition_text(item: dict[str, Any]) -> str:
    market = item.get("market") or {}
    return f"竞品数 {market.get('competing_listings') or '-'}，Top10 集中度 {history_value_percent(market.get('top10_revenue_share'))}"


def _supply_text(item: dict[str, Any]) -> str:
    return f"{item.get('supplier') or '无供应商'}，采购价 {history_value_money(item.get('buy_cost_cny'), '¥')}，MOQ {item.get('moq') or '-'}"


def _logistics_text(item: dict[str, Any]) -> str:
    return f"重量/尺寸依赖导出字段；当前规格缺口：{', '.join(g for g in _data_gaps(item) if '包装尺寸' in g) or '未发现'}"


def _risk_text(item: dict[str, Any]) -> str:
    reasons = item.get("rejection_reasons") or []
    if item.get("mock") or item.get("invalid_for_decision"):
        return "货源为 mock 或无效，不能直接采购决策"
    return ", ".join(reasons) if reasons else "未记录明确风险，仍需品牌/合规人工检查"


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in (items or ["暂无"]))


def history_value_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def history_value_money(value: Any, prefix: str = "$") -> str:
    try:
        return f"{prefix}{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"
