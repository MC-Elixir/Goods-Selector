from pathlib import Path
import stat
from types import SimpleNamespace

from scripts import setup_hermes_client as setup


def test_prepare_project_env_generates_token_and_derives_model(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PPIO_API_KEY=test-model-key\n"
        "PPIO_API_BASE=https://example.test/openai\n"
        "PPIO_TEXT_MODEL=test/model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "PROJECT_ENV", env_path)

    values = setup.prepare_project_env()
    written = setup._read_env(env_path)

    assert len(values["SELECTOR_MCP_TOKEN"]) >= 24
    assert written["SELECTOR_MCP_TOKEN"] == values["SELECTOR_MCP_TOKEN"]
    assert written["SELECTOR_HERMES_MODEL"] == "test/model"
    assert written["SELECTOR_HERMES_MODEL_BASE_URL"] == "https://example.test/openai"
    assert written["SELECTOR_HERMES_MODEL_API_KEY"] == "test-model-key"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_install_profile_uses_local_distribution_and_writes_profile_env(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(setup.shutil, "which", lambda command: "/usr/bin/hermes")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args == ["/usr/bin/hermes", "version"]:
            return SimpleNamespace(stdout="Hermes Agent v0.20.0")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    values = {
        "SELECTOR_MCP_TOKEN": "x" * 32,
        "SELECTOR_HERMES_MODEL": "test/model",
        "SELECTOR_HERMES_MODEL_BASE_URL": "https://example.test/openai",
        "SELECTOR_HERMES_MODEL_API_KEY": "key",
    }

    profile_env = setup.install_profile(values)

    assert calls[1][0] == [
        "/usr/bin/hermes", "profile", "install", str(setup.PROFILE_SOURCE),
        "--name", "amazon-selector-client", "--alias", "--yes",
    ]
    assert profile_env == tmp_path / ".hermes/profiles/amazon-selector-client/.env"
    assert setup._read_env(profile_env) == values
    assert stat.S_IMODE(profile_env.stat().st_mode) == 0o600


def test_install_profile_updates_existing_distribution_with_security_config(monkeypatch, tmp_path):
    profile_dir = tmp_path / ".hermes/profiles/amazon-selector-client"
    profile_dir.mkdir(parents=True)
    calls = []
    monkeypatch.setattr(setup.shutil, "which", lambda command: "/usr/bin/hermes")

    def fake_run(args, **kwargs):
        calls.append(args)
        if args == ["/usr/bin/hermes", "version"]:
            return SimpleNamespace(stdout="Hermes Agent v0.20.0")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    values = {
        "SELECTOR_MCP_TOKEN": "x" * 32,
        "SELECTOR_HERMES_MODEL": "test/model",
        "SELECTOR_HERMES_MODEL_BASE_URL": "https://example.test/openai",
        "SELECTOR_HERMES_MODEL_API_KEY": "key",
    }

    setup.install_profile(values)

    assert calls == [
        ["/usr/bin/hermes", "version"],
        [
            "/usr/bin/hermes", "profile", "update", "amazon-selector-client",
            "--force-config", "--yes",
        ],
    ]


def test_ensure_compatible_hermes_rejects_non_020_versions(monkeypatch):
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Hermes Agent v0.21.0"),
    )

    try:
        setup.ensure_compatible_hermes("/usr/bin/hermes")
    except SystemExit as exc:
        assert ">=0.20.0,<0.21.0" in str(exc)
    else:
        raise AssertionError("0.21.0 should be rejected")


def test_wait_for_mcp_ready_accepts_auth_required(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=3):
        calls["n"] += 1
        raise setup.urllib.error.HTTPError(
            "http://127.0.0.1:8766/mcp", 401, "Unauthorized", hdrs={}, fp=None
        )

    monkeypatch.setattr(setup.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(setup.time, "sleep", lambda *_: None)

    setup.wait_for_mcp_ready(timeout_seconds=5)
    assert calls["n"] == 1
