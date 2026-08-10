"""Persistent request-id store used to make sourcing starts idempotent."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class IdempotencyConflict(ValueError):
    pass


class IdempotencyStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def lookup(self, request_id: str, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._read()
            row = rows.get(request_id)
            if not row:
                return None
            if row.get("fingerprint") != fingerprint:
                raise IdempotencyConflict(
                    "request_id 已被另一组参数使用；请换一个新的 request_id。"
                )
            result = row.get("result")
            return dict(result) if isinstance(result, dict) else None

    def record(self, request_id: str, fingerprint: str, result: dict[str, Any]) -> None:
        with self._lock:
            rows = self._read()
            existing = rows.get(request_id)
            if existing and existing.get("fingerprint") != fingerprint:
                raise IdempotencyConflict(
                    "request_id 已被另一组参数使用；请换一个新的 request_id。"
                )
            rows[request_id] = {"fingerprint": fingerprint, "result": result}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self.path)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(
                "幂等记录无法读取；为避免重复启动任务，服务已安全停止本次写操作。"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError(
                "幂等记录格式错误；为避免重复启动任务，服务已安全停止本次写操作。"
            )
        return value
