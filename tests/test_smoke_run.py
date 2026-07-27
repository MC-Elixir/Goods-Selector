from click.testing import CliRunner

import main as main_module
from agent.smoke_run import SmokeRunConfig, run_smoke
from config.settings import settings
from main import cli


def test_run_smoke_returns_preflight_failure_without_pipeline(monkeypatch):
    called = []
    monkeypatch.setattr(
        "agent.smoke_run.run_preflight",
        lambda: {"ready": False, "checks": [{"level": "error", "label": "1688", "detail": "missing"}]},
    )
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: called.append("init"))
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 2, "total": 2})

    result = run_smoke(SmokeRunConfig(category="Home & Kitchen", limit=1))

    assert result["status"] == "preflight_failed"
    assert result["manual_queue"]["open"] == 2
    assert called == []


def test_run_smoke_success_restores_runtime_settings(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    original_mock = settings.alibaba_allow_mock_suppliers
    original_llm = settings.enable_llm_verification

    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 123)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.smoke_run.audit_export", lambda path: {
        "candidate_count": 1,
        "sourcing_quality": "blocked",
        "market_data_count": 1,
        "market_data_rate": 1.0,
        "market_data_ready": True,
        "market_data_rich_count": 1,
        "market_data_rich_rate": 1.0,
        "market_data_rich_ready": True,
        "supplier_evidence_count": 1,
        "supplier_evidence_rate": 1.0,
        "supplier_evidence_ready": True,
        "real_supplier_count": 1,
        "supplier_source_counts": {"alibaba_import": 1},
        "avg_spec_match_score": 0.88,
        "avg_match_quality_score": 0.91,
    })
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 1, "total": 1})

    result = run_smoke(SmokeRunConfig(
        category="Home & Kitchen",
        marketplace="US",
        limit=2,
        top_n=2,
        no_mock=True,
        llm_verification=True,
    ))

    assert result["status"] == "success"
    assert result["run_log_id"] == 123
    assert result["audit"]["manual_queue"] == {"open": 1, "total": 1}
    assert result["audit"]["market_data"] == {
        "count": 1,
        "rate": 1.0,
        "ready": True,
        "rich_count": 1,
        "rich_rate": 1.0,
        "rich_ready": True,
    }
    assert result["audit"]["supplier_evidence"] == {
        "count": 1,
        "rate": 1.0,
        "ready": True,
        "real_supplier_count": 1,
        "source_counts": {"alibaba_import": 1},
        "avg_spec_match_score": 0.88,
        "avg_match_quality_score": 0.91,
    }
    assert result["exports"]["json"] == str(export)
    assert settings.alibaba_allow_mock_suppliers == original_mock
    assert settings.enable_llm_verification == original_llm


def test_smoke_run_cli_prints_json(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.seller_sprite_market_data_guard", lambda: (True, ""))
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 456)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.smoke_run.audit_export", lambda path: {"candidate_count": 0})
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 0, "total": 0})

    result = CliRunner().invoke(cli, [
        "smoke-run",
        "--category", "Home & Kitchen",
        "--limit", "1",
        "--top-n", "1",
        "--skip-preflight",
    ])

    assert result.exit_code == 0
    assert '"status": "success"' in result.output
    assert '"run_log_id": 456' in result.output


def test_agent_web_cli_warns_that_docker_is_the_default_runtime(monkeypatch):
    called = []
    monkeypatch.setattr("agent.server.run_server", lambda **kwargs: called.append(kwargs))

    result = CliRunner().invoke(cli, ["agent-web"])

    assert result.exit_code == 0
    assert "Docker" in result.output
    assert "docker compose up -d --build amazon-selector" in result.output
    assert "http://127.0.0.1:8765" in result.output
    assert called == [{"host": "127.0.0.1", "port": 8765}]


def test_legacy_pipeline_command_remains_default(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "run_pipeline", lambda **kwargs: calls.append(kwargs) or 77)

    result = CliRunner().invoke(
        cli,
        ["run", "--category", "Sports & Outdoors", "--limit", "1"],
    )

    assert result.exit_code == 0
    assert calls == [{"category": "Sports & Outdoors", "limit": 1, "marketplace": "US"}]


def test_run_smoke_can_require_market_data(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.seller_sprite_market_data_guard", lambda: (True, ""))
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 789)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.smoke_run.audit_export", lambda path: {
        "candidate_count": 1,
        "market_data_count": 0,
        "market_data_rate": 0.0,
        "market_data_ready": False,
        "market_data_rich_count": 0,
        "market_data_rich_rate": 0.0,
        "market_data_rich_ready": False,
        "supplier_evidence_count": 1,
        "supplier_evidence_rate": 1.0,
        "supplier_evidence_ready": True,
        "real_supplier_count": 1,
        "supplier_source_counts": {"alibaba_pifatuan": 1},
        "avg_spec_match_score": 0.8,
        "avg_match_quality_score": 0.7,
    })
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 0, "total": 0})

    result = run_smoke(SmokeRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_market_data=True,
    ))

    assert result["status"] == "market_data_missing"
    assert result["run_log_id"] == 789
    assert result["audit"]["market_data"] == {
        "count": 0,
        "rate": 0.0,
        "ready": False,
        "rich_count": 0,
        "rich_rate": 0.0,
        "rich_ready": False,
    }
    assert result["audit"]["supplier_evidence"]["ready"] is True
    assert result["audit"]["supplier_evidence"]["source_counts"] == {"alibaba_pifatuan": 1}


def test_run_smoke_can_require_supplier_evidence(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 791)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.smoke_run.audit_export", lambda path: {
        "candidate_count": 1,
        "supplier_evidence_count": 0,
        "supplier_evidence_rate": 0.0,
        "supplier_evidence_ready": False,
        "real_supplier_count": 0,
        "supplier_source_counts": {"none": 1},
    })
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 0, "total": 0})

    result = run_smoke(SmokeRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_supplier_evidence=True,
    ))

    assert result["status"] == "supplier_evidence_missing"
    assert result["run_log_id"] == 791
    assert result["audit"]["supplier_evidence"] == {
        "count": 0,
        "rate": 0.0,
        "ready": False,
        "real_supplier_count": 0,
        "source_counts": {"none": 1},
        "avg_spec_match_score": None,
        "avg_match_quality_score": None,
    }


def test_run_smoke_fails_before_pipeline_when_required_market_data_unavailable(monkeypatch):
    called = []
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr(
        "agent.smoke_run.seller_sprite_market_data_guard",
        lambda: (False, "SellerSprite ASIN check failed: 未授权"),
    )
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: called.append("init_db"))
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: called.append("pipeline"))
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 0, "total": 0})

    result = run_smoke(SmokeRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_market_data=True,
    ))

    assert result["status"] == "market_data_unavailable"
    assert result["error"] == "SellerSprite ASIN check failed: 未授权"
    assert called == []


def test_smoke_run_cli_fails_when_required_market_data_missing(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.seller_sprite_market_data_guard", lambda: (True, ""))
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 790)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.smoke_run.audit_export", lambda path: {
        "candidate_count": 1,
        "market_data_count": 0,
        "market_data_rate": 0.0,
        "market_data_ready": False,
        "market_data_rich_count": 0,
        "market_data_rich_rate": 0.0,
        "market_data_rich_ready": False,
    })
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 0, "total": 0})

    result = CliRunner().invoke(cli, [
        "smoke-run",
        "--category", "Home & Kitchen",
        "--limit", "1",
        "--top-n", "1",
        "--skip-preflight",
        "--require-market-data",
    ])

    assert result.exit_code == 2
    assert '"status": "market_data_missing"' in result.output


def test_smoke_run_cli_fails_when_required_supplier_evidence_missing(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 792)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.smoke_run.audit_export", lambda path: {
        "candidate_count": 1,
        "supplier_evidence_count": 0,
        "supplier_evidence_rate": 0.0,
        "supplier_evidence_ready": False,
    })
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 0, "total": 0})

    result = CliRunner().invoke(cli, [
        "smoke-run",
        "--category", "Home & Kitchen",
        "--limit", "1",
        "--top-n", "1",
        "--skip-preflight",
        "--require-supplier-evidence",
    ])

    assert result.exit_code == 2
    assert '"status": "supplier_evidence_missing"' in result.output


def test_seller_sprite_check_cli_reports_missing_key(monkeypatch):
    monkeypatch.setattr("agent.config_status.check_seller_sprite_capabilities", lambda **kwargs: {
        "configured": False,
        "base_url": "https://api.sellersprite.com",
        "authorized_api_count": 0,
        "authorized_data_api_count": 0,
        "api_checks": [{"name": "visits", "ok": False, "error": "API key not configured"}],
    })

    result = CliRunner().invoke(cli, ["seller-sprite-check"])

    assert result.exit_code == 2
    assert '"configured": false' in result.output
    assert "API key not configured" in result.output


def test_seller_sprite_check_cli_allows_visits_without_permission_when_data_api_works(monkeypatch):
    monkeypatch.setattr("agent.config_status.check_seller_sprite_capabilities", lambda **kwargs: {
        "configured": True,
        "base_url": "https://api.sellersprite.com",
        "authorized_api_count": 1,
        "authorized_data_api_count": 1,
        "has_market_evidence": True,
        "api_checks": [
            {"name": "visits", "ok": False, "error": "没有该接口访问次数查询权限"},
            {"name": "asin_detail", "ok": True, "error": None},
        ],
    })

    result = CliRunner().invoke(cli, ["seller-sprite-check"])

    assert result.exit_code == 0
    assert '"configured": true' in result.output
    assert "没有该接口访问次数查询权限" in result.output
    assert '"authorized_api_count": 1' in result.output
    assert "secret-key" not in result.output


def test_seller_sprite_asin_check_cli_reports_sanitized_detail(monkeypatch):
    class FakeDetail:
        asin = "B0TEST1234"
        marketplace = "US"
        title = "Test Product"
        brand = "Acme"
        price = 19.99
        list_price = None
        rating = 4.5
        review_count = 321
        bsr = 1200
        bsr_category_name = "Home & Kitchen"
        category_path = "Home & Kitchen:Bedding"

        def __bool__(self):
            return True

    class FakeClient:
        api_key = "secret-key"
        base_url = "https://api.sellersprite.com"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def asin_detail(self, marketplace, asin):
            assert marketplace == "US"
            assert asin == "B0TEST1234"
            return FakeDetail()

    monkeypatch.setattr("analyzers.maijiajingling.MaijiajinglingClient", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_seller_sprite_diagnostic", lambda result: {
        "has_market_evidence": True,
        "asin": result["asin"],
        "key_length": result["key_length"],
    })

    result = CliRunner().invoke(cli, [
        "seller-sprite-asin-check",
        "--asin", "B0TEST1234",
        "--marketplace", "US",
    ])

    assert result.exit_code == 0
    assert '"asin": "B0TEST1234"' in result.output
    assert '"review_count": 321' in result.output
    assert '"has_market_evidence": true' in result.output
    assert "secret-key" not in result.output


def test_seller_sprite_configure_cli_does_not_print_secret(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("MJJL_API_KEY=\n", encoding="utf-8")

    monkeypatch.setattr("agent.config_status.PROJECT_ROOT", tmp_path)

    result = CliRunner().invoke(cli, [
        "seller-sprite-configure",
        "--key", "super-secret-key",
    ])

    assert result.exit_code == 0
    assert "super-secret-key" not in result.output
    assert '"key_length": 16' in result.output
    assert env_path.read_text(encoding="utf-8") == "MJJL_API_KEY=super-secret-key\n"


def test_run_smoke_returns_failed_summary_on_pipeline_error(monkeypatch):
    monkeypatch.setattr("agent.smoke_run.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.smoke_run.init_db", lambda: None)
    monkeypatch.setattr("agent.smoke_run.latest_export_after", lambda started: {})
    monkeypatch.setattr("agent.smoke_run.manual_queue_summary", lambda: {"open": 3, "total": 3})

    def fail_pipeline(**kwargs):
        raise RuntimeError("amazon page timed out")

    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", fail_pipeline)

    result = run_smoke(SmokeRunConfig(category="Home & Kitchen", limit=1))

    assert result["status"] == "failed"
    assert result["error"] == "amazon page timed out"
    assert result["audit"]["manual_queue"]["open"] == 3
