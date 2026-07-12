"""Bounded, evidence-gated supplier sourcing coordinator."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import text

from matchers.alibaba_detail import BlockedOfferPage
from matchers.match_evidence import build_match_evidence
from matchers.query_planner import generate_query_plan, rewrite_low_relevance_queries
from schemas.sourcing import MatchEvidence, RecommendationEvidence, RecommendationStatus


TERMINAL_BLOCK_CODES = {"AUTH_REQUIRED", "CAPTCHA"}
STABLE_SEARCH_ERROR_CODES = {
    "AUTH_REQUIRED", "CAPTCHA", "RATE_LIMITED", "TIMEOUT", "NO_RESULTS", "LOW_RELEVANCE",
    "INVALID_INPUT", "MISSING_REQUIRED_DATA", "INTERNAL",
}
NON_RETRYABLE_CODES = {"AUTH_REQUIRED", "CAPTCHA", "INVALID_INPUT", "MISSING_REQUIRED_DATA", "INTERNAL"}


@dataclass
class SourcingSliceDependencies:
    understand: Callable
    search: Callable
    load_detail: Callable
    verify_visual: Callable
    market_evidence: Callable
    engine: Any | None = None


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
    code = str(getattr(exc, "error_code", "") or "").upper()
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


def _attempt(query: Any, *, hits: list[Any] | None = None, relevant_count: int = 0,
             error_code: str | None = None) -> dict:
    result_count = len(hits or [])
    rate = relevant_count / max(1, result_count)
    return {
        "query": query.model_dump(mode="json"), "result_count": result_count,
        "relevant_count": relevant_count, "hit_rate": rate,
        "result_refs": [f"offer:{item.alibaba_offer_id}" for item in (hits or [])],
        "error_code": error_code or ("NO_RESULTS" if not result_count else None),
    }


def _recommend(product: Any, result: SourcingSliceResult, market: dict[str, Any], *,
               mock_excluded: bool) -> RecommendationEvidence:
    best = max(result.accepted_matches, key=lambda item: item.overall_confidence, default=None)
    supplier = next((s for s in result.suppliers if best and f"offer:{s.alibaba_offer_id}" == best.supplier_ref), None)
    detail = getattr(supplier, "raw_data", {}).get("detail", {}) if supplier else {}
    missing: list[str] = []
    logistics = market.get("logistics_basis")
    profit = market.get("profit_basis")
    logistics_valid = isinstance(logistics, dict) and bool(logistics.get("refs")) and all(
        _positive(logistics.get(key)) for key in ("weight_kg", "length_cm", "width_cm", "height_cm")
    )
    profit_valid = isinstance(profit, dict) and bool(profit.get("refs")) and all(
        _positive(profit.get(key)) for key in ("selling_price", "landed_cost", "profit_margin")
    )
    checks = {
        "demand_refs": bool(market.get("demand_refs")),
        "competition_refs": bool(market.get("competition_refs")),
        "purchase_cost_ref": bool(market.get("purchase_cost_ref")),
        "logistics_basis": logistics_valid,
        "profit_basis": profit_valid,
        "real_price": bool(supplier) and (_positive(getattr(supplier, "base_price_cny", None)) or _positive(detail.get("base_price_cny"))),
        "real_moq": bool(supplier) and (_positive(getattr(supplier, "moq", None)) or _positive(detail.get("moq"))),
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
    return RecommendationEvidence(
        asin=product.asin,
        supplier_offer_id=best.supplier_ref.removeprefix("offer:") if best else None,
        status=status, discovery_reason="Amazon US source candidate passed initial discovery",
        amazon_completeness=market.get("amazon_completeness", 0.0),
        demand_evidence_refs=market.get("demand_refs", []),
        competition_evidence_refs=market.get("competition_refs", []),
        supplier_match_ref=best.supplier_ref if best else None,
        confirmed_specs=best.passed_reasons if best else [],
        unconfirmed_specs=best.missing_evidence if best else [],
        purchase_cost_ref=market.get("purchase_cost_ref") if best else None,
        logistics_basis=logistics or {},
        profit_basis=profit or {}, risks=market.get("risks", []),
        confidence=best.overall_confidence if best else 0.0,
        recommendation_reasons=["minimum_supplier_evidence_passed", "decision_evidence_complete"] if status is RecommendationStatus.RECOMMEND else [],
        rejection_reasons=rejection,
        manual_verification_tasks=[f"verify_{name}" for name in missing],
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
            completed = attempt["error_code"] in (None, "NO_RESULTS", "LOW_RELEVANCE")
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
                "retry_of": query.get("retry_of"), "status": "completed" if completed else "failed",
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
                result.query_attempts.append(_attempt(query, error_code=code))
                if code in NON_RETRYABLE_CODES:
                    result.recommendation = _blocked_recommendation(product, "search", exc)
                    if deps.engine is not None:
                        _persist(result, deps.engine)
                    return result
                hit_rates[query.query_id] = 0.0
                continue
            usable = []
            for supplier in hits:
                if not allow_mock and _is_mock(supplier):
                    mock_excluded = True
                    continue
                if supplier.alibaba_offer_id not in seen:
                    seen.add(supplier.alibaba_offer_id)
                    usable.append(supplier)
            hit_rate = len(usable) / max(1, len(usable))
            hit_rates[query.query_id] = hit_rate
            error = "NO_RESULTS" if not usable else None
            attempt = _attempt(query, hits=usable, relevant_count=len(usable), error_code=error)
            attempt["mock_filtered_count"] = len(hits) - len([s for s in hits if not _is_mock(s)]) if not allow_mock else 0
            result.query_attempts.append(attempt)
            for supplier in usable:
                try:
                    enriched = deps.load_detail(supplier)
                except Exception as exc:
                    code = _error_code(exc)
                    if code in NON_RETRYABLE_CODES:
                        result.recommendation = _blocked_recommendation(product, "detail", exc)
                        if deps.engine is not None:
                            _persist(result, deps.engine)
                        return result
                    continue
                if not allow_mock and _is_mock(enriched):
                    mock_excluded = True
                    continue
                visual = deps.verify_visual(product, enriched)
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
