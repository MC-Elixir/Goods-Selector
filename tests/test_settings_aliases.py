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
