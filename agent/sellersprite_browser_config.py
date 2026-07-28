"""Persisted, non-secret local configuration for the SellerSprite browser flow."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_CONFIG_NAME = "sellersprite_browser_config.json"
_CONTAINER_DATA_PREFIX = "/app/data/"


@dataclass(frozen=True)
class SellerSpriteBrowserConfig:
    enabled: bool
    locator_profile_path: str
    download_dir: str
    host_download_dir: str


def config_path(project_root: Path) -> Path:
    return project_root / "data" / _CONFIG_NAME


def project_local_path(project_root: Path, container_path: str) -> Path:
    """Translate a persisted /app/data path for the current project root."""
    normalized = _require_container_data_path(container_path, "path")
    return project_root / "data" / normalized.removeprefix(_CONTAINER_DATA_PREFIX)


def load_sellersprite_browser_config(project_root: Path, settings: Any) -> SellerSpriteBrowserConfig:
    """Resolve environment overrides followed by durable volume-backed values."""
    payload = _read_config(config_path(project_root))
    enabled = _env_bool("SELLERSPRITE_BROWSER_ENABLED", payload.get("enabled", settings.sellersprite_browser_enabled))
    locator_profile_path = _env_text(
        "SELLERSPRITE_BROWSER_LOCATOR_PROFILE_PATH",
        payload.get("locator_profile_path", settings.sellersprite_browser_locator_profile_path),
    )
    download_dir = _env_text(
        "SELLERSPRITE_BROWSER_DOWNLOAD_DIR",
        payload.get("download_dir", settings.sellersprite_browser_download_dir),
    )
    # ``host_download_dir`` is deliberately persisted only as the sentinel
    # ``configured`` because the actual host path may be machine-specific.
    # BaseSettings still loads the real value from the project .env, so it
    # must take precedence over that sentinel for host-side CLI runs.
    settings_host_download_dir = str(
        settings.sellersprite_browser_host_download_dir or ""
    ).strip()
    host_download_dir = _env_text(
        "SELLERSPRITE_BROWSER_HOST_DOWNLOAD_DIR",
        settings_host_download_dir or payload.get("host_download_dir", ""),
    )
    return SellerSpriteBrowserConfig(
        enabled=enabled,
        locator_profile_path=locator_profile_path,
        download_dir=download_dir,
        host_download_dir=host_download_dir,
    )


def configure_sellersprite_browser(
    project_root: Path,
    *,
    locator_profile_path: str,
    download_dir: str,
    host_download_dir: str,
    enabled: bool,
) -> SellerSpriteBrowserConfig:
    """Validate and write project-local configuration without retaining host paths."""
    locator = _require_container_data_path(locator_profile_path, "locator_profile_path")
    target = _require_container_data_path(download_dir, "download_dir")
    local_profile = project_local_path(project_root, locator)
    if local_profile.exists() and not local_profile.is_file():
        raise ValueError("locator_profile_path must reference a file under /app/data/")
    if not host_download_dir or not str(host_download_dir).strip():
        raise ValueError("host_download_dir is required")
    payload = {
        "download_dir": target,
        "enabled": bool(enabled),
        "host_download_dir": "configured",
        "locator_profile_path": locator,
    }
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SellerSpriteBrowserConfig(**payload)


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _env_text(name: str, fallback: object) -> str:
    value = os.getenv(name)
    if value is None:
        value = fallback
    return str(value or "").strip()


def _env_bool(name: str, fallback: object) -> bool:
    value = os.getenv(name)
    if value is None:
        return bool(fallback)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_container_data_path(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    relative = normalized.removeprefix(_CONTAINER_DATA_PREFIX)
    if (
        not normalized.startswith(_CONTAINER_DATA_PREFIX)
        or not relative
        or any(part in {"", ".", ".."} for part in Path(relative).parts)
    ):
        raise ValueError(f"{field_name} must be below /app/data/")
    return normalized
