"""Bounded, evidence-gated supplier sourcing coordinator."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import text

from agent.provenance import trusted_evidence_value
from matchers.alibaba_detail import BlockedOfferPage
from matchers.match_evidence import build_match_evidence
from matchers.query_planner import generate_query_plan, rewrite_low_relevance_queries
from schemas.sourcing import MatchEvidence, RecommendationEvidence, RecommendationStatus


TERMINAL_BLOCK_CODES = {"AUTH_REQUIRED", "CAPTCHA"}
STABLE_SEARCH_ERROR_CODES = {
    "AUTH_REQUIRED", "CAPTCHA", "RATE_LIMITED", "TIMEOUT", "NO_RESULTS", "LOW_RELEVANCE",
    "INVALID_INPUT", "MISSING_REQUIRED_DATA", "INTERNAL",
    "PROVIDER_FAILURE", "SCHEMA_VALIDATION", "IMAGE_EVIDENCE_UNAVAILABLE",
}
NON_RETRYABLE_CODES = {"AUTH_REQUIRED", "CAPTCHA", "INVALID_INPUT", "MISSING_REQUIRED_DATA", "INTERNAL"}
TEXT_RELEVANCE_THRESHOLD = 0.5
IMAGE_RELEVANCE_THRESHOLD = 0.8
RETRYABLE_VISUAL_CODES = {"PROVIDER_FAILURE"}


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return score if math.isfinite(score) else None


def _normalized_terms(value: Any) -> list[str]:
    text_value = str(value or "").casefold()
    return [term for term in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text_value) if len(term) >= 2]


def _bigrams(terms: list[str]) -> set[str]:
    return {
        term[index:index + 2]
        for term in terms if not term.isascii()
        for index in range(len(term) - 1)
    }


def _default_relevance(query: Any, supplier: Any) -> bool:
    """Conservative relevance decision from explicit or meaningful textual evidence."""
    raw = getattr(supplier, "raw_data", None)
    raw = raw if isinstance(raw, dict) else {}
    explicit = raw.get("search_relevance")
    if type(explicit) is bool:
        return explicit
    if explicit is not None:
        score = _finite_score(explicit)
        return score is not None and score >= TEXT_RELEVANCE_THRESHOLD
    text_score = _finite_score(getattr(supplier, "text_similarity", None))
    if text_score is not None:
        return text_score >= TEXT_RELEVANCE_THRESHOLD
    image_score = _finite_score(getattr(supplier, "image_similarity", None))
    source = str(raw.get("source", "")).casefold()
    if image_score is not None and source in {
        "image_search", "pailitao", "alibaba_pailitao", "alibaba_playwright",
    }:
        return image_score >= IMAGE_RELEVANCE_THRESHOLD
    query_terms = _normalized_terms(getattr(query, "text", ""))
    title_terms = _normalized_terms(getattr(supplier, "title_cn", ""))
    if not query_terms or not title_terms:
        return False
    title_ascii = {term for term in title_terms if term.isascii()}
    title_cjk_runs = [term for term in title_terms if not term.isascii()]
    query_cjk = [term for term in query_terms if not term.isascii()]
    if len(query_terms) == 1 and query_cjk:
        term = query_cjk[0]
        return any(run == term or run.startswith(term) or run.endswith(term) for run in title_cjk_runs)
    if len(query_cjk) >= 2 and len(query_cjk) == len(query_terms):
        phrase = "".join(query_cjk)
        return any(phrase in run for run in title_cjk_runs)
    matches = [
        term in title_ascii if term.isascii() else any(
            run == term or run.startswith(term) or run.endswith(term)
            for run in title_cjk_runs
        )
        for term in query_terms
    ]
    required = max(2, math.ceil(len(query_terms) * 0.75))
    return sum(matches) >= required


@dataclass
class SourcingSliceDependencies:
    understand: Callable
    search: Callable
    load_detail: Callable
    verify_visual: Callable
    market_evidence: Callable
    engine: Any | None = None
    assess_relevance: Callable | None = None


@dataclass
class SourcingSliceResult:
    run_ref: str
    iterations: int
    understanding: object
    query_attempts: list[dict] = field(default_factory=list)
    suppliers: list = field(default_factory=list)
    evaluated_matches: list[MatchEvidence] = field(default_factory=list)
    accepted_matches: list[MatchEvidence] = field(default_factory=list)
    rejected_matches: list[MatchEvidence] = field(default_factory=list)
    review_matches: list[MatchEvidence] = field(default_factory=list)
    detail_failures: list[dict] = field(default_factory=list)
    visual_failures: list[dict] = field(default_factory=list)
    recommendation: RecommendationEvidence | None = None


def _is_mock(supplier: Any) -> bool:
    method = (getattr(supplier, "match_verification_method", "") or "").casefold()
    raw = getattr(supplier, "raw_data", None)
    raw = raw if isinstance(raw, dict) else {}
    source = str(raw.get("source", "")).casefold()
    return method == "mock" or raw.get("data_status") == "mock" or source == "mock"


def _positive(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except (TypeError, ValueError, OverflowError):
        return False


def _error_code(exc: Exception) -> str:
    code = str(getattr(exc, "error_code", "") or getattr(exc, "code", "") or "").upper()
    if code in STABLE_SEARCH_ERROR_CODES:
        return code
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, ValueError):
        return "INVALID_INPUT"
    if isinstance(exc, (KeyError, AttributeError)):
        return "MISSING_REQUIRED_DATA"
    return "INTERNAL"


def _blocked_recommendation(product: Any, stage: str, exc: Exception) -> RecommendationEvidence:
    code = _error_code(exc)
    return RecommendationEvidence(
        asin=product.asin, status=RecommendationStatus.INSUFFICIENT_DATA,
        discovery_reason="Amazon US source candidate passed initial discovery",
        amazon_completeness=0.0, confidence=0.0,
        rejection_reasons=[f"1688_{stage}_{code.casefold()}"],
        manual_verification_tasks=[str(getattr(exc, "diagnostic", exc))],
    )


def _attempt(query: Any, *, hits: list[Any] | None = None, relevant_count: int | None = None,
             error_code: str | None = None, completed: bool = True) -> dict:
    result_count = len(hits or []) if completed else None
    rate = (relevant_count / max(1, result_count)) if completed and relevant_count is not None else None
    return {
        "query": query.model_dump(mode="json"), "result_count": result_count,
        "relevant_count": relevant_count, "hit_rate": rate,
        "result_refs": [f"offer:{item.alibaba_offer_id}" for item in (hits or [])] if completed else [],
        "error_code": error_code or ("NO_RESULTS" if completed and not result_count else None),
        "status": "completed" if completed else "failed",
    }


def _recommend(product: Any, result: SourcingSliceResult, market: dict[str, Any], *,
               mock_excluded: bool) -> RecommendationEvidence:
    best = max(result.accepted_matches, key=lambda item: item.overall_confidence, default=None)
    missing: list[str] = []
    demand_refs = trusted_evidence_value(market.get("demand_refs"))
    competition_refs = trusted_evidence_value(market.get("competition_refs"))
    purchase_cost_ref = trusted_evidence_value(market.get("purchase_cost_ref"))
    amazon_completeness = trusted_evidence_value(market.get("amazon_completeness"))
    logistics = trusted_evidence_value(market.get("logistics_basis"))
    profit = trusted_evidence_value(market.get("profit_basis"))
    logistics_valid = isinstance(logistics, dict) and bool(logistics.get("refs")) and all(
        _positive(logistics.get(key)) for key in ("weight_kg", "length_cm", "width_cm", "height_cm")
    )
    profit_valid = isinstance(profit, dict) and bool(profit.get("refs")) and all(
        _positive(profit.get(key)) for key in ("selling_price", "landed_cost", "profit_margin")
    )
    checks = {
        "amazon_completeness": _positive(amazon_completeness),
        "demand_refs": bool(demand_refs),
        "competition_refs": bool(competition_refs),
        "purchase_cost_ref": bool(purchase_cost_ref),
        "logistics_basis": logistics_valid,
        "profit_basis": profit_valid,
        "real_price": bool(best) and "price" in best.passed_reasons,
        "real_moq": bool(best) and "moq" in best.passed_reasons,
    }
    if best:
        missing = [name for name, present in checks.items() if not present]
        status = RecommendationStatus.RECOMMEND if not missing else RecommendationStatus.NEEDS_MANUAL_REVIEW
    elif result.review_matches:
        status = RecommendationStatus.NEEDS_MANUAL_REVIEW
        evidence_missing = sorted({name for match in result.review_matches for name in match.missing_evidence})
        missing.extend(evidence_missing)
    elif result.rejected_matches:
        status = RecommendationStatus.REJECT
    else:
        status = RecommendationStatus.INSUFFICIENT_DATA
    rejection = [f"missing_{name}" for name in missing]
    if not best and not result.review_matches and not result.rejected_matches:
        rejection.append("no_supplier_passed_minimum_evidence")
    for match in result.rejected_matches:
        rejection.extend(match.mismatch_reasons)
    if mock_excluded:
        rejection.append("mock_supplier_excluded")
    for failure in result.detail_failures:
        rejection.append(failure["reason"])
    for failure in result.visual_failures:
        rejection.append(failure["reason"])
    return RecommendationEvidence(
        asin=product.asin,
        supplier_offer_id=best.supplier_ref.removeprefix("offer:") if best else None,
        status=status, discovery_reason="Amazon US source candidate passed initial discovery",
        amazon_completeness=amazon_completeness if _positive(amazon_completeness) else 0.0,
        demand_evidence_refs=demand_refs or [],
        competition_evidence_refs=competition_refs or [],
        supplier_match_ref=best.supplier_ref if best else None,
        confirmed_specs=best.passed_reasons if best else [],
        unconfirmed_specs=best.missing_evidence if best else [],
        purchase_cost_ref=purchase_cost_ref if best else None,
        logistics_basis=logistics or {},
        profit_basis=profit or {}, risks=market.get("risks", []),
        confidence=best.overall_confidence if best else 0.0,
        recommendation_reasons=["minimum_supplier_evidence_passed", "decision_evidence_complete"] if status is RecommendationStatus.RECOMMEND else [],
        rejection_reasons=rejection,
        manual_verification_tasks=[
            *[f"verify_{name}" for name in missing],
            *[f"retry_{failure['reason']}" for failure in result.detail_failures],
            *[f"retry_{failure['reason']}" for failure in result.visual_failures],
            *[
                f"retry_{failure['reason']}:{failure['offer_ref']}:attempts={failure['attempt_count']}"
                for failure in result.detail_failures
            ],
            *[
                f"retry_{failure['reason']}:{failure['offer_ref']}:attempts={failure['attempt_count']}"
                for failure in result.visual_failures
            ],
        ],
    )


def _persist(result: SourcingSliceResult, engine: Any) -> None:
    asin = result.understanding.asin
    with engine.begin() as conn:
        scope = {"run_ref": result.run_ref, "asin": asin}
        conn.execute(text("DELETE FROM query_attempts WHERE run_ref=:run_ref AND asin=:asin"), scope)
        conn.execute(text("DELETE FROM match_evidence WHERE run_ref=:run_ref AND asin=:asin"), scope)
        conn.execute(text("DELETE FROM sourcing_recommendations WHERE run_ref=:run_ref AND asin=:asin"), scope)
        for attempt in result.query_attempts:
            query = attempt["query"]
            completed = attempt["status"] == "completed"
            conn.execute(text("""INSERT INTO query_attempts (
                run_ref, asin, query_id, query_type, query_text, reason,
                excluded_brand_tokens_json, backend, result_count, relevant_count,
                retry_of, status, artifact_ref
            ) VALUES (:run_ref, :asin, :query_id, :query_type, :query_text, :reason,
                :tokens, 'dependency.search', :result_count, :relevant_count,
                :retry_of, :status, :artifact_ref)
            ON CONFLICT(run_ref, query_id) DO UPDATE SET
                result_count=excluded.result_count, relevant_count=excluded.relevant_count,
                status=excluded.status, artifact_ref=excluded.artifact_ref"""), {
                "run_ref": result.run_ref, "asin": asin, "query_id": query["query_id"],
                "query_type": query["query_type"], "query_text": query["text"],
                "reason": query["reason"], "tokens": json.dumps(query["excluded_brand_tokens"]),
                "result_count": attempt["result_count"] if completed else None,
                "relevant_count": attempt["relevant_count"] if completed else None,
                "retry_of": query.get("retry_of"), "status": attempt["status"],
                "artifact_ref": json.dumps({"result_refs": attempt["result_refs"], "hit_rate": attempt["hit_rate"], "error_code": attempt["error_code"]}),
            })
        if getattr(engine, "fail_persistence_after", None) == "query_attempts":
            raise RuntimeError("injected persistence failure")
        for match in result.evaluated_matches:
            payload = match.model_dump(mode="json")
            conn.execute(text("""INSERT INTO match_evidence
                (run_ref, asin, offer_id, decision, overall_confidence, evidence_json)
                VALUES (:run_ref, :asin, :offer_id, :decision, :confidence, :evidence)
                ON CONFLICT(run_ref, asin, offer_id) DO UPDATE SET
                    decision=excluded.decision, overall_confidence=excluded.overall_confidence,
                    evidence_json=excluded.evidence_json"""), {
                "run_ref": result.run_ref, "asin": asin,
                "offer_id": match.supplier_ref.removeprefix("offer:"),
                "decision": match.decision, "confidence": match.overall_confidence,
                "evidence": json.dumps(payload, ensure_ascii=False),
            })
        recommendation = result.recommendation
        if recommendation:
            payload = recommendation.model_dump(mode="json")
            conn.execute(text("""INSERT INTO sourcing_recommendations
                (run_ref, asin, offer_id, status, evidence_json)
                VALUES (:run_ref, :asin, :offer_id, :status, :evidence)
                ON CONFLICT(run_ref, asin, offer_id) DO UPDATE SET
                    status=excluded.status, evidence_json=excluded.evidence_json"""), {
                "run_ref": result.run_ref, "asin": asin,
                "offer_id": recommendation.supplier_offer_id,
                "status": recommendation.status.value,
                "evidence": json.dumps(payload, ensure_ascii=False),
            })


def serialize_sourcing_result(result: SourcingSliceResult) -> dict[str, Any]:
    """Return a JSON-safe evidence payload suitable for snapshots and exports."""
    recommendation = result.recommendation
    return {
        "schema_version": "target-sourcing-evidence-v1",
        "run_ref": result.run_ref,
        "asin": result.understanding.asin,
        "iterations": result.iterations,
        "understanding": result.understanding.model_dump(mode="json"),
        "query_attempts": list(result.query_attempts),
        "evaluated_matches": [item.model_dump(mode="json") for item in result.evaluated_matches],
        "accepted_offer_ids": [
            item.supplier_ref.removeprefix("offer:") for item in result.accepted_matches
        ],
        "rejected_offer_ids": [
            item.supplier_ref.removeprefix("offer:") for item in result.rejected_matches
        ],
        "review_offer_ids": [
            item.supplier_ref.removeprefix("offer:") for item in result.review_matches
        ],
        "detail_failures": list(result.detail_failures),
        "visual_failures": list(result.visual_failures),
        "recommendation": recommendation.model_dump(mode="json") if recommendation else None,
    }


def _not_started_attempt(query: Any) -> dict[str, Any]:
    return {
        "query": query.model_dump(mode="json"),
        "result_count": None,
        "relevant_count": None,
        "hit_rate": None,
        "result_refs": [],
        "error_code": None,
        "status": "not_started",
        "backend": None,
    }


def evaluate_prefetched_suppliers(
    product: Any,
    suppliers: list[Any],
    understanding: AmazonProductUnderstanding,
    queries: list[Any],
    run_ref: str,
    *,
    query_execution: list[dict[str, Any]] | None = None,
) -> SourcingSliceResult:
    """Apply strict evidence gates to candidates gathered by the formal matcher.

    Per-query counts are recorded only when the active backend exposed an
    execution trace. Unknown attempts remain ``not_started`` with null counts.
    """
    result = SourcingSliceResult(
        run_ref=run_ref,
        iterations=1,
        understanding=understanding,
    )
    executions = {
        str(item.get("query") or ""): item
        for item in (query_execution or [])
        if isinstance(item, dict) and str(item.get("query") or "")
    }
    for query in queries:
        execution = executions.get(query.text)
        if execution is None:
            result.query_attempts.append(_not_started_attempt(query))
            continue
        if execution.get("status") != "completed":
            attempt = _attempt(query, error_code="INTERNAL", completed=False)
            attempt["backend"] = execution.get("backend")
            attempt["diagnostic"] = str(execution.get("error") or "")[:200] or None
            result.query_attempts.append(attempt)
            continue
        hits = [
            supplier for supplier in suppliers
            if query.text in (
                (supplier.raw_data or {}).get("search_queries", [])
                if isinstance(getattr(supplier, "raw_data", None), dict) else []
            )
        ]
        relevant = [supplier for supplier in hits if _default_relevance(query, supplier)]
        attempt = _attempt(
            query,
            hits=hits,
            relevant_count=len(relevant),
            error_code="NO_RESULTS" if not hits else None,
        )
        attempt["backend"] = execution.get("backend")
        result.query_attempts.append(attempt)

    raw_product = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    target_profile = raw_product.get("target_category_profile")
    for supplier in suppliers:
        if _is_mock(supplier):
            continue
        raw_supplier = (
            supplier.raw_data if isinstance(getattr(supplier, "raw_data", None), dict) else {}
        )
        visual = raw_supplier.get("visual_match")
        if not isinstance(visual, dict) or "is_match" not in visual:
            visual = None
        match = build_match_evidence(
            understanding,
            supplier,
            visual,
            target_profile=target_profile,
        )
        raw_supplier["strict_match_evidence"] = match.model_dump(mode="json")
        supplier.raw_data = raw_supplier
        result.evaluated_matches.append(match)
        if match.decision == "keep":
            result.suppliers.append(supplier)
            result.accepted_matches.append(match)
        elif match.decision == "reject":
            result.rejected_matches.append(match)
        else:
            result.review_matches.append(match)

    best = max(
        result.accepted_matches,
        key=lambda item: item.overall_confidence,
        default=None,
    )
    if best is not None:
        status = RecommendationStatus.WATCHLIST
    elif result.review_matches:
        status = RecommendationStatus.NEEDS_MANUAL_REVIEW
    elif result.rejected_matches:
        status = RecommendationStatus.REJECT
    else:
        status = RecommendationStatus.INSUFFICIENT_DATA
    rejection_reasons = list(dict.fromkeys(
        reason
        for item in result.rejected_matches
        for reason in item.mismatch_reasons
    ))
    if not result.evaluated_matches:
        rejection_reasons.append("no_real_supplier_evidence")
    manual_tasks = list(dict.fromkeys([
        *(
            f"verify_{name}"
            for item in result.review_matches
            for name in item.missing_evidence
        ),
        *(["calculate_profit", "evaluate_market"] if best is not None else []),
    ]))
    amazon_complete = (
        1.0
        if isinstance(target_profile, dict) and not target_profile.get("missing_critical")
        else 0.0
    )
    result.recommendation = RecommendationEvidence(
        asin=understanding.asin,
        supplier_offer_id=best.supplier_ref.removeprefix("offer:") if best else None,
        status=status,
        discovery_reason="Amazon US target-category candidate passed source discovery",
        amazon_completeness=amazon_complete,
        supplier_match_ref=best.supplier_ref if best else None,
        confirmed_specs=best.passed_reasons if best else [],
        unconfirmed_specs=best.missing_evidence if best else [],
        confidence=best.overall_confidence if best else 0.0,
        recommendation_reasons=["strict_supplier_match_passed"] if best else [],
        rejection_reasons=rejection_reasons,
        manual_verification_tasks=manual_tasks,
    )
    return result


def _persist_serialized_on_connection(connection: Any, payload: dict[str, Any]) -> None:
    run_ref = str(payload.get("run_ref") or "")
    asin = str(payload.get("asin") or "")
    if not run_ref or not asin:
        raise ValueError("sourcing evidence requires run_ref and asin")
    scope = {"run_ref": run_ref, "asin": asin}
    connection.execute(text("DELETE FROM query_attempts WHERE run_ref=:run_ref AND asin=:asin"), scope)
    connection.execute(text("DELETE FROM match_evidence WHERE run_ref=:run_ref AND asin=:asin"), scope)
    connection.execute(text("DELETE FROM sourcing_recommendations WHERE run_ref=:run_ref AND asin=:asin"), scope)
    for attempt in payload.get("query_attempts") or []:
        query = attempt.get("query") or {}
        status = attempt.get("status") or "not_started"
        completed = status == "completed"
        connection.execute(text("""INSERT INTO query_attempts (
            run_ref, asin, query_id, query_type, query_text, reason,
            excluded_brand_tokens_json, backend, result_count, relevant_count,
            retry_of, status, artifact_ref
        ) VALUES (:run_ref, :asin, :query_id, :query_type, :query_text, :reason,
            :tokens, :backend, :result_count, :relevant_count,
            :retry_of, :status, :artifact_ref)"""), {
            "run_ref": run_ref,
            "asin": asin,
            "query_id": query.get("query_id"),
            "query_type": query.get("query_type"),
            "query_text": query.get("text"),
            "reason": query.get("reason") or "target category deterministic query",
            "tokens": json.dumps(query.get("excluded_brand_tokens") or [], ensure_ascii=False),
            "backend": attempt.get("backend"),
            "result_count": attempt.get("result_count") if completed else None,
            "relevant_count": attempt.get("relevant_count") if completed else None,
            "retry_of": query.get("retry_of"),
            "status": status,
            "artifact_ref": json.dumps({
                "result_refs": attempt.get("result_refs") or [],
                "hit_rate": attempt.get("hit_rate"),
                "error_code": attempt.get("error_code"),
                "diagnostic": attempt.get("diagnostic"),
            }, ensure_ascii=False),
        })
    for match in payload.get("evaluated_matches") or []:
        offer_id = str(match.get("supplier_ref") or "").removeprefix("offer:")
        connection.execute(text("""INSERT INTO match_evidence
            (run_ref, asin, offer_id, decision, overall_confidence, evidence_json)
            VALUES (:run_ref, :asin, :offer_id, :decision, :confidence, :evidence)"""), {
            "run_ref": run_ref,
            "asin": asin,
            "offer_id": offer_id,
            "decision": match.get("decision"),
            "confidence": match.get("overall_confidence"),
            "evidence": json.dumps(match, ensure_ascii=False),
        })
    recommendation = payload.get("recommendation")
    if isinstance(recommendation, dict):
        connection.execute(text("""INSERT INTO sourcing_recommendations
            (run_ref, asin, offer_id, status, evidence_json)
            VALUES (:run_ref, :asin, :offer_id, :status, :evidence)"""), {
            "run_ref": run_ref,
            "asin": asin,
            "offer_id": recommendation.get("supplier_offer_id"),
            "status": recommendation.get("status"),
            "evidence": json.dumps(recommendation, ensure_ascii=False),
        })


def persist_serialized_sourcing_evidence(payload: dict[str, Any], bind: Any) -> None:
    """Persist a serialized evidence payload using a Session, Connection, or Engine."""
    if hasattr(bind, "execute"):
        _persist_serialized_on_connection(bind, payload)
        return
    with bind.begin() as connection:
        _persist_serialized_on_connection(connection, payload)


def finalize_record_sourcing_evidence(record: Any) -> dict[str, Any] | None:
    """Fold downstream profit, market, and scoring evidence into the decision."""
    product = getattr(record, "product", None)
    raw = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    payload = raw.get("sourcing_evidence")
    if not isinstance(payload, dict):
        return None
    recommendation = payload.get("recommendation")
    if not isinstance(recommendation, dict):
        return payload
    accepted = payload.get("accepted_offer_ids") or []
    score = getattr(record, "score", None)
    profit = getattr(record, "profit", None)
    market = getattr(record, "market", None)

    reasons = list(recommendation.get("rejection_reasons") or [])
    tasks = list(recommendation.get("manual_verification_tasks") or [])
    if accepted:
        if score is None:
            status = RecommendationStatus.NEEDS_MANUAL_REVIEW.value
            tasks.append("complete_scoring_evidence")
        elif not getattr(score, "passed_hard_filter", False):
            status = RecommendationStatus.REJECT.value
            reasons.extend(getattr(score, "rejection_reasons", None) or [])
        elif profit is None or market is None:
            status = RecommendationStatus.NEEDS_MANUAL_REVIEW.value
            if profit is None:
                tasks.append("calculate_profit")
            if market is None:
                tasks.append("evaluate_market")
        else:
            status = RecommendationStatus.RECOMMEND.value
            recommendation["recommendation_reasons"] = list(dict.fromkeys([
                *(recommendation.get("recommendation_reasons") or []),
                "strict_supplier_match_passed",
                "profit_market_and_hard_filters_passed",
            ]))
    else:
        status = str(
            recommendation.get("status") or RecommendationStatus.INSUFFICIENT_DATA.value
        )

    if profit is not None:
        recommendation["purchase_cost_ref"] = f"offer:{accepted[0]}:price" if accepted else None
        recommendation["profit_basis"] = {
            "selling_price": getattr(profit, "selling_price", None),
            "landed_cost": getattr(profit, "total_cost", None),
            "profit_margin": getattr(profit, "profit_margin", None),
            "refs": [f"pipeline:profit:{getattr(product, 'asin', '')}"],
        }
    if product is not None and all(
        getattr(product, name, None) is not None
        for name in ("weight_kg", "length_cm", "width_cm", "height_cm")
    ):
        recommendation["logistics_basis"] = {
            name: getattr(product, name)
            for name in ("weight_kg", "length_cm", "width_cm", "height_cm")
        }
        recommendation["logistics_basis"]["refs"] = [
            f"amazon:detail:{getattr(product, 'asin', '')}"
        ]
    market_raw = (
        market.raw_data if isinstance(getattr(market, "raw_data", None), dict) else {}
    )
    market_ref = market_raw.get("source_ref")
    if market_ref:
        if any(getattr(market, name, None) is not None for name in (
            "search_volume_monthly", "monthly_purchases", "est_monthly_sales"
        )):
            recommendation["demand_evidence_refs"] = [str(market_ref)]
        if any(getattr(market, name, None) is not None for name in (
            "competing_listings", "top10_revenue_share"
        )):
            recommendation["competition_evidence_refs"] = [str(market_ref)]
    recommendation["status"] = status
    recommendation["rejection_reasons"] = list(dict.fromkeys(reasons))
    recommendation["manual_verification_tasks"] = list(dict.fromkeys(tasks))
    payload["recommendation"] = recommendation
    raw["sourcing_evidence"] = payload
    product.raw_data = raw
    return payload


def run_sourcing_slice(product: Any, deps: SourcingSliceDependencies, run_ref: str,
                       allow_mock: bool = False) -> SourcingSliceResult:
    understanding = deps.understand(product)
    queries = generate_query_plan(understanding)
    result = SourcingSliceResult(run_ref=run_ref, iterations=0, understanding=understanding)
    seen: set[str] = set()
    mock_excluded = False
    for iteration in range(1, 3):
        result.iterations = iteration
        hit_rates: dict[str, float] = {}
        for query in queries:
            try:
                hits = list(deps.search(query) or [])
            except Exception as exc:
                code = _error_code(exc)
                result.query_attempts.append(_attempt(query, error_code=code, completed=False))
                if code in NON_RETRYABLE_CODES:
                    result.recommendation = _blocked_recommendation(product, "search", exc)
                    if deps.engine is not None:
                        _persist(result, deps.engine)
                    return result
                hit_rates[query.query_id] = 0.0
                continue
            real_by_id = {}
            for supplier in hits:
                if not allow_mock and _is_mock(supplier):
                    mock_excluded = True
                    continue
                real_by_id.setdefault(supplier.alibaba_offer_id, supplier)
            real_hits = list(real_by_id.values())
            assessor = deps.assess_relevance or _default_relevance
            relevant_hits = [supplier for supplier in real_hits if assessor(query, supplier)]
            usable = [supplier for supplier in relevant_hits if supplier.alibaba_offer_id not in seen]
            seen.update(supplier.alibaba_offer_id for supplier in usable)
            hit_rate = len(relevant_hits) / max(1, len(real_hits))
            hit_rates[query.query_id] = hit_rate
            error = "NO_RESULTS" if not real_hits else ("LOW_RELEVANCE" if hit_rate < 0.2 else None)
            attempt = _attempt(query, hits=real_hits, relevant_count=len(relevant_hits), error_code=error)
            attempt["mock_filtered_count"] = len(hits) - len([s for s in hits if not _is_mock(s)]) if not allow_mock else 0
            result.query_attempts.append(attempt)
            for supplier in usable:
                enriched = None
                last_exc = None
                attempt_count = 0
                for attempt_count in range(1, 3):
                    try:
                        enriched = deps.load_detail(supplier)
                        break
                    except Exception as exc:
                        last_exc = exc
                        code = _error_code(exc)
                        if code not in {"TIMEOUT", "RATE_LIMITED"}:
                            break
                if enriched is None:
                    exc = last_exc or RuntimeError("missing detail result")
                    code = _error_code(exc)
                    if code in NON_RETRYABLE_CODES:
                        if code in TERMINAL_BLOCK_CODES:
                            result.recommendation = _blocked_recommendation(product, "detail", exc)
                            if deps.engine is not None:
                                _persist(result, deps.engine)
                            return result
                    result.detail_failures.append({
                        "offer_ref": f"offer:{supplier.alibaba_offer_id}",
                        "error_code": code, "attempt_count": attempt_count,
                        "reason": f"supplier_detail_{code.casefold()}",
                    })
                    continue
                if not allow_mock and _is_mock(enriched):
                    mock_excluded = True
                    continue
                visual = None
                visual_exc = None
                visual_attempt_count = 0
                for visual_attempt_count in range(1, 3):
                    try:
                        visual = deps.verify_visual(product, enriched)
                        break
                    except Exception as exc:
                        visual_exc = exc
                        if _error_code(exc) not in RETRYABLE_VISUAL_CODES:
                            break
                if visual is None:
                    code = _error_code(visual_exc or RuntimeError("missing visual result"))
                    failure = {
                        "offer_ref": f"offer:{enriched.alibaba_offer_id}",
                        "error_code": code, "attempt_count": visual_attempt_count,
                        "reason": f"supplier_visual_{code.casefold()}",
                    }
                    result.visual_failures.append(failure)
                    match = build_match_evidence(understanding, enriched, {})
                    result.evaluated_matches.append(match)
                    result.review_matches.append(match)
                    continue
                visual_payload = visual.model_dump(mode="json") if hasattr(visual, "model_dump") else visual
                match = build_match_evidence(understanding, enriched, visual_payload)
                result.evaluated_matches.append(match)
                if match.decision == "keep":
                    result.suppliers.append(enriched)
                    result.accepted_matches.append(match)
                elif match.decision == "reject":
                    result.rejected_matches.append(match)
                else:
                    result.review_matches.append(match)
        if result.accepted_matches:
            break
        queries = rewrite_low_relevance_queries(understanding, queries, hit_rates, iteration)
        if not queries:
            break
    result.recommendation = _recommend(product, result, dict(deps.market_evidence(product) or {}), mock_excluded=mock_excluded)
    if deps.engine is not None:
        _persist(result, deps.engine)
    return result
