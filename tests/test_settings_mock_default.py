from config.settings import Settings


def test_mock_suppliers_disabled_by_default(monkeypatch):
    """Formal runs must not emit mock suppliers unless explicitly opted in.

    Plain `main.py run` does not override this flag (only smoke-run/AgentRuntime
    do), so the class default governs whether a blocked 1688 path falls back to
    mock. It must be False.
    """
    monkeypatch.delenv("ALIBABA_ALLOW_MOCK_SUPPLIERS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.alibaba_allow_mock_suppliers is False
