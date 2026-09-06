import importlib

from config.settings import Settings

settings_module = importlib.import_module("config.settings")


def test_sellersprite_env_aliases(monkeypatch):
    monkeypatch.delenv("MJJL_API_KEY", raising=False)
    monkeypatch.setenv("SELLERSPRITE_API_KEY", "alias-key")
    monkeypatch.setenv("SELLERSPRITE_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("SELLERSPRITE_MAX_PRODUCTS_PER_RUN", "7")

    settings = Settings(_env_file=None)

    assert settings.mjjl_api_key == "alias-key"
    assert settings.mjjl_api_base == "https://example.test/v1"
    assert settings.mjjl_max_products_per_run == 7


def test_log_dir_defaults_to_data_logs(monkeypatch, tmp_path):
    monkeypatch.delenv("LOG_DIR", raising=False)
    monkeypatch.setattr(settings_module, "DATA_DIR", tmp_path)

    settings = Settings(_env_file=None)

    assert settings.log_dir == tmp_path / "logs"


def test_log_dir_can_be_overridden_by_env(monkeypatch, tmp_path):
    override = tmp_path / "deployment-logs"
    monkeypatch.setenv("LOG_DIR", str(override))

    settings = Settings(_env_file=None)

    assert settings.log_dir == override


def test_aliyun_token_plan_has_priority_and_resolves_openai_compatible_config(monkeypatch):
    monkeypatch.setenv("ALIYUN_TOKEN_PLAN_API_KEY", "sk-sp-token-plan")
    monkeypatch.setenv("ALIYUN_TOKEN_PLAN_API_BASE", "https://token-plan.example/compatible-mode/v1")
    monkeypatch.setenv("ALIYUN_TOKEN_PLAN_VISION_MODEL", "qwen-vl-plan")
    monkeypatch.setenv("ALIYUN_TOKEN_PLAN_TEXT_MODEL", "qwen-text-plan")
    monkeypatch.setenv("ALIYUN_API_KEY", "aliyun-payg")
    monkeypatch.setenv("PPIO_API_KEY", "ppio-fallback")

    settings = Settings(_env_file=None)

    assert settings.vision_provider == "aliyun_token_plan"
    assert settings.openai_compatible_api_key == "sk-sp-token-plan"
    assert settings.openai_compatible_api_base == "https://token-plan.example/compatible-mode/v1"
    assert settings.openai_compatible_vision_model == "qwen-vl-plan"
    assert settings.openai_compatible_text_model == "qwen-text-plan"


def test_dashscope_api_key_alias_selects_aliyun(monkeypatch):
    monkeypatch.delenv("ALIYUN_API_KEY", raising=False)
    monkeypatch.delenv("ALIYUN_TOKEN_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("PPIO_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    settings = Settings(_env_file=None)

    assert settings.vision_provider == "aliyun"
    assert settings.openai_compatible_api_key == "dashscope-key"
    assert settings.openai_compatible_api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
