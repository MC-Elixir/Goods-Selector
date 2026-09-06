"""Bounded orchestration for one SellerSprite reverse-keyword export."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable
from uuid import UUID

from agent.run_events import record_run_event
from agent.sellersprite_browser_config import load_sellersprite_browser_config, project_local_path
from agent.sellersprite_models import SellerSpriteContext, SellerSpriteLocatorProfile, SellerSpriteResult
from agent.sellersprite_policy import normalize_sellersprite_error_code
from agent.tools.sellersprite_browser import PlaywrightSellerSpriteSession, SellerSpriteWorkflowError
from agent.tools.sellersprite_importer import (
    ImportedSellerSpriteExport,
    SellerSpriteImportError,
    import_sellersprite_export,
)
from config.settings import PROJECT_ROOT, settings

_HUMAN_OUTCOME_CODES = frozenset(
    {"EXTENSION_UNAVAILABLE", "SELLERSPRITE_LOGIN_REQUIRED", "SELLERSPRITE_PERMISSION_REQUIRED", "SELLERSPRITE_QUOTA_EXCEEDED", "CAPTCHA"}
)
_RETRYABLE_CODES = frozenset({"EXPORT_FAILED", "DOWNLOAD_TIMEOUT"})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PUBLIC_KEYWORD_NUMERIC_FIELDS = (
    "search_volume",
    "search_volume_lower_bound",
    "purchase_volume",
    "purchase_volume_lower_bound",
    "purchase_rate",
    "purchase_rate_lower_bound",
    "competing_products",
    "competing_products_lower_bound",
    "spr",
    "spr_lower_bound",
    "organic_rank",
    "organic_rank_lower_bound",
    "ad_rank",
    "ad_rank_lower_bound",
    "trend_lower_bound",
    "trend_duration_seconds",
    "duration_seconds",
)
_PUBLIC_KEYWORD_TEXT_FIELDS = ("trend", "duration")


@dataclass
class SellerSpriteDependencies:
    """All side effects are injectable so browser tests do not need Chrome."""

    profile: SellerSpriteLocatorProfile | None = None
    session_factory: Callable[[], Any] | None = None
    download_observer: Any | None = None
    importer: Callable[[SellerSpriteContext, Any], ImportedSellerSpriteExport] | None = None
    repository: Any | None = None
    event_recorder: Callable[..., None] | None = None
    clock: Callable[[], float] | None = None
    sleeper: Callable[[float], None] | None = None
    is_cancelled: Callable[[], bool] | None = None
    browser_enabled: bool | None = None
    download_dir: Path | str | None = None
    browser_download_dir: Path | str | None = None
    page_timeout_seconds: int | None = None
    export_timeout_seconds: int | None = None
    min_interval_seconds: int | None = None
    max_retries: int | None = None

    def __post_init__(self) -> None:
        self.importer = self.importer or import_sellersprite_export
        self.event_recorder = self.event_recorder or record_run_event
        self.clock = self.clock or monotonic
        self.sleeper = self.sleeper or sleep
        self.is_cancelled = self.is_cancelled or (lambda: False)
        browser_config = load_sellersprite_browser_config(PROJECT_ROOT, settings)
        self.browser_enabled = (
            browser_config.enabled
            if self.browser_enabled is None
            else bool(self.browser_enabled)
        )
        raw_download_dir = str(
            self.download_dir
            or browser_config.download_dir
            or settings.sellersprite_import_dir
        )
        distro = (os.getenv("WSL_DISTRO_NAME") or "").strip()
        host_download_dir = str(
            getattr(browser_config, "host_download_dir", "") or ""
        ).strip()
        self.download_dir = Path(
            project_local_path(PROJECT_ROOT, raw_download_dir)
            if raw_download_dir.startswith("/app/data/")
            else raw_download_dir
        )
        if self.browser_download_dir is None:
            if host_download_dir not in {"", "configured"}:
                self.browser_download_dir = _host_download_path_for_chrome(
                    host_download_dir,
                    distro=distro,
                )
            elif distro and (wsl_download_dir := os.getenv("SELLERSPRITE_BROWSER_WSL_DOWNLOAD_DIR", "").strip()):
                self.browser_download_dir = _wsl_path_to_windows_share(
                    wsl_download_dir,
                    distro=distro,
                )
            elif distro and raw_download_dir.startswith("/mnt/"):
                self.browser_download_dir = _wsl_mounted_path_to_windows(raw_download_dir)
            elif distro and raw_download_dir.startswith("/app/data/"):
                # Compatibility fallback for non-Docker WSL runs where the
                # process path and the host-visible path are identical.
                self.browser_download_dir = _wsl_path_to_windows_share(
                    str(self.download_dir),
                    distro=distro,
                )
            else:
                self.browser_download_dir = self.download_dir
        self.page_timeout_seconds = self.page_timeout_seconds or settings.sellersprite_browser_page_timeout_seconds
        self.export_timeout_seconds = self.export_timeout_seconds or settings.sellersprite_browser_export_timeout_seconds
        self.min_interval_seconds = self.min_interval_seconds if self.min_interval_seconds is not None else settings.sellersprite_browser_min_interval_seconds
        self.max_retries = self.max_retries if self.max_retries is not None else settings.sellersprite_browser_max_retries
        if self.profile is None and browser_config.locator_profile_path:
            try:
                profile_path = browser_config.locator_profile_path
                self.profile = SellerSpriteLocatorProfile.from_json(
                    project_local_path(PROJECT_ROOT, profile_path)
                    if profile_path.startswith("/app/data/")
                    else Path(profile_path)
                )
            except ValueError:
                self.profile = None
        if self.session_factory is None and self.profile is not None:
            self.session_factory = self._make_default_session
        if self.repository is None:
            self.repository = _default_repository

    def _make_default_session(self) -> PlaywrightSellerSpriteSession:
        assert self.profile is not None
        return PlaywrightSellerSpriteSession(
            profile=self.profile,
            download_dir=self.download_dir,
            browser_download_dir=self.browser_download_dir,
            page_timeout_seconds=int(self.page_timeout_seconds),
            export_timeout_seconds=int(self.export_timeout_seconds),
            download_observer=self.download_observer,
            is_cancelled=self.is_cancelled,
        )


def run_reverse_keyword_export(
    asin: str,
    *,
    sourcing_run_id: str | None = None,
    dependencies: SellerSpriteDependencies | None = None,
) -> SellerSpriteResult:
    """Export, validate, import, then persist one Amazon-US ASIN's keywords."""

    dependencies = dependencies or SellerSpriteDependencies()
    context = SellerSpriteContext.create(asin, sourcing_run_id=sourcing_run_id)
    _record(dependencies, "sellersprite_started", context)
    if (
        not dependencies.browser_enabled
        or dependencies.profile is None
        or dependencies.session_factory is None
    ):
        return _terminal_result(dependencies, context, "EXTENSION_UNAVAILABLE")

    retries = max(0, min(1, int(dependencies.max_retries)))
    for attempt in range(retries + 1):
        attempt_started = dependencies.clock()
        try:
            _ensure_not_cancelled(dependencies)
            with dependencies.session_factory() as session:
                session.open_amazon_product(context.asin)
                _ensure_not_cancelled(dependencies)
                session.check_sellersprite_extension()
                _ensure_not_cancelled(dependencies)
                artifact = session.export_sellersprite_reverse_keywords(context.asin)
                _ensure_not_cancelled(dependencies)
            try:
                _ensure_not_cancelled(dependencies)
                imported = dependencies.importer(context, artifact)
            except SellerSpriteImportError as exc:
                raise SellerSpriteWorkflowError(exc.error_code) from exc
            file_sha256 = _safe_digest(getattr(imported, "artifact", None))
            if file_sha256 is None:
                # The importer is the integrity boundary.  A successful export
                # is not public evidence unless its imported artifact has a
                # canonical SHA-256 digest.
                raise SellerSpriteWorkflowError("INVALID_EXPORT")
            keyword_rows = _public_keyword_rows(getattr(imported, "rows", []))
            _record(
                dependencies,
                "sellersprite_exported",
                context,
                {"file_sha256": file_sha256},
            )
            _ensure_not_cancelled(dependencies)
            persisted = _save(dependencies.repository, imported)
            _ensure_not_cancelled(dependencies)
            manifest_id = _safe_manifest_id(persisted)
            if manifest_id is None:
                # The database result closes the artifact-to-manifest evidence
                # chain.  Do not publish success without its immutable ID.
                raise SellerSpriteWorkflowError("INTERNAL")
            _record(
                dependencies,
                "sellersprite_imported",
                context,
                {"row_count": imported.row_count, "manifest_id": manifest_id},
            )
            return SellerSpriteResult(
                status="SUCCESS",
                context=context,
                data={
                    "row_count": imported.row_count,
                    "file_sha256": file_sha256,
                    "keyword_rows": keyword_rows,
                    "manifest_id": manifest_id,
                },
            )
        except SellerSpriteWorkflowError as exc:
            error_code = exc.error_code
        except TimeoutError:
            raise
        except Exception:
            error_code = "INTERNAL"

        if error_code in _RETRYABLE_CODES and attempt < retries:
            _record(dependencies, "sellersprite_retry", context, {"error_code": error_code})
            elapsed = max(0.0, dependencies.clock() - attempt_started)
            delay = max(0.0, float(dependencies.min_interval_seconds) - elapsed)
            if delay:
                dependencies.sleeper(delay)
            continue
        return _terminal_result(dependencies, context, error_code)

    return _terminal_result(dependencies, context, "INTERNAL")


def _ensure_not_cancelled(dependencies: SellerSpriteDependencies) -> None:
    if dependencies.is_cancelled():
        raise SellerSpriteWorkflowError("CANCELLED")


def _terminal_result(
    dependencies: SellerSpriteDependencies,
    context: SellerSpriteContext,
    error_code: str,
) -> SellerSpriteResult:
    safe_error_code = normalize_sellersprite_error_code(error_code)
    _record(dependencies, "sellersprite_failed", context, {"error_code": safe_error_code})
    if safe_error_code in _HUMAN_OUTCOME_CODES:
        return SellerSpriteResult.needs_human(context, safe_error_code)
    return SellerSpriteResult(status=safe_error_code, context=context, error_code=safe_error_code)


def _record(
    dependencies: SellerSpriteDependencies,
    event: str,
    context: SellerSpriteContext,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        dependencies.event_recorder(
            event=event,
            job_id=context.sourcing_run_id,
            stage="sellersprite",
            asin=context.asin,
            payload={"call_id": context.call_id, **(payload or {})},
        )
    except Exception:
        # Telemetry must never alter the controlled browser outcome.
        pass


def _save(repository: Any, imported: ImportedSellerSpriteExport) -> Any:
    save = getattr(repository, "save", None)
    return save(imported) if callable(save) else repository(imported)


def _default_repository(imported: ImportedSellerSpriteExport) -> dict[str, Any]:
    from db.sellersprite_repository import save_sellersprite_import
    from db.session import engine

    return save_sellersprite_import(engine, imported)


def _safe_digest(artifact: Any) -> str | None:
    digest = getattr(artifact, "sha256", None)
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        return None
    return digest.lower()


def _safe_manifest_id(persisted: Any) -> str | None:
    value = persisted.get("id") if isinstance(persisted, dict) else None
    if not isinstance(value, str):
        return None
    try:
        canonical = str(UUID(value))
    except ValueError:
        return None
    return canonical if value == canonical else None


def _public_keyword_rows(rows: object) -> list[dict[str, Any]]:
    """Return a bounded, typed projection of normalized importer rows.

    ``raw_payload`` belongs to the persisted audit manifest only.  The public
    workflow result deliberately contains only documented metrics so callers
    never receive source columns, paths, or other implementation details.
    """
    if not isinstance(rows, list):
        return []
    public_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keyword = row.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        safe_row: dict[str, Any] = {"keyword": keyword.strip()}
        for field in _PUBLIC_KEYWORD_NUMERIC_FIELDS:
            value = row.get(field)
            if _is_safe_metric_number(value):
                safe_row[field] = value
        for field in _PUBLIC_KEYWORD_TEXT_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                safe_row[field] = value.strip()
        public_rows.append(safe_row)
        if len(public_rows) == 20:
            break
    return public_rows


def _is_safe_metric_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _wsl_mounted_path_to_windows(value: str) -> str:
    path = Path(value)
    parts = path.parts
    if len(parts) < 4 or parts[1] != "mnt" or len(parts[2]) != 1:
        return value
    drive = parts[2].upper()
    suffix = "\\".join(parts[3:])
    return f"{drive}:\\{suffix}"


def _host_download_path_for_chrome(value: str, *, distro: str) -> str:
    """Translate an explicit host path without changing the container observer."""
    return _wsl_path_to_windows_share(value, distro=distro) if distro else value


def _wsl_path_to_windows_share(value: str, *, distro: str) -> str:
    """Map a WSL-visible directory to the UNC path Chrome on Windows can use."""
    raw = str(value or "").strip()
    if raw.startswith("/mnt/"):
        return _wsl_mounted_path_to_windows(raw)
    if raw.startswith("/") and distro:
        return f"\\\\wsl.localhost\\{distro}{raw.replace('/', '\\')}"
    return raw
