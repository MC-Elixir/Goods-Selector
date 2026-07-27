"""Small helpers for updating local .env files without printing secrets."""
from __future__ import annotations

from pathlib import Path


def set_env_values(path: Path, updates: dict[str, str]) -> list[str]:
    """Set key/value pairs in a .env file, preserving unrelated lines."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    changed: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={_quote_env(remaining.pop(key))}")
            changed.append(key)
        else:
            out.append(line)

    for key, value in remaining.items():
        out.append(f"{key}={_quote_env(value)}")
        changed.append(key)

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def _quote_env(value: str) -> str:
    if value == "":
        return ""
    if any(ch.isspace() or ch in value for ch in ['"', "'", "#", "="]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
