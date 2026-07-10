import pytest

from agent.server import _config_from_body


def test_keyword_run_config_defaults_to_fixed_amazon_us():
    config = _config_from_body({
        "source_mode": "keyword",
        "keyword": "水杯",
        "limit": 10,
    })

    assert config.source_mode == "keyword"
    assert config.keyword == "水杯"
    assert config.category == ""
    assert config.marketplace == "US"
    assert config.no_mock is True


def test_run_config_rejects_non_us_marketplace():
    with pytest.raises(ValueError, match="Amazon US"):
        _config_from_body({
            "category": "Home & Kitchen",
            "marketplace": "UK",
        })


def test_formal_api_ignores_mock_opt_in_without_dev_flag(monkeypatch):
    monkeypatch.delenv("DEV_ALLOW_MOCK_SUPPLIERS", raising=False)

    config = _config_from_body({
        "category": "Home & Kitchen",
        "marketplace": "US",
        "no_mock": False,
    })

    assert config.no_mock is True
