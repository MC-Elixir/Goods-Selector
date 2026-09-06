from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent.sellersprite_1688_sourcing import run_sellersprite_1688_sourcing
from agent.tools.sellersprite_browser import SellerSpriteWorkflowError
from execution.models import StageContext
from execution.policies import classify_error
from tests.test_sellersprite_1688_sourcing import FakeDeps, FakeSession


def test_formal_export_failure_is_retryable_not_empty():
    with pytest.raises(SellerSpriteWorkflowError) as caught:
        run_sellersprite_1688_sourcing(
            "B00Q7OAN50", dependencies=FakeDeps(FakeSession(error="EXPORT_FAILED")), required=True,
        )
    assert classify_error(caught.value).disposition.value == "retryable"


def test_formal_unparseable_offers_are_not_empty_success():
    with pytest.raises(SellerSpriteWorkflowError) as caught:
        run_sellersprite_1688_sourcing(
            "B00Q7OAN50", required=True,
            dependencies=FakeDeps(FakeSession(suppliers=[{"title": "missing identity"}])),
        )
    assert caught.value.error_code == "INVALID_EXPORT"


def test_same_request_survives_backend_restart_without_second_enqueue(tmp_path, monkeypatch):
    from agent.runner import AgentRuntime
    from agent.state import AgentRunConfig

    monkeypatch.setattr(AgentRuntime, "_recover_interrupted_runs", lambda self: None)
    monkeypatch.setattr(AgentRuntime, "_record_persistent_event", lambda *a: None)
    monkeypatch.setattr(AgentRuntime, "_ensure_worker_locked", lambda self: None)
    path = tmp_path / "jobs.json"
    config = AgentRunConfig(category="Home & Kitchen")
    first = AgentRuntime(path).start_run(config, request_id="request-0001")
    runtime = AgentRuntime(path)
    second = runtime.start_run(config, request_id="request-0001")
    assert second.id == first.id
    assert list(runtime._queue) == [first.id]
    with pytest.raises(ValueError, match="different parameters"):
        runtime.start_run(AgentRunConfig(category="Other"), request_id="request-0001")


def test_persistence_failure_does_not_start_job(tmp_path, monkeypatch):
    from agent.runner import AgentRuntime
    from agent.state import AgentRunConfig

    monkeypatch.setattr(AgentRuntime, "_recover_interrupted_runs", lambda self: None)
    monkeypatch.setattr(AgentRuntime, "_record_persistent_event", lambda *a: None)
    started = []
    monkeypatch.setattr(AgentRuntime, "_ensure_worker_locked", lambda self: started.append(True))
    runtime = AgentRuntime(tmp_path / "jobs.json")
    monkeypatch.setattr(runtime, "_persist_jobs_locked", lambda **kw: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        runtime.start_run(AgentRunConfig(category="Home"), request_id="request-0001")
    assert not started
    assert not runtime._queue
    assert not runtime._jobs


def test_browser_callback_checks_node_deadline():
    context = StageContext(
        node_id=1, attempt_id=1, run_id=1, asin="B00Q7OAN50", attempt_no=1,
        generation=1, lease_token="test", worker_id="test",
        deadline=datetime.utcnow() - timedelta(seconds=1),
        cancel_check=lambda: False, heartbeat=lambda: None, input_snapshot={},
    )
    with pytest.raises(TimeoutError):
        context.check_interruption()


def test_rejected_supplier_is_exported_but_not_selected(tmp_path):
    import json

    from crawlers.amazon_bsr import ProductDTO
    from execution.handlers import dump_suppliers
    from matchers.alibaba_pailitao import SupplierDTO
    from reports.exporter import _report_suppliers, export_json

    rejected = SupplierDTO(
        alibaba_offer_id="123", match_verification_method="heuristic_rejected",
        raw_data={"source": "sellersprite_1688", "spec_match": {"conflicts": ["category"]}},
    )
    product = ProductDTO(asin="B00Q7OAN50", marketplace="US", title="Bottle")
    product.raw_data["rejected_suppliers"] = dump_suppliers([rejected])
    record = SimpleNamespace(product=product, suppliers=[], profit=None, score=None)
    path = export_json([record], tmp_path / "report.json")
    row = json.loads(path.read_text(encoding="utf-8"))[0]
    assert row["suppliers"][0]["selection_decision"] == "淘汰"
    assert len(_report_suppliers(record)) == 1
    assert record.suppliers == []


def test_single_product_timeout_keeps_retry_wait(monkeypatch):
    from config.settings import settings
    from crawlers.amazon_bsr import ProductDTO
    from db.models import ExecutionNode, RunLog
    from pipeline.orchestrator import run_pipeline
    from tests.test_recoverable_pipeline import _memory_session_scope

    Session, scope = _memory_session_scope()
    monkeypatch.setattr("pipeline.orchestrator.session_scope", scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *a: [
        ProductDTO(asin="B00Q7OAN50", marketplace="US", title="Bottle", price=25),
    ])
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("network")))
    run_id = run_pipeline(category="Home & Kitchen", limit=1, export=False)
    with Session() as session:
        assert session.get(RunLog, run_id).status == "retry_wait"
        node = session.query(ExecutionNode).filter_by(run_id=run_id, stage="match").one()
        assert node.status == "retry_wait"
        assert node.attempt_count == 1


def test_formal_match_executes_enabled_vision_and_preserves_rejection(monkeypatch):
    from config.settings import settings
    from crawlers.amazon_bsr import ProductDTO
    from matchers.alibaba_pailitao import SupplierDTO
    from pipeline.recoverable import _formal_match_suppliers

    product = ProductDTO(asin="B00Q7OAN50", marketplace="US", title="Bottle")
    supplier = SupplierDTO(alibaba_offer_id="123", raw_data={"source": "sellersprite_1688"})
    monkeypatch.setattr(settings, "enable_llm_verification", True)
    monkeypatch.setattr("agent.sellersprite_1688_sourcing.run_sellersprite_1688_sourcing", lambda *a, **kw: [supplier])
    monkeypatch.setattr("matchers._enrich_supplier_details", lambda values, *a, **kw: values)
    monkeypatch.setattr("matchers._title_fallback_keywords", lambda title: [])
    monkeypatch.setattr("matchers.verifier.Alibaba1688Verifier", lambda: SimpleNamespace(verify=lambda **kw: kw["suppliers"]))
    calls = []

    def verify_pair(product, supplier):
        calls.append(supplier.alibaba_offer_id)
        return SimpleNamespace(is_match=False, model_dump=lambda **kw: {
            "is_match": False, "provider": "test", "model": "test", "prompt_version": "v1",
        })

    monkeypatch.setattr("matchers.verifier.LLMVisualVerifier", lambda: SimpleNamespace(verify_pair=verify_pair))
    assert _formal_match_suppliers(product) == []
    assert calls == ["123"]
    assert product.raw_data["vision_verifications"] == 1
    rejected = product.raw_data["rejected_suppliers"][0]
    assert rejected["match_verification_method"] == "llm_rejected"
    assert rejected["raw_data"]["visual_match"]["prompt_version"] == "v1"


def test_formal_preflight_requires_sourcing_locators(monkeypatch):
    from agent import preflight

    monkeypatch.setattr(preflight, "_check_seller_sprite_browser", lambda: preflight._ok("seller_sprite_browser", "config ready", ""))
    monkeypatch.setattr("agent.sellersprite_service.SellerSpriteDependencies", lambda: SimpleNamespace(
        profile=SimpleNamespace(has_sourcing_1688_locators=lambda: False),
    ))
    result = preflight.check_seller_sprite_browser()
    assert result["level"] == "error"
    assert "locators are missing" in result["detail"]


def test_lost_mcp_response_replays_same_backend_job(tmp_path, monkeypatch):
    import asyncio

    from agent.runner import AgentRuntime
    from agent.state import AgentRunConfig
    from selector_mcp.service import SelectorService
    from selector_mcp.store import IdempotencyStore

    monkeypatch.setattr(AgentRuntime, "_recover_interrupted_runs", lambda self: None)
    monkeypatch.setattr(AgentRuntime, "_record_persistent_event", lambda *a: None)
    monkeypatch.setattr(AgentRuntime, "_ensure_worker_locked", lambda self: None)
    runtime = AgentRuntime(tmp_path / "jobs.json")

    class Client:
        lost = False

        async def preflight(self):
            return {"ready": True, "checks": []}

        async def start_job(self, body):
            job = runtime.start_run(AgentRunConfig(category=body["category"]), request_id=body["request_id"])
            if not self.lost:
                self.lost = True
                raise TimeoutError("response lost after backend accepted")
            return {"job": job.to_dict()}

    async def replay():
        service = SelectorService(Client(), IdempotencyStore(tmp_path / "requests.json"))
        with pytest.raises(TimeoutError):
            await service.start_sourcing("same-request", "category", category="Home", confirm=True)
        result = await service.start_sourcing("same-request", "category", category="Home", confirm=True)
        assert result["started"]

    asyncio.run(replay())
    assert len(runtime._jobs) == 1
    assert len(runtime._queue) == 1
