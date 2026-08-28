"""Recoverable execution adapter for the existing deterministic pipeline."""
from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from loguru import logger

from analyzers.profit_model import InsufficientCostEvidence, ProfitBreakdown
from analyzers.scorer import ScoreBreakdown, ScoringEvidenceError
from config.settings import settings
from db.models import MarketAnalysis, Product, ProfitSnapshot, RunLog, Score, Supplier
from execution.artifacts import ArtifactFile, ArtifactSetManager
from execution.coordinator import NodeResult, RecoverableRunCoordinator
from execution.handlers import (
    dump_market,
    dump_product,
    dump_profit,
    dump_score,
    dump_suppliers,
    load_market,
    load_product,
    load_profit,
    load_score,
    load_suppliers,
)
from execution.models import HumanActionRequired, NodeStatus
from execution.repository import ExecutionRepository

RUN_SCOPE_KEY = "run"
SCHEMA_VERSION = "1.0"


def _formal_match_suppliers(product, *, market_keywords=None, cancel_check=None):
    """Discover only via SellerSprite, then enrich/verify returned offer URLs."""
    from agent.sellersprite_1688_sourcing import run_sellersprite_1688_sourcing
    from matchers import _enrich_supplier_details, _title_fallback_keywords
    from matchers.verifier import Alibaba1688Verifier

    suppliers = run_sellersprite_1688_sourcing(
        product.asin,
        cancel_check=cancel_check,
        required=True,
    )
    if not suppliers:
        return []
    suppliers = _enrich_supplier_details(
        suppliers,
        settings,
        cancel_check=cancel_check,
    )
    seller_keywords = [
        value.strip() for value in (market_keywords or [])
        if isinstance(value, str) and value.strip()
    ]
    keywords = list(dict.fromkeys([*seller_keywords, *_title_fallback_keywords(product.title)]))
    verified = Alibaba1688Verifier().verify(
        suppliers=suppliers,
        product=product,
        analysis=None,
        search_keywords=keywords,
    )
    for supplier in verified:
        supplier.raw_data["candidate_discovery_source"] = "sellersprite_1688"
        supplier.raw_data["search_query_plan"] = {
            "queries": keywords,
            "market_keywords": seller_keywords,
            "market_source": "sellersprite_browser_extension",
        }
    return verified


def run_recoverable_pipeline(
    *,
    category: str,
    source_mode: str = "category",
    keyword: str | None = None,
    limit: int = 100,
    marketplace: str = "US",
    pipeline_version: str = "0.3.0",
    top_n: int = 20,
    export: bool = True,
    export_review_on_empty: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    stage_timeouts: dict[str, float] | None = None,
    seed_products: list[dict[str, Any]] | None = None,
) -> int:
    import pipeline.orchestrator as legacy

    site, mode, source_query = _validate_source(category, source_mode, keyword, marketplace)
    if seed_products:
        raise ValueError(
            "seed_products is no longer accepted by the formal workflow; "
            "Amazon crawler discovery is mandatory"
        )
    config = {
        "schema_version": SCHEMA_VERSION,
        "category": category,
        "source_mode": mode,
        "source_query": source_query,
        "keyword": keyword,
        "limit": int(limit),
        "marketplace": site,
        "pipeline_version": pipeline_version,
        "top_n": int(top_n),
        "export": bool(export),
        "export_review_on_empty": bool(export_review_on_empty),
        "allow_mock_suppliers": bool(settings.alibaba_allow_mock_suppliers),
        "stage_timeouts": stage_timeouts or _default_timeouts(),
    }
    api_calls = {
        "source_mode": mode,
        "source_query": source_query,
        "marketplace": site,
        "recoverable_config": config,
    }
    with legacy.session_scope() as session:
        run = RunLog(
            pipeline_version=pipeline_version,
            category=category if mode == "category" else None,
            marketplace=site,
            started_at=datetime.utcnow(),
            status="running",
            api_calls=api_calls,
        )
        session.add(run)
        session.flush()
        run_id = run.id
    logger.info(f"[run #{run_id}] recoverable start | source={mode}:{source_query} limit={limit}")
    return _execute(
        run_id=run_id,
        config=config,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def resume_recoverable_pipeline(
    run_id: int,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    import pipeline.orchestrator as legacy

    with legacy.session_scope() as session:
        run = session.get(RunLog, int(run_id))
        if run is None:
            raise KeyError(run_id)
        api_calls = run.api_calls if isinstance(run.api_calls, dict) else {}
        config = api_calls.get("recoverable_config")
        if not isinstance(config, dict):
            raise ValueError(f"run {run_id} predates recoverable execution metadata")
        run.status = "running"
        run.finished_at = None
        run.error_message = None
    return _execute(
        run_id=int(run_id),
        config=config,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def _execute(
    *,
    run_id: int,
    config: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None,
    cancel_check: Callable[[], bool] | None,
) -> int:
    import pipeline.orchestrator as legacy

    repository = ExecutionRepository(session_context=legacy.session_scope)
    artifact_manager = ArtifactSetManager(session_context=legacy.session_scope)
    coordinator = RecoverableRunCoordinator(
        run_id=run_id,
        repository=repository,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    coordinator.recover_stale()
    timeouts = config.get("stage_timeouts") or _default_timeouts()
    api_calls = _load_api_calls(legacy, run_id)

    source_input = {
        "schema_version": SCHEMA_VERSION,
        "source_mode": config["source_mode"],
        "source_query": config["source_query"],
        "limit": config["limit"],
        "marketplace": config["marketplace"],
    }

    def discover(_context):
        products = legacy._collect_source_products(
            config["source_mode"],
            config["source_query"],
            config["limit"],
            config["marketplace"],
        )
        legacy._attach_source_metadata(
            products, config["source_mode"], config["source_query"]
        )
        raw_count = len(products)
        products, removed = legacy._dedupe_products_by_asin(products)
        keyword_normalized = None
        keyword_warning = None
        if config["source_mode"] == "keyword" and products:
            raw = products[0].raw_data if isinstance(products[0].raw_data, dict) else {}
            keyword_normalized = raw.get("keyword_normalized")
            keyword_warning = raw.get("keyword_warning")
        return {
            "schema_version": SCHEMA_VERSION,
            "products": [dump_product(product) for product in products],
            "raw_product_count": raw_count,
            "duplicates_removed": removed,
            "keyword_normalized": keyword_normalized,
            "keyword_warning": keyword_warning,
        }

    source = coordinator.run_node(
        scope_type="run",
        scope_key=RUN_SCOPE_KEY,
        stage="source_discovery",
        input_snapshot=source_input,
        handler=discover,
        timeout_seconds=_timeout(timeouts, "crawl"),
    )
    if source.status != NodeStatus.SUCCEEDED.value:
        if source.status in {
            NodeStatus.HUMAN_REQUIRED.value,
            NodeStatus.RETRY_WAIT.value,
            NodeStatus.CANCELLED.value,
        }:
            _append_source_diagnostics(api_calls, source)
            _update_run(legacy, run_id, api_calls=api_calls)
            repository.update_run_status(run_id, export_required=False)
            return run_id
        _persist_source_failure(legacy, run_id, api_calls, source)
        if source.exception is not None:
            raise source.exception
        raise RuntimeError(source.error_detail or "source discovery failed")

    source_output = source.output_snapshot or {}
    product_payloads = source_output.get("products") or []
    api_calls.update({
        "amazon_source": len(product_payloads),
        "amazon_source_raw": source_output.get("raw_product_count"),
        "amazon_duplicates_removed": source_output.get("duplicates_removed"),
        "source_origin": f"amazon_crawler:{config['source_mode']}",
    })
    if source_output.get("keyword_normalized"):
        api_calls["keyword_normalized"] = source_output["keyword_normalized"]
    if source_output.get("keyword_warning"):
        api_calls["keyword_warning"] = source_output["keyword_warning"]
    _update_run(legacy, run_id, api_calls=api_calls, products_crawled=len(product_payloads))

    products = []
    source_dependency = _node_dependency(
        repository, run_id, RUN_SCOPE_KEY, "source_discovery", scope_type="run"
    )
    for index, payload in enumerate(product_payloads, 1):
        product = load_product(payload)
        asin = product.asin

        def write_product(output):
            restored = load_product(output["product"])
            return lambda session, _node: legacy._upsert_product(session, restored)

        result = coordinator.run_node(
            scope_type="asin",
            scope_key=asin,
            stage="ingest",
            input_snapshot={
                "schema_version": SCHEMA_VERSION,
                "product": payload,
                "source_dependency": source_dependency,
            },
            handler=lambda _context, item=payload: {  # type: ignore[misc]
                "schema_version": SCHEMA_VERSION,
                "product": item,
            },
            result_writer_factory=write_product,
            success_validator=lambda node, item=payload: _ingest_result_valid(legacy, node, item),  # type: ignore[misc]
        )
        if result.status == NodeStatus.SUCCEEDED.value:
            products.append(load_product(result.output_snapshot["product"]))

    if _stage_waiting(repository, run_id, "ingest"):
        repository.update_run_status(run_id, export_required=False)
        return run_id

    records_by_asin: dict[str, legacy.PipelineRecord] = {
        product.asin: legacy.PipelineRecord(product=product) for product in products
    }

    # SellerSprite evidence must exist before 1688 queries are planned.  The
    # market node depends only on ingest, so its successful artifact remains
    # reusable across match/profit retries.
    _run_sellersprite_market_stage(
        legacy=legacy,
        run_id=run_id,
        config=config,
        products=products,
        records_by_asin=records_by_asin,
        coordinator=coordinator,
        repository=repository,
        api_calls=api_calls,
        cancel_check=cancel_check,
        timeouts=timeouts,
    )
    _update_run(legacy, run_id, api_calls=api_calls)
    if _stage_waiting(repository, run_id, "market"):
        repository.update_run_status(run_id, export_required=False)
        return run_id

    # Supplier matching, independently recoverable per ASIN.
    matched = 0
    match_timeout = _timeout(timeouts, "match")
    previous_allow_mock = settings.alibaba_allow_mock_suppliers
    settings.alibaba_allow_mock_suppliers = bool(config.get("allow_mock_suppliers", False))
    try:
        for index, product in enumerate(products, 1):
            asin = product.asin
            market_keywords = _market_search_keywords(records_by_asin[asin].market)
            match_input = {
                "schema_version": SCHEMA_VERSION,
                "product": dump_product(product),
                "no_mock": not bool(settings.alibaba_allow_mock_suppliers),
                "ingest_dependency": _node_dependency(
                    repository, run_id, asin, "ingest"
                ),
                "market_dependency": _node_dependency(
                    repository, run_id, asin, "market"
                ),
                "market_keywords": market_keywords,
            }

            def match_handler(_context, item=product, hints=market_keywords):
                # Formal candidate discovery has one auditable source.  Other
                # matchers remain available for diagnostics, but are never an
                # automatic fallback from this workflow.
                suppliers = _formal_match_suppliers(
                    item,
                    market_keywords=hints,
                    cancel_check=cancel_check,
                )
                return {
                    "schema_version": SCHEMA_VERSION,
                    "product": dump_product(item),
                    "suppliers": dump_suppliers(suppliers),
                }

            def write_match(output):
                restored_product = load_product(output["product"])
                restored_suppliers = load_suppliers(output.get("suppliers"))

                def writer(session, _node):
                    product_row = legacy._upsert_product(session, restored_product)
                    for supplier in restored_suppliers:
                        legacy._upsert_supplier(session, product_row.id, supplier)
                    evidence = (
                        restored_product.raw_data.get("sourcing_evidence")
                        if isinstance(restored_product.raw_data, dict) else None
                    )
                    if isinstance(evidence, dict):
                        from matchers.sourcing_slice import persist_serialized_sourcing_evidence
                        persist_serialized_sourcing_evidence(evidence, session)
                return writer

            result = coordinator.run_node(
                scope_type="asin",
                scope_key=asin,
                stage="match",
                input_snapshot=match_input,
                handler=match_handler,
                timeout_seconds=match_timeout,
                result_writer_factory=write_match,
                success_validator=lambda node: _match_result_valid(legacy, node),
                progress_payload={
                    "index": index,
                    "total": len(products),
                    "message": f"Matching suppliers for {asin} ({index}/{len(products)})",
                },
            )
            if isinstance(result.exception, TimeoutError) and len(products) == 1:
                _update_run(
                    legacy,
                    run_id,
                    status="failed",
                    error_message=f"match stage timed out: {result.error_detail}",
                    api_calls=api_calls,
                )
                raise legacy.PipelineTimeout(f"match stage timed out: {result.error_detail}")
            if result.status == NodeStatus.SUCCEEDED.value:
                restored_product = load_product(result.output_snapshot["product"])
                suppliers = load_suppliers(result.output_snapshot.get("suppliers"))
                records_by_asin[asin].product = restored_product
                records_by_asin[asin].suppliers = suppliers
                matched += len(suppliers)
            elif result.status == NodeStatus.TIMED_OUT.value and len(products) == 1:
                _update_run(
                    legacy,
                    run_id,
                    status="failed",
                    error_message=f"match stage timed out: {result.error_detail}",
                    api_calls=api_calls,
                )
                raise legacy.PipelineTimeout(f"match stage timed out: {result.error_detail}")
            elif result.status in {
                NodeStatus.HUMAN_REQUIRED.value,
                NodeStatus.RETRY_WAIT.value,
                NodeStatus.CANCELLED.value,
                NodeStatus.TIMED_OUT.value,
            }:
                # These outcomes require external state, backoff, cancellation,
                # or explicit retry. Stop the ASIN loop at the first barrier so
                # one 1688 block cannot be repeated across the whole batch.
                break
    finally:
        settings.alibaba_allow_mock_suppliers = previous_allow_mock
    api_calls["supplier_match_attempts"] = len(products)
    api_calls["vision_analyzer"] = len(products)
    _update_run(legacy, run_id, api_calls=api_calls, suppliers_matched=matched)
    if _stage_waiting(repository, run_id, "match"):
        repository.update_run_status(run_id, export_required=False)
        return run_id

    # Profit and supplier ranking.
    calculated = 0
    supplier_duplicates_removed = 0
    for index, product in enumerate(products, 1):
        record = records_by_asin[product.asin]
        if not _stage_succeeded(repository, run_id, product.asin, "match"):
            continue
        profit_input = {
            "schema_version": SCHEMA_VERSION,
            "product": dump_product(product),
            "suppliers": dump_suppliers(record.suppliers),
            "profit_params": _file_fingerprint_payload("config/profit_params.yaml"),
            "match_dependency": _node_dependency(
                repository, run_id, product.asin, "match"
            ),
        }
        if not record.suppliers:
            coordinator.skip_node(
                scope_type="asin", scope_key=product.asin, stage="profit",
                input_snapshot=profit_input, reason="no matched suppliers",
            )
            continue

        before_count = len(record.suppliers)

        def profit_handler(_context, rec=record):
            rejection_reasons: list[str] = []
            try:
                profit = legacy._rank_suppliers_by_profit(rec.product, rec.suppliers)
            except InsufficientCostEvidence as exc:
                profit = None
                rejection_reasons.extend(legacy._evidence_rejection_reasons(exc))
            return {
                "schema_version": SCHEMA_VERSION,
                "product": dump_product(rec.product),
                "suppliers": dump_suppliers(rec.suppliers),
                "profit": dump_profit(profit),
                "rejection_reasons": rejection_reasons,
            }

        result = coordinator.run_node(
            scope_type="asin",
            scope_key=product.asin,
            stage="profit",
            input_snapshot=profit_input,
            handler=profit_handler,
            timeout_seconds=_timeout(timeouts, "profit"),
            result_writer_factory=lambda output: _profit_writer(legacy, output),
            success_validator=lambda node: _snapshot_result_valid(
                legacy, node, ProfitSnapshot, "profit"
            ),
            progress_payload={
                "index": index,
                "total": len(products),
                "message": f"Calculating profit for {product.asin} ({index}/{len(products)})",
            },
        )
        if result.status == NodeStatus.SUCCEEDED.value:
            output = result.output_snapshot
            record.suppliers = load_suppliers(output.get("suppliers"))
            record.profit = load_profit(output.get("profit"))
            record.rejection_reasons.extend(output.get("rejection_reasons") or [])
            supplier_duplicates_removed += max(before_count - len(record.suppliers), 0)
            if record.profit is not None:
                calculated += 1
    api_calls["supplier_duplicates_removed"] = supplier_duplicates_removed
    _update_run(legacy, run_id, api_calls=api_calls, profits_calculated=calculated)
    if _stage_waiting(repository, run_id, "profit"):
        repository.update_run_status(run_id, export_required=False)
        return run_id

    # Score only when profit exists. Missing evidence is a business
    # outcome recorded in the output, not an execution failure.
    for index, product in enumerate(products, 1):
        record = records_by_asin[product.asin]
        score_input = {
            "schema_version": SCHEMA_VERSION,
            "product": dump_product(product),
            "suppliers": dump_suppliers(record.suppliers),
            "profit": dump_profit(record.profit),
            "market": dump_market(record.market),
            "profit_dependency": _node_dependency(
                repository, run_id, product.asin, "profit"
            ),
            "market_dependency": _node_dependency(
                repository, run_id, product.asin, "market"
            ),
            "scoring_weights": _file_fingerprint_payload("config/scoring_weights.yaml"),
        }
        if record.profit is None:
            coordinator.skip_node(
                scope_type="asin", scope_key=product.asin, stage="score",
                input_snapshot=score_input, reason="profit result unavailable",
            )
            continue

        def score_handler(_context, rec=record):
            rejection_reasons: list[str] = []
            try:
                score = legacy.score_product(
                    product=rec.product,
                    profit_breakdown=rec.profit,
                    market_analysis=rec.market,
                    suppliers=rec.suppliers,
                )
            except ScoringEvidenceError as exc:
                score = None
                rejection_reasons.extend(legacy._evidence_rejection_reasons(exc))
            return {
                "schema_version": SCHEMA_VERSION,
                "product": dump_product(rec.product),
                "score": dump_score(score),
                "rejection_reasons": rejection_reasons,
            }

        result = coordinator.run_node(
            scope_type="asin", scope_key=product.asin, stage="score",
            input_snapshot=score_input, handler=score_handler,
            timeout_seconds=_timeout(timeouts, "score"),
            result_writer_factory=lambda output: _score_writer(legacy, output),
            success_validator=lambda node: _snapshot_result_valid(
                legacy, node, Score, "score"
            ),
            progress_payload={
                "index": index,
                "total": len(products),
                "message": f"Scoring {product.asin} ({index}/{len(products)})",
            },
        )
        if result.status == NodeStatus.SUCCEEDED.value:
            record.score = load_score(result.output_snapshot.get("score"))
            record.rejection_reasons.extend(result.output_snapshot.get("rejection_reasons") or [])

    if _stage_waiting(repository, run_id, "score"):
        repository.update_run_status(run_id, export_required=False)
        return run_id

    # Run-level aggregate nodes are fingerprinted by all ASIN score states, so
    # recovering B invalidates only filter/export while A and C remain cached.
    records = [records_by_asin[product.asin] for product in products]
    legacy._finalize_sourcing_evidence(records)
    aggregate_refs = [
        _node_dependency(repository, run_id, product.asin, "score") for product in products
    ]
    filter_input = {
        "schema_version": SCHEMA_VERSION,
        "records": [_dump_record(record) for record in records],
        "score_dependencies": aggregate_refs,
        "top_n": config["top_n"],
    }

    def filter_handler(_context):
        restored = [_load_record(payload, legacy) for payload in filter_input["records"]]
        ranked = legacy.rank_candidates(restored, top_n=None)
        candidates, removed = legacy._dedupe_records_by_asin(ranked)
        if config["top_n"]:
            candidates = candidates[:config["top_n"]]
        return {
            "schema_version": SCHEMA_VERSION,
            "records": [_dump_record(record) for record in restored],
            "candidates": [_dump_record(record) for record in candidates],
            "duplicates_removed": removed,
        }

    filter_result = coordinator.run_node(
        scope_type="run", scope_key=RUN_SCOPE_KEY, stage="filter",
        input_snapshot=filter_input, handler=filter_handler,
    )
    filter_output = filter_result.output_snapshot or {"records": [], "candidates": []}
    candidates = [_load_record(payload, legacy) for payload in filter_output.get("candidates") or []]
    api_calls["candidate_duplicates_removed"] = filter_output.get("duplicates_removed", 0)
    _update_run(
        legacy,
        run_id,
        api_calls=api_calls,
        candidates_after_filter=len(candidates),
    )

    # One workbook contains both accepted candidates and rejected/pending
    # evidence.  Keep candidate order first, followed by every other product.
    restored_records = [
        _load_record(payload, legacy) for payload in filter_output.get("records") or []
    ]
    candidate_asins = {record.product.asin for record in candidates}
    export_records = [*candidates, *(
        record for record in restored_records if record.product.asin not in candidate_asins
    )]

    export_input = {
        "schema_version": SCHEMA_VERSION,
        "filter_output_fingerprint": _node_dependency(
            repository, run_id, RUN_SCOPE_KEY, "filter", scope_type="run"
        ),
        "records": [_dump_record(record) for record in export_records],
        "enabled": config["export"],
    }
    if not config["export"]:
        coordinator.skip_node(
            scope_type="run", scope_key=RUN_SCOPE_KEY, stage="export",
            input_snapshot=export_input, reason="export disabled by caller",
        )
    elif not export_records:
        coordinator.skip_node(
            scope_type="run", scope_key=RUN_SCOPE_KEY, stage="export",
            input_snapshot=export_input, reason="no exportable records",
        )
    else:
        def export_handler(context):
            artifact_set_id = f"run-{run_id}-export-g{context.generation}"
            reconciled = artifact_manager.reconcile(artifact_set_id)
            if reconciled:
                return _artifact_output(artifact_set_id, reconciled)
            restored = [_load_record(payload, legacy) for payload in export_input["records"]]
            staging_dir = settings.export_dir / ".staging" / artifact_set_id
            staging_reports = staging_dir / "reports"
            staging_dir.mkdir(parents=True, exist_ok=True)
            base_name = f"candidates_run_{run_id}_g{context.generation}"
            excel_temp = legacy.export_excel(restored, staging_dir / f"{base_name}.xlsx")
            json_temp = legacy.export_json(restored, staging_dir / f"{base_name}.json")
            files = [
                ArtifactFile(
                    logical_name="excel",
                    artifact_type="xlsx",
                    temporary_path=excel_temp,
                    final_path=settings.export_dir / f"{base_name}.xlsx",
                ),
                ArtifactFile(
                    logical_name="json",
                    artifact_type="json",
                    temporary_path=json_temp,
                    final_path=settings.export_dir / f"{base_name}.json",
                ),
            ]
            manifests = artifact_manager.publish(
                context=context,
                artifact_set_id=artifact_set_id,
                files=files,
            )
            _remove_empty_staging_dirs(staging_reports, staging_dir)
            return _artifact_output(artifact_set_id, manifests)

        coordinator.run_node(
            scope_type="run", scope_key=RUN_SCOPE_KEY, stage="export",
            input_snapshot=export_input, handler=export_handler,
            timeout_seconds=_timeout(timeouts, "export"),
            success_validator=lambda node: _artifact_result_valid(artifact_manager, node),
        )

    status = repository.update_run_status(run_id, export_required=bool(config["export"] and export_records))
    _update_run(legacy, run_id, api_calls=api_calls)
    logger.info(f"[run #{run_id}] recoverable finish | status={status} candidates={len(candidates)}")
    return run_id


def _run_sellersprite_market_stage(
    *,
    legacy,
    run_id: int,
    config: dict[str, Any],
    products: list,
    records_by_asin: dict,
    coordinator: RecoverableRunCoordinator,
    repository: ExecutionRepository,
    api_calls: dict[str, Any],
    cancel_check,
    timeouts: dict[str, Any],
) -> None:
    """Collect browser-extension keyword evidence before supplier search."""
    configured_market_cap = max(int(settings.mjjl_max_products_per_run or 0), 0)
    # A positive legacy cap enables the browser stage, but the formal workflow
    # collects evidence for every Amazon product. Explicit zero remains an
    # offline/diagnostic switch used by unit tests and maintenance commands.
    market_cap = len(products) if configured_market_cap > 0 else 0
    skipped_cap = max(len(products) - market_cap, 0)
    if skipped_cap:
        api_calls["mjjl_skipped_cap"] = skipped_cap

    browser_dependencies = None
    try:
        from agent.sellersprite_service import SellerSpriteDependencies

        candidate = SellerSpriteDependencies(is_cancelled=cancel_check)
        if candidate.browser_enabled and candidate.profile is not None and candidate.session_factory is not None:
            browser_dependencies = candidate
    except Exception as exc:
        logger.info(f"SellerSprite browser dependency unavailable: {exc}")


    browser_market_source = "sellersprite_browser_extension" if browser_dependencies else "unavailable"
    api_calls["market_source"] = browser_market_source
    api_calls["market_skipped_cap"] = skipped_cap
    browser_sourcing_run_id = str(uuid5(NAMESPACE_URL, f"amazon-selector:sourcing-run:{run_id}"))

    for index, product in enumerate(products, 1):
        existing_market = _market_from_seller_research(product, config)
        market_source = "seller_research_export" if existing_market else browser_market_source
        market_input = {
            "schema_version": SCHEMA_VERSION,
            "product": dump_product(product),
            "ingest_dependency": _node_dependency(repository, run_id, product.asin, "ingest"),
            "source_query": config["source_query"],
            "market_source": market_source,
        }
        if existing_market is not None:
            result = coordinator.run_node(
                scope_type="asin", scope_key=product.asin, stage="market",
                input_snapshot=market_input,
                handler=lambda _context, item=product, market=existing_market: {  # type: ignore[misc]
                    "schema_version": SCHEMA_VERSION,
                    "product": dump_product(item),
                    "market": dump_market(market),
                },
                timeout_seconds=_timeout(timeouts, "market"),
                result_writer_factory=lambda output: _market_writer(legacy, output),
                success_validator=lambda node: _snapshot_result_valid(
                    legacy, node, MarketAnalysis, "market"
                ),
                progress_payload={
                    "index": index,
                    "total": len(products),
                    "message": f"Reusing SellerSprite research evidence for {product.asin} ({index}/{len(products)})",
                },
            )
            if result.status == NodeStatus.SUCCEEDED.value:
                records_by_asin[product.asin].market = load_market(
                    result.output_snapshot.get("market")
                )
                api_calls["seller_research_market_reused"] = (
                    api_calls.get("seller_research_market_reused", 0) + 1
                )
            continue
        if index > market_cap:
            coordinator.skip_node(
                scope_type="asin", scope_key=product.asin, stage="market",
                input_snapshot=market_input, reason="market cap not selected",
            )
            continue
        if browser_dependencies is None:
            result = coordinator.run_node(
                scope_type="asin", scope_key=product.asin, stage="market",
                input_snapshot=market_input,
                handler=lambda _context, asin=product.asin: (_ for _ in ()).throw(
                    HumanActionRequired(
                        "EXTENSION_UNAVAILABLE",
                        f"SellerSprite market evidence unavailable for {asin}",
                        instructions=(
                            "请在专用 Chrome 中启用并登录卖家精灵插件，确认反查关键词导出可用，"
                            "然后继续任务。"
                        ),
                    )
                ),
            )
            if result.status == NodeStatus.HUMAN_REQUIRED.value:
                break
            continue

        def market_handler(_context, item=product):
            from agent.sellersprite_service import run_reverse_keyword_export
            from agent.tools.sellersprite_browser import SellerSpriteWorkflowError
            from analyzers.sellersprite_browser_market import market_from_reverse_keyword_result

            browser_result = run_reverse_keyword_export(
                item.asin,
                sourcing_run_id=browser_sourcing_run_id,
                dependencies=browser_dependencies,
            )
            if browser_result.status == "NEEDS_HUMAN":
                code = browser_result.error_code or "SELLERSPRITE_HUMAN_REQUIRED"
                raise HumanActionRequired(
                    code,
                    f"SellerSprite browser action required for {item.asin}",
                    instructions=(
                        "Resolve the visible SellerSprite state in the attached Chrome "
                        "session, then resume this ASIN market node."
                    ),
                )
            if browser_result.status != "SUCCESS":
                raise SellerSpriteWorkflowError(browser_result.error_code or browser_result.status)
            market = market_from_reverse_keyword_result(
                asin=item.asin,
                marketplace=config["marketplace"],
                result_data=browser_result.data,
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "product": dump_product(item),
                "market": dump_market(market),
            }

        result = coordinator.run_node(
            scope_type="asin", scope_key=product.asin, stage="market",
            input_snapshot=market_input, handler=market_handler,
            timeout_seconds=_timeout(timeouts, "market"),
            result_writer_factory=lambda output: _market_writer(legacy, output),
            success_validator=lambda node: _snapshot_result_valid(
                legacy, node, MarketAnalysis, "market"
            ),
            progress_payload={
                "index": index,
                "total": len(products),
                "message": f"Collecting SellerSprite keywords for {product.asin} ({index}/{len(products)})",
            },
        )
        if result.status == NodeStatus.SUCCEEDED.value:
            records_by_asin[product.asin].market = load_market(result.output_snapshot.get("market"))
            if result.executed:
                api_calls["sellersprite_browser_exports"] = api_calls.get("sellersprite_browser_exports", 0) + 1
        elif result.status in {
            NodeStatus.HUMAN_REQUIRED.value,
            NodeStatus.RETRY_WAIT.value,
            NodeStatus.CANCELLED.value,
        }:
            # SellerSprite states such as extension-unavailable, login, quota,
            # or CAPTCHA require the user/browser to change state. Do not
            # consume more ASINs while that prerequisite is unresolved.
            break


def _market_from_seller_research(product, config: dict[str, Any]):
    """Reuse real market metrics already carried by a SellerSprite shortlist."""
    raw = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    monthly_sales = raw.get("research_monthly_sales")
    monthly_revenue = raw.get("research_monthly_revenue")
    fit_score = raw.get("research_fit_score")
    if monthly_sales is None and monthly_revenue is None and fit_score is None:
        return None

    from analyzers.maijiajingling import MarketAnalysisDTO

    source_query = str(raw.get("source_query") or config.get("source_query") or "").strip()
    return MarketAnalysisDTO(
        asin=product.asin,
        marketplace=config["marketplace"],
        brand=product.brand,
        seller_name=raw.get("research_seller"),
        title=product.title,
        est_monthly_sales=int(monthly_sales) if monthly_sales is not None else None,
        price=product.price,
        currency="USD" if product.price is not None else None,
        rating=product.rating,
        review_count=product.review_count,
        main_keyword=source_query or None,
        opportunity_score=float(fit_score) if fit_score is not None else None,
        raw_data={
            "source_provider": "sellersprite",
            "source_type": "seller_research_export",
            "source_query": source_query or None,
            "research_run_id": raw.get("research_run_id"),
            "monthly_sales": monthly_sales,
            "monthly_revenue": monthly_revenue,
            "fit_score": fit_score,
            "fit_category": raw.get("research_fit_category"),
            "fit_reasons": list(raw.get("research_fit_reasons") or []),
        },
    )


def _market_search_keywords(market) -> list[str]:
    if market is None:
        return []
    values: list[str] = []
    raw = getattr(market, "raw_data", None) or {}
    for row in raw.get("keyword_candidates") or []:
        keyword = row.get("keyword") if isinstance(row, dict) else None
        if isinstance(keyword, str) and keyword.strip() and keyword.strip() not in values:
            values.append(keyword.strip())
    main_keyword = getattr(market, "main_keyword", None)
    if isinstance(main_keyword, str) and main_keyword.strip() and main_keyword.strip() not in values:
        values.insert(0, main_keyword.strip())
    return values[:10]


def _validate_source(category, source_mode, keyword, marketplace) -> tuple[str, str, str]:
    site = (marketplace or "US").strip().upper()
    if site != "US":
        raise ValueError("marketplace is fixed to Amazon US")
    mode = (source_mode or "category").strip().lower()
    if mode not in {"category", "keyword"}:
        raise ValueError("source_mode must be category or keyword")
    source_query = (keyword or "").strip() if mode == "keyword" else (category or "").strip()
    if not source_query:
        raise ValueError("keyword is required" if mode == "keyword" else "category is required")
    return site, mode, source_query


def _default_timeouts() -> dict[str, float]:
    return {
        "crawl": settings.pipeline_crawl_timeout_seconds,
        "match": settings.pipeline_match_timeout_seconds,
        "profit": settings.pipeline_profit_timeout_seconds,
        "market": settings.pipeline_market_timeout_seconds,
        "score": settings.pipeline_score_timeout_seconds,
        "export": settings.pipeline_export_timeout_seconds,
    }


def _timeout(timeouts: dict[str, Any], stage: str) -> float | None:
    value = timeouts.get(stage)
    return float(value) if value is not None and float(value) > 0 else None


def _load_api_calls(legacy, run_id: int) -> dict[str, Any]:
    with legacy.session_scope() as session:
        run = session.get(RunLog, run_id)
        return dict(run.api_calls or {})


def _update_run(legacy, run_id: int, **values: Any) -> None:
    with legacy.session_scope() as session:
        run = session.get(RunLog, run_id)
        if run is None:
            raise KeyError(run_id)
        for key, value in values.items():
            setattr(run, key, value)


def _persist_source_failure(legacy, run_id, api_calls, result: NodeResult) -> None:
    _append_source_diagnostics(api_calls, result)
    _update_run(
        legacy,
        run_id,
        status="failed",
        finished_at=datetime.utcnow(),
        error_message=(result.error_detail or "source discovery failed")[:2000],
        api_calls=api_calls,
    )


def _append_source_diagnostics(api_calls: dict[str, Any], result: NodeResult) -> None:
    if result.exception is None:
        return
    try:
        from crawlers.amazon_search import search_failure_details
        api_calls.update(search_failure_details(result.exception))
    except Exception:
        pass


def _result_key(node) -> str:
    value = lambda name: node.get(name) if isinstance(node, dict) else getattr(node, name)
    return (
        f"execution:{value('id')}:{value('generation')}:"
        f"{value('input_fingerprint') or 'none'}"
    )


def _ingest_result_valid(legacy, node: dict[str, Any], payload: dict[str, Any]) -> bool:
    product = load_product(payload)
    with legacy.session_scope() as session:
        return session.query(Product.id).filter_by(
            asin=product.asin,
            marketplace=product.marketplace,
        ).scalar() is not None


def _match_result_valid(legacy, node: dict[str, Any]) -> bool:
    output = node.get("output_snapshot") or {}
    suppliers = load_suppliers(output.get("suppliers"))
    if not suppliers:
        return True
    product = load_product(output["product"])
    offer_ids = {supplier.alibaba_offer_id for supplier in suppliers}
    with legacy.session_scope() as session:
        product_id = session.query(Product.id).filter_by(
            asin=product.asin,
            marketplace=product.marketplace,
        ).scalar()
        if product_id is None:
            return False
        persisted = {
            row[0]
            for row in session.query(Supplier.alibaba_offer_id).filter(
                Supplier.product_id == product_id,
                Supplier.alibaba_offer_id.in_(offer_ids),
            ).all()
        }
        return persisted == offer_ids


def _snapshot_result_valid(legacy, node: dict[str, Any], model, output_key: str) -> bool:
    output = node.get("output_snapshot") or {}
    value = output.get(output_key)
    if value is None:
        return True
    if output_key == "market" and not value.get("asin"):
        return True
    key = _result_key(node)
    with legacy.session_scope() as session:
        return session.query(model.id).filter_by(result_key=key).scalar() is not None


def _artifact_result_valid(
    manager: ArtifactSetManager,
    node: dict[str, Any],
) -> bool:
    output = node.get("output_snapshot") or {}
    artifact_set_id = output.get("artifact_set_id")
    if not artifact_set_id:
        return False
    manifests = manager.reconcile(str(artifact_set_id))
    if not manifests:
        return False
    logical_names = {row["logical_name"] for row in manifests}
    expected = {
        row.get("logical_name")
        for row in (output.get("manifests") or [])
        if isinstance(row, dict) and row.get("logical_name")
    }
    return {"excel", "json"} <= logical_names and (
        not expected or logical_names == expected
    ) and all(
        row["status"] == "committed" for row in manifests
    )


def _profit_writer(legacy, output):
    product = load_product(output["product"])
    suppliers = load_suppliers(output.get("suppliers"))
    profit = load_profit(output.get("profit"))

    def writer(session, node):
        if profit is None or not suppliers:
            return
        required = [field.name for field in fields(ProfitBreakdown)]
        if any(getattr(profit, name, None) is None for name in required):
            return
        key = _result_key(node)
        if session.query(ProfitSnapshot).filter_by(result_key=key).one_or_none():
            return
        product_row = legacy._upsert_product(session, product)
        supplier_row = legacy._upsert_supplier(session, product_row.id, suppliers[0])
        session.add(ProfitSnapshot(
            product_id=product_row.id,
            supplier_id=supplier_row.id,
            selling_price=float(profit.selling_price),
            batch_qty=200,
            purchase_cost=float(profit.purchase_cost),
            shipping_cost=float(profit.shipping_cost),
            fba_fee=float(profit.fba_fee),
            commission=float(profit.commission),
            ad_cost=float(profit.ad_cost),
            return_loss=float(profit.return_loss),
            exchange_loss=float(profit.exchange_loss),
            other_costs=float(profit.other_costs),
            total_cost=float(profit.total_cost),
            net_profit=float(profit.net_profit),
            profit_margin=float(profit.profit_margin),
            params_version="runtime",
            result_key=key,
        ))
    return writer


def _market_writer(legacy, output):
    product = load_product(output["product"])
    market = load_market(output.get("market"))

    def writer(session, node):
        if market is None or not bool(market):
            return
        key = _result_key(node)
        if session.query(MarketAnalysis).filter_by(result_key=key).one_or_none():
            return
        product_row = legacy._upsert_product(session, product)
        session.add(MarketAnalysis(
            product_id=product_row.id,
            main_keyword=market.main_keyword,
            search_volume_monthly=market.search_volume_monthly,
            keyword_difficulty=market.keyword_difficulty,
            competing_listings=market.competing_listings,
            top10_revenue_share=market.top10_revenue_share,
            avg_review_count_top10=market.avg_review_count_top10,
            avg_price_top10=market.avg_price_top10,
            opportunity_score=market.opportunity_score,
            seasonality=market.seasonality,
            raw_data=market.raw_data,
            result_key=key,
        ))
    return writer


def _score_writer(legacy, output):
    product = load_product(output["product"])
    score = load_score(output.get("score"))

    def writer(session, node):
        if score is None:
            return
        required = [field.name for field in fields(ScoreBreakdown)]
        if any(getattr(score, name, None) is None for name in required):
            return
        key = _result_key(node)
        if session.query(Score).filter_by(result_key=key).one_or_none():
            return
        product_row = legacy._upsert_product(session, product)
        session.add(Score(
            product_id=product_row.id,
            profit_score=float(score.profit_score),
            demand_score=float(score.demand_score),
            competition_score=float(score.competition_score),
            supply_score=float(score.supply_score),
            logistics_score=float(score.logistics_score),
            risk_score=float(score.risk_score),
            total_score=float(score.total_score),
            passed_hard_filter=bool(score.passed_hard_filter),
            rejection_reasons=list(score.rejection_reasons or []),
            weights_version="runtime",
            result_key=key,
        ))
    return writer


def _dump_record(record) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "product": dump_product(record.product),
        "suppliers": dump_suppliers(record.suppliers),
        "profit": dump_profit(record.profit),
        "market": dump_market(record.market),
        "score": dump_score(record.score),
        "rejection_reasons": list(record.rejection_reasons or []),
    }


def _load_record(payload: dict[str, Any], legacy):
    return legacy.PipelineRecord(
        product=load_product(payload["product"]),
        suppliers=load_suppliers(payload.get("suppliers")),
        profit=load_profit(payload.get("profit")),
        market=load_market(payload.get("market")),
        score=load_score(payload.get("score")),
        rejection_reasons=list(payload.get("rejection_reasons") or []),
    )


def _find_node(repository, run_id, scope_key, stage, scope_type="asin"):
    return next((
        node for node in repository.list_nodes(run_id)
        if node["scope_type"] == scope_type
        and node["scope_key"] == scope_key
        and node["stage"] == stage
    ), None)


def _stage_succeeded(repository, run_id, asin, stage) -> bool:
    node = _find_node(repository, run_id, asin, stage)
    return bool(node and node["status"] == NodeStatus.SUCCEEDED.value)


def _stage_waiting(repository, run_id: int, stage: str) -> bool:
    return any(
        node["stage"] == stage
        and node["status"] in {
            NodeStatus.PENDING.value,
            NodeStatus.RUNNING.value,
            NodeStatus.RETRY_WAIT.value,
            NodeStatus.HUMAN_REQUIRED.value,
            NodeStatus.CANCELLED.value,
        }
        for node in repository.list_nodes(run_id)
    )


def _node_dependency(repository, run_id, scope_key, stage, scope_type="asin"):
    node = _find_node(repository, run_id, scope_key, stage, scope_type=scope_type)
    if not node:
        return {"scope_key": scope_key, "stage": stage, "status": "missing"}
    return {
        "scope_key": scope_key,
        "stage": stage,
        "status": node["status"],
        "generation": node["generation"],
        "output_fingerprint": node["output_fingerprint"],
    }


def _file_fingerprint_payload(relative_path: str) -> dict[str, Any]:
    from hashlib import sha256
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / relative_path
    if not path.exists():
        return {"path": relative_path, "sha256": None}
    return {"path": relative_path, "sha256": sha256(path.read_bytes()).hexdigest()}


def _artifact_output(artifact_set_id: str, manifests: list[dict[str, Any]]) -> dict[str, Any]:
    excel = next((row["final_path"] for row in manifests if row["logical_name"] == "excel"), None)
    json_path = next((row["final_path"] for row in manifests if row["logical_name"] == "json"), None)
    markdown = [
        row["final_path"] for row in manifests
        if str(row["logical_name"]).startswith("markdown:")
    ]
    if not excel or not json_path:
        raise RuntimeError(f"artifact set missing required export files: {artifact_set_id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_set_id": artifact_set_id,
        "excel": excel,
        "json": json_path,
        "markdown": markdown,
        "manifests": manifests,
    }


def _remove_empty_staging_dirs(*paths) -> None:
    for path in paths:
        try:
            path.rmdir()
        except OSError:
            pass
