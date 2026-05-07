"""评分引擎单测。"""
import pytest

from analyzers import scorer


def test_weights_sum_to_one():
    config = scorer.load_weights_config()
    weights = config["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_score_profit_boundary():
    """利润率 5% → 接近 0 分；50% → 接近 1 分。"""
    pytest.skip("等 score_profit 实现后启用")
