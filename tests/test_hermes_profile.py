from pathlib import Path

import yaml

from scripts import setup_hermes_client as setup

PROFILE = Path("deployment/hermes/amazon-selector-profile")


def test_hermes_profile_is_version_pinned_and_requires_secrets():
    distribution = yaml.safe_load((PROFILE / "distribution.yaml").read_text(encoding="utf-8"))
    assert distribution["hermes_requires"] == ">=0.20.0"
    assert setup.MIN_HERMES_VERSION == (0, 20, 0)
    assert setup.MAX_HERMES_VERSION == (0, 21, 0)
    names = {item["name"] for item in distribution["env_requires"]}
    assert "SELECTOR_MCP_TOKEN" in names
    assert "SELECTOR_HERMES_MODEL_API_KEY" in names


def test_hermes_profile_uses_authenticated_mcp_and_disables_general_tools():
    text = (PROFILE / "config.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    server = config["mcp_servers"]["amazon_selector"]
    assert server["url"] == "http://127.0.0.1:8766/mcp"
    assert server["headers"]["Authorization"] == "Bearer ${SELECTOR_MCP_TOKEN}"
    assert server["trust"] == "untrusted"
    assert server["tools"]["resources"] is False
    assert server["tools"]["prompts"] is False
    assert len(server["tools"]["include"]) == 19
    disabled = set(config["agent"]["disabled_toolsets"])
    assert {"terminal", "file", "browser", "web", "code_execution", "delegation", "messaging"} <= disabled
    assert config["toolsets"] == ["clarify", "mcp-amazon_selector"]


def test_profile_prompt_requires_confirmation_and_no_mock():
    soul = (PROFILE / "SOUL.md").read_text(encoding="utf-8")
    assert "confirm=true" in soul
    assert "No-Mock" in soul
    assert "mcp__amazon_selector__selector_check_environment" in soul
