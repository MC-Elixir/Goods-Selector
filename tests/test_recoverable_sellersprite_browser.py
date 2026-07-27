from __future__ import annotations

from types import SimpleNamespace

from agent.sellersprite_models import SellerSpriteContext, SellerSpriteResult
from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from db.models import MarketAnalysis, RunLog
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.orchestrator import run_pipeline
from tests.test_recoverable_pipeline import _memory_session_scope, _profit, _score


class _ConfiguredButUnusedApiClient:
    _configured = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def analyze_market(self, *_args, **_kwargs):
        raise AssertionError("browser-enabled flow must not call SellerSprite API")


class _BrowserDependencies:
    browser_enabled = True
    profile = object()
    session_factory = object()

    def __init__(self, *, is_cancelled=None):
        self.is_cancelled = is_cancelled or (lambda: False)


def test_recoverable_market_falls_back_to_sellersprite_browser(monkeypatch):
    Session, session_scope = _memory_session_scope()
    product = ProductDTO(
        asin="B00Q7OAN50",
        marketplace="US",
        title="Insulated Bottle",
        price=25.0,
    )
    browser_calls = []
    scored_markets = []
    matched_market_keywords = []

    def browser_export(asin, *, sourcing_run_id, dependencies):
        browser_calls.append((asin, sourcing_run_id, dependencies))
        return SellerSpriteResult(
            status="SUCCESS",
            context=SellerSpriteContext.create(asin, sourcing_run_id),
            data={
                "manifest_id": "00000000-0000-0000-0000-000000000001",
                "file_sha256": "a" * 64,
                "row_count": 1109,
                "keyword_rows": [{
                    "keyword": "insulated water bottle",
                    "search_volume": 4200,
                    "purchase_volume": 210,
                    "purchase_rate": 0.05,
                    "competing_products": 1800,
                }],
            },
        )

    def score(**kwargs):
        scored_markets.append(kwargs["market_analysis"])
        return _score(**kwargs)

    monkeypatch.setattr("pipeline.orchestrator.session_scope", session_scope)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    def match_with_market_keywords(*_args, **kwargs):
        matched_market_keywords.extend(kwargs.get("market_keywords") or [])
        return [SupplierDTO(
            alibaba_offer_id="1001",
            supplier_name="Factory",
            base_price_cny=20.0,
            moq=20,
            raw_data={"source": "unit-test"},
        )]

    monkeypatch.setattr("matchers.match_suppliers", match_with_market_keywords)
    monkeypatch.setattr("pipeline.orchestrator.predict_profit", _profit)
    monkeypatch.setattr("pipeline.orchestrator.score_product", score)
    monkeypatch.setattr(
        "pipeline.orchestrator.rank_candidates",
        lambda records, top_n=None: [record for record in records if record.score is not None],
    )
    monkeypatch.setattr(
        "analyzers.maijiajingling.MaijiajinglingClient", _ConfiguredButUnusedApiClient
    )
    monkeypatch.setattr(
        "agent.sellersprite_service.SellerSpriteDependencies", _BrowserDependencies
    )
    monkeypatch.setattr(
        "agent.sellersprite_service.run_reverse_keyword_export", browser_export
    )
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 1)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)

    run_id = run_pipeline("Home & Kitchen", limit=1, export=False)

    assert len(browser_calls) == 1
    assert browser_calls[0][0] == "B00Q7OAN50"
    assert matched_market_keywords == ["insulated water bottle"]
    assert scored_markets[0].main_keyword == "insulated water bottle"
    assert scored_markets[0].est_monthly_sales is None
    with Session() as session:
        assert session.get(RunLog, run_id).status == "success"
        market = session.query(MarketAnalysis).one()
        assert market.search_volume_monthly == 4200
        assert market.competing_listings == 1800
        assert market.raw_data["source_type"] == "browser_extension_export"
