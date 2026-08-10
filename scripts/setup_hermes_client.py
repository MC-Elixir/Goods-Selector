#!/usr/bin/env python3
"""Prepare the local single-client Hermes profile without printing secrets."""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ENV = PROJECT_ROOT / ".env"
PROFILE_SOURCE = PROJECT_ROOT / "deployment" / "hermes" / "amazon-selector-profile"
PROFILE_NAME = "amazon-selector-client"
MIN_HERMES_VERSION = (0, 20, 0)
MAX_HERMES_VERSION = (0, 21, 0)


def _read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return result
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _update_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    remaining = dict(values)
    output: list[str] = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.append("# Hermes / Selector MCP（由 setup_hermes_client.py 管理）")
        output.extend(f"{key}={value}" for key, value in remaining.items())
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def prepare_project_env() -> dict[str, str]:
    current = _read_env(PROJECT_ENV)
    token = current.get("SELECTOR_MCP_TOKEN") or secrets.token_urlsafe(32)
    if len(token) < 24:
        raise SystemExit("现有 SELECTOR_MCP_TOKEN 少于 24 位，请删除后重新运行或换用强随机值。")
    values = {
        "SELECTOR_MCP_TOKEN": token,
        "SELECTOR_HERMES_MODEL": current.get("SELECTOR_HERMES_MODEL") or current.get("PPIO_TEXT_MODEL") or "minimax/minimax-m3",
        "SELECTOR_HERMES_MODEL_BASE_URL": current.get("SELECTOR_HERMES_MODEL_BASE_URL") or current.get("PPIO_API_BASE") or "https://api.ppio.com/openai",
        "SELECTOR_HERMES_MODEL_API_KEY": current.get("SELECTOR_HERMES_MODEL_API_KEY") or current.get("PPIO_API_KEY") or "",
    }
    _update_env(PROJECT_ENV, values)
    return values


def _hermes_version(hermes: str) -> tuple[int, int, int]:
    result = subprocess.run(
        [hermes, "version"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if not match:
        raise SystemExit("无法识别 Hermes 版本；请安装兼容的 0.20.x 版本后重试。")
    return tuple(int(part) for part in match.groups())


def ensure_compatible_hermes(hermes: str) -> None:
    version = _hermes_version(hermes)
    if not MIN_HERMES_VERSION <= version < MAX_HERMES_VERSION:
        raise SystemExit(
            "Hermes 版本不兼容：需要 >=0.20.0,<0.21.0，"
            f"当前为 {'.'.join(map(str, version))}。"
        )


def install_profile(values: dict[str, str]) -> Path:
    hermes = shutil.which("hermes")
    if not hermes:
        raise SystemExit(
            "未找到 hermes 命令。请先按 Hermes Agent 官方文档安装兼容的 0.20.x 版本，再重新运行。"
        )
    ensure_compatible_hermes(hermes)
    profile_dir = Path.home() / ".hermes" / "profiles" / PROFILE_NAME
    if profile_dir.exists():
        command = [
            hermes, "profile", "update", PROFILE_NAME, "--force-config", "--yes",
        ]
    else:
        command = [
            hermes, "profile", "install", str(PROFILE_SOURCE), "--name", PROFILE_NAME,
            "--alias", "--yes",
        ]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    profile_env = profile_dir / ".env"
    _update_env(profile_env, values)
    return profile_env


def start_services() -> None:
    subprocess.run(
        ["docker", "compose", "--profile", "assistant", "up", "-d", "--build", "amazon-selector", "selector-mcp"],
        cwd=PROJECT_ROOT,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="配置 Amazon Selector 的 Hermes 单客户入口")
    parser.add_argument("--install-profile", action="store_true", help="安装/更新 Hermes profile")
    parser.add_argument("--start", action="store_true", help="构建并启动 WebUI 与 MCP 服务")
    args = parser.parse_args()

    values = prepare_project_env()
    print("已准备项目配置；MCP 密钥已安全写入 .env（未显示）。")
    if not values["SELECTOR_HERMES_MODEL_API_KEY"]:
        print("注意：尚未配置 Hermes 文本模型密钥，请在 .env 填写 PPIO_API_KEY 或 SELECTOR_HERMES_MODEL_API_KEY。")
    if args.install_profile:
        profile_env = install_profile(values)
        print(f"Hermes profile 已安装：{PROFILE_NAME}（环境文件：{profile_env}）")
    if args.start:
        start_services()
        print("服务已启动：操作页 http://127.0.0.1:8765/operator，MCP http://127.0.0.1:8766/mcp")
    if not args.install_profile and not args.start:
        print("下一步：加 --install-profile --start 完成安装和启动。")


if __name__ == "__main__":
    main()
