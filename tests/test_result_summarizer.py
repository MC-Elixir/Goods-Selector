from __future__ import annotations

from types import SimpleNamespace

from agent import result_summarizer
from config.settings import settings


def test_result_summarizer_uses_ppio_text_model(monkeypatch, tmp_path):
    export = tmp_path / "candidates.json"
    export.write_text(
        '[{"product":{"asin":"B0TEST1234","title":"Water bottle"},"score":{"total_score":62,"passed_hard_filter":false}}]',
        encoding="utf-8",
    )
    calls = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="结论：暂缓\n依据：评分不足"))]
            )

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    def fake_openai(api_key, base_url, timeout):
        calls["api_key"] = api_key
        calls["base_url"] = base_url
        calls["timeout"] = timeout
        return FakeClient()

    monkeypatch.setattr(settings, "model_api_provider", "ppio")
    monkeypatch.setattr(settings, "ppio_api_key", "ppio-key")
    monkeypatch.setattr(settings, "ppio_api_base", "https://api.ppio.com/openai")
    monkeypatch.setattr(settings, "ppio_text_model", "minimax/minimax-m3")
    monkeypatch.setattr(result_summarizer._openai, "OpenAI", fake_openai)

    summary = result_summarizer.summarize_run_result(
        run_log_id=12,
        config={"category": "Sports & Outdoors", "marketplace": "US"},
        exports={"json": str(export)},
        audit={"candidate_count": 1, "mock_count": 0},
    )

    assert summary["status"] == "success"
    assert summary["provider"] == "ppio"
    assert summary["model"] == "minimax/minimax-m3"
    assert summary["summary"].startswith("结论：暂缓")
    assert calls["api_key"] == "ppio-key"
    assert calls["base_url"] == "https://api.ppio.com/openai"
    assert calls["timeout"] == 30.0
    assert calls["model"] == "minimax/minimax-m3"
    assert "candidate_count" in calls["messages"][0]["content"]


def test_result_summarizer_skips_when_ppio_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "model_api_provider", "ppio")
    monkeypatch.setattr(settings, "ppio_api_key", "")

    summary = result_summarizer.summarize_run_result(
        run_log_id=12,
        config={"category": "Sports & Outdoors"},
        exports={},
        audit={"candidate_count": 0},
    )

    assert summary["status"] == "skipped"
    assert "OpenAI-compatible API key" in summary["error"]


def test_result_summarizer_uses_aliyun_token_plan(monkeypatch, tmp_path):
    export = tmp_path / "candidates.json"
    export.write_text("[]", encoding="utf-8")
    calls = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="结论：暂缓"))])

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    def fake_openai(**kwargs):
        calls["client_kwargs"] = kwargs
        return FakeClient()

    monkeypatch.setattr(settings, "model_api_provider", "aliyun_token_plan")
    monkeypatch.setattr(settings, "aliyun_token_plan_api_key", "sk-sp-test")
    monkeypatch.setattr(settings, "aliyun_token_plan_api_base", "https://token-plan.example/v1")
    monkeypatch.setattr(settings, "aliyun_token_plan_text_model", "qwen-plan")
    monkeypatch.setattr(result_summarizer._openai, "OpenAI", fake_openai)

    summary = result_summarizer.summarize_run_result(
        run_log_id=1, config={}, exports={"json": str(export)}, audit={}
    )

    assert summary["provider"] == "aliyun_token_plan"
    assert summary["model"] == "qwen-plan"
    assert calls["client_kwargs"]["base_url"] == "https://token-plan.example/v1"
