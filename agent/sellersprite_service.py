"""Bounded orchestration for one SellerSprite reverse-keyword export."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable

from agent.run_events import record_run_event
from agent.sellersprite_models import SellerSpriteContext, SellerSpriteLocatorProfile, SellerSpriteResult
from agent.sellersprite_policy import normalize_sellersprite_error_code
from agent.tools.sellersprite_browser import PlaywrightSellerSpriteSession, SellerSpriteWorkflowError
from agent.tools.sellersprite_importer import (
    ImportedSellerSpriteExport,
    SellerSpriteImportError,
    import_sellersprite_export,
)
from config.settings import settings


_HUMAN_OUTCOME_CODES = frozenset(
    {"EXTENSION_UNAVAILABLE", "SELLERSPRITE_LOGIN_REQUIRED", "SELLERSPRITE_PERMISSION_REQUIRED", "CAPTCHA"}
)
_RETRYABLE_CODES = frozenset({"EXPORT_FAILED", "DOWNLOAD_TIMEOUT"})


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
        self.browser_enabled = (
            settings.sellersprite_browser_enabled
            if self.browser_enabled is None
            else bool(self.browser_enabled)
        )
        self.download_dir = Path(
            self.download_dir
            or settings.sellersprite_browser_download_dir
            or settings.sellersprite_import_dir
        )
        self.page_timeout_seconds = self.page_timeout_seconds or settings.sellersprite_browser_page_timeout_seconds
        self.export_timeout_seconds = self.export_timeout_seconds or settings.sellersprite_browser_export_timeout_seconds
        self.min_interval_seconds = self.min_interval_seconds if self.min_interval_seconds is not None else settings.sellersprite_browser_min_interval_seconds
        self.max_retries = self.max_retries if self.max_retries is not None else settings.sellersprite_browser_max_retries
        if self.profile is None and settings.sellersprite_browser_locator_profile_path:
            try:
                self.profile = SellerSpriteLocatorProfile.from_json(
                    Path(settings.sellersprite_browser_locator_profile_path)
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
            _record(
                dependencies,
                "sellersprite_exported",
                context,
                {"file_sha256": _safe_digest(artifact)},
            )
            _ensure_not_cancelled(dependencies)
            persisted = _save(dependencies.repository, imported)
            _ensure_not_cancelled(dependencies)
            _record(
                dependencies,
                "sellersprite_imported",
                context,
                {"row_count": imported.row_count, "manifest_id": _safe_manifest_id(persisted)},
            )
            return SellerSpriteResult(
                status="SUCCESS",
                context=context,
                data={
                    "row_count": imported.row_count,
                    "keywords": [row.get("keyword") for row in imported.rows],
                    "manifest_id": _safe_manifest_id(persisted),
                },
            )
        except SellerSpriteWorkflowError as exc:
            error_code = exc.error_code
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
    return digest if isinstance(digest, str) and len(digest) == 64 else None


def _safe_manifest_id(persisted: Any) -> str | None:
    value = persisted.get("id") if isinstance(persisted, dict) else None
    return value if isinstance(value, str) else None
