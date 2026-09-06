import os
import subprocess
from pathlib import Path

import pytest


def test_dockerfile_installs_python_dependencies_before_playwright_module_calls():
    dockerfile = _read_dockerfile_or_skip()

    pip_install = dockerfile.index("pip install --no-cache-dir -r requirements.txt")
    install_deps = dockerfile.index("python -m playwright install-deps chromium")
    install_browser = dockerfile.index("python -m playwright install chromium")

    assert pip_install < install_deps
    assert pip_install < install_browser


def test_dockerfile_configures_apt_retries_before_playwright_install_deps():
    dockerfile = _read_dockerfile_or_skip()

    apt_retries = dockerfile.index("Acquire::Retries")
    install_deps = dockerfile.index("python -m playwright install-deps chromium")

    assert apt_retries < install_deps


def test_dockerfile_precreates_persistent_runtime_directories():
    dockerfile = _read_dockerfile_or_skip()

    assert "/app/data/cache" in dockerfile
    assert "/app/data/exports" in dockerfile
    assert "/app/data/images" in dockerfile
    assert "/app/data/logs" in dockerfile


def test_dockerfile_installs_browser_use_in_isolated_venv():
    dockerfile = _read_dockerfile_or_skip()

    assert "requirements-browser-agent.txt" in dockerfile
    assert "python -m venv /opt/browser-agent" in dockerfile
    assert "/opt/browser-agent/bin/pip install --no-cache-dir -r requirements-browser-agent.txt" in dockerfile
    assert "BROWSER_AGENT_COMMAND=/opt/browser-agent/bin/browser-use" in dockerfile


def test_browser_agent_requirements_are_not_in_main_requirements():
    main_requirements = Path("requirements.txt").read_text(encoding="utf-8")
    browser_requirements = Path("requirements-browser-agent.txt").read_text(encoding="utf-8")

    assert "browser-use" not in main_requirements
    assert "browser-use==" in browser_requirements


def test_compose_uses_single_persistent_data_volume_and_local_only_port():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "./data:/app/data" in compose
    assert "127.0.0.1:8765:8765" in compose
    assert 'ALIBABA_ALLOW_MOCK_SUPPLIERS: "false"' in compose
    assert 'profiles: ["assistant"]' in compose
    assert "127.0.0.1:8766:8766" in compose
    assert "SELECTOR_API_BASE_URL: http://amazon-selector:8765" in compose
    assert "BU_CDP_HTTP: http://host.docker.internal:9222" in compose
    assert "${BU_CDP_HTTP" not in compose
    assert "7897" not in compose
    assert "HTTP_PROXY" not in compose


def test_windows_startup_keeps_chrome_private_and_verifies_container_cdp():
    script = Path("start.ps1").read_text(encoding="utf-8")

    assert '--remote-debugging-address=127.0.0.1' in script
    assert '"--remote-debugging-address=0.0.0.0",' not in script
    assert 'http://127.0.0.1:9222/json/version' in script
    assert 'http://host.docker.internal:9222' in script
    assert 'from agent.browser_agent import _resolve_cdp_ws' in script
    assert 'from agent.preflight import _assert_cdp_websocket_reachable' in script
    assert 'docker compose stop amazon-selector' in script
    assert 'seller_sprite_browser' in script
    assert 'do not start a formal run until this check is OK' in script


def test_docs_present_docker_as_the_default_webui_runtime():
    readme = Path("README.md").read_text(encoding="utf-8")
    deployment = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    claude = Path("CLAUDE.md").read_text(encoding="utf-8")

    assert "docker compose up -d --build amazon-selector" in readme
    assert "正式使用默认走 Docker" in readme
    assert "python main.py agent-web" in readme
    assert "仅用于本机调试" in readme
    assert "docker compose up -d --build amazon-selector" in deployment
    assert "docker compose up -d --build amazon-selector" in claude


def test_env_example_documents_deployment_paths_and_formal_mock_policy():
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "DATABASE_URL=sqlite:///data/amazon_selector.db" in env_example
    assert "LOG_DIR=data/logs" in env_example
    assert "AMAZON_MARKETPLACE=US" in env_example
    assert "ALIBABA_ALLOW_MOCK_SUPPLIERS=false" in env_example


def test_entrypoint_creates_runtime_data_directories(tmp_path):
    log = tmp_path / "calls.log"
    data_dir = tmp_path / "runtime-data"
    _write_executable(
        tmp_path / "python",
        '#!/bin/sh\nprintf "python %s\\n" "$*" >> "$CALL_LOG"\n',
    )

    env = _entrypoint_env(tmp_path, log)
    env["AMAZON_SELECTOR_DATA_DIR"] = str(data_dir)
    subprocess.run(
        ["sh", "docker-entrypoint.sh", "agent-web"],
        check=True,
        env=env,
    )

    assert (data_dir / "cache").is_dir()
    assert (data_dir / "exports").is_dir()
    assert (data_dir / "images").is_dir()
    assert (data_dir / "logs").is_dir()
    assert log.read_text(encoding="utf-8").splitlines() == [
        "python main.py init-db",
        "python main.py agent-web",
    ]


def test_entrypoint_routes_main_commands_through_cli(tmp_path):
    log = tmp_path / "calls.log"
    _write_executable(
        tmp_path / "python",
        '#!/bin/sh\nprintf "python %s\\n" "$*" >> "$CALL_LOG"\n',
    )

    env = _entrypoint_env(tmp_path, log)
    subprocess.run(
        ["sh", "docker-entrypoint.sh", "run", "--category", "Home & Kitchen"],
        check=True,
        env=env,
    )

    assert log.read_text(encoding="utf-8").splitlines() == [
        "python main.py init-db",
        "python main.py run --category Home & Kitchen",
    ]


def test_entrypoint_routes_selector_mcp_through_cli(tmp_path):
    log = tmp_path / "calls.log"
    _write_executable(
        tmp_path / "python",
        '#!/bin/sh\nprintf "python %s\\n" "$*" >> "$CALL_LOG"\n',
    )
    env = _entrypoint_env(tmp_path, log)
    subprocess.run(
        ["sh", "docker-entrypoint.sh", "selector-mcp", "--port", "8766"],
        check=True,
        env=env,
    )
    assert log.read_text(encoding="utf-8").splitlines() == [
        "python main.py init-db",
        "python main.py selector-mcp --port 8766",
    ]


def test_entrypoint_allows_direct_tools_like_pytest(tmp_path):
    log = tmp_path / "calls.log"
    _write_executable(
        tmp_path / "python",
        '#!/bin/sh\nprintf "python %s\\n" "$*" >> "$CALL_LOG"\n',
    )
    _write_executable(
        tmp_path / "pytest",
        '#!/bin/sh\nprintf "pytest %s\\n" "$*" >> "$CALL_LOG"\n',
    )

    env = _entrypoint_env(tmp_path, log)
    subprocess.run(
        ["sh", "docker-entrypoint.sh", "pytest", "tests/", "-q"],
        check=True,
        env=env,
    )

    assert log.read_text(encoding="utf-8").splitlines() == [
        "python main.py init-db",
        "pytest tests/ -q",
    ]


def _entrypoint_env(bin_dir: Path, log: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CALL_LOG"] = str(log)
    env.setdefault("AMAZON_SELECTOR_DATA_DIR", str(bin_dir / "runtime-data"))
    return env


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _read_dockerfile_or_skip() -> str:
    path = Path("Dockerfile")
    if not path.exists():
        pytest.skip("Dockerfile is not copied into the runtime image")
    return path.read_text(encoding="utf-8")
