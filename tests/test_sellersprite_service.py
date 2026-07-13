from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent.sellersprite_models import SellerSpriteLocatorProfile
from agent.sellersprite_service import (
    SellerSpriteDependencies,
    run_reverse_keyword_export,
)
from agent.tools.sellersprite_browser import SellerSpriteWorkflowError
from agent.tools.sellersprite_importer import SellerSpriteImportError
from config.settings import settings


def valid_profile() -> SellerSpriteLocatorProfile:
    return SellerSpriteLocatorProfile(
        ready="css=ready",
        login_required="css=login_required",
        permission_required="css=permission_required",
        captcha="css=captcha",
        reverse_keywords="css=reverse_keywords",
        asin_input="css=asin_input",
        submit="css=submit",
        results_ready="css=results_ready",
        export="css=export",
    )


@dataclass
class FakeImported:
    rows: list[dict[str, object]]
    row_count: int


class FakeSession:
    def __init__(self, *, error_code: str | None = None, artifact: object | None = None) -> None:
        self.error_code = error_code
        self.artifact = artifact if artifact is not None else object()
        self.opened: list[str] = []
        self.checked = 0
        self.exported = 0

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def open_amazon_product(self, asin: str) -> None:
        self.opened.append(asin)
        self._maybe_fail()

    def check_sellersprite_extension(self) -> None:
        self.checked += 1
        self._maybe_fail()

    def export_sellersprite_reverse_keywords(self, _asin: str) -> object:
        self.exported += 1
        self._maybe_fail()
        return self.artifact

    def _maybe_fail(self) -> None:
        if self.error_code:
            raise SellerSpriteWorkflowError(self.error_code)


class ExportErrorSession(FakeSession):
    def open_amazon_product(self, asin: str) -> None:
        self.opened.append(asin)

    def check_sellersprite_extension(self) -> None:
        self.checked += 1

    def export_sellersprite_reverse_keywords(self, _asin: str) -> object:
        self.exported += 1
        assert self.error_code is not None
        raise SellerSpriteWorkflowError(self.error_code)


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[FakeImported] = []

    def save(self, imported: FakeImported) -> dict[str, str]:
        self.saved.append(imported)
        return {"id": "manifest-1"}


@pytest.fixture
def fake_dependencies():
    session = FakeSession()
    repository = FakeRepository()
    events: list[dict[str, object]] = []
    imported = FakeImported(
        rows=[{"keyword": "umbrella"}, {"keyword": "patio umbrella"}],
        row_count=2,
    )
    dependencies = SellerSpriteDependencies(
        profile=valid_profile(),
        session_factory=lambda: session,
        browser_enabled=True,
        importer=lambda _context, _artifact: imported,
        repository=repository,
        event_recorder=lambda **event: events.append(event),
        sleeper=lambda _seconds: None,
        max_retries=1,
    )
    return dependencies, session, repository, events


def test_workflow_opens_checks_exports_imports_and_persists(fake_dependencies):
    dependencies, session, repository, events = fake_dependencies

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "SUCCESS"
    assert session.opened == ["B00Q7OAN50"]
    assert session.checked == 1
    assert session.exported == 1
    assert result.data["row_count"] == 2
    assert len(result.data["keywords"]) == 2
    assert repository.saved and events[-1]["event"] == "sellersprite_imported"


@pytest.mark.parametrize(
    ("error_code", "status"),
    [
        ("SELLERSPRITE_LOGIN_REQUIRED", "NEEDS_HUMAN"),
        ("SELLERSPRITE_PERMISSION_REQUIRED", "NEEDS_HUMAN"),
        ("CAPTCHA", "NEEDS_HUMAN"),
        ("ASIN_MISMATCH", "ASIN_MISMATCH"),
        ("AMBIGUOUS_DOWNLOAD", "AMBIGUOUS_DOWNLOAD"),
        ("INVALID_EXPORT", "INVALID_EXPORT"),
        ("CANCELLED", "CANCELLED"),
    ],
)
def test_terminal_errors_do_not_retry_or_persist(fake_dependencies, error_code, status):
    dependencies, session, repository, _events = fake_dependencies
    session.error_code = error_code

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == status
    assert result.error_code == error_code
    assert session.checked == 0 or session.checked == 1
    assert session.exported == 0
    assert repository.saved == []


def test_absent_profile_never_constructs_or_guesses_browser_selector(fake_dependencies):
    dependencies, session, _repository, _events = fake_dependencies
    dependencies.profile = None

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "NEEDS_HUMAN"
    assert result.error_code == "EXTENSION_UNAVAILABLE"
    assert session.opened == []


def test_disabled_browser_setting_blocks_even_injected_runnable_session(monkeypatch):
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", False)
    session = FakeSession()
    dependencies = SellerSpriteDependencies(
        profile=valid_profile(),
        session_factory=lambda: session,
    )

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "NEEDS_HUMAN"
    assert result.error_code == "EXTENSION_UNAVAILABLE"
    assert session.opened == []


def test_cancellation_after_navigation_stops_before_extension_check(fake_dependencies):
    dependencies, session, repository, _events = fake_dependencies
    cancelled = False

    def is_cancelled() -> bool:
        return cancelled

    def cancel_after_open(asin: str) -> None:
        nonlocal cancelled
        session.opened.append(asin)
        cancelled = True

    session.open_amazon_product = cancel_after_open
    dependencies.is_cancelled = is_cancelled

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "CANCELLED"
    assert session.opened == ["B00Q7OAN50"]
    assert session.checked == 0
    assert session.exported == 0
    assert repository.saved == []


def test_export_event_is_recorded_before_repository_failure(fake_dependencies):
    dependencies, session, _repository, events = fake_dependencies

    def fail_save(_imported):
        raise RuntimeError("database unavailable")

    session.artifact = type("Artifact", (), {"sha256": "a" * 64})()
    dependencies.repository = fail_save
    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    exported = [event for event in events if event["event"] == "sellersprite_exported"]
    assert result.status == "INTERNAL"
    assert len(exported) == 1
    assert exported[0]["payload"]["file_sha256"] == "a" * 64
    assert events[-1]["event"] == "sellersprite_failed"


def test_default_session_receives_dependency_cancellation_predicate(tmp_path):
    dependencies = SellerSpriteDependencies(
        profile=valid_profile(),
        browser_enabled=True,
        download_dir=tmp_path,
        is_cancelled=lambda: True,
    )

    session = dependencies._make_default_session()

    with pytest.raises(SellerSpriteWorkflowError, match="CANCELLED"):
        session.__enter__()


def test_transient_export_failure_retries_once(fake_dependencies):
    dependencies, _session, repository, _events = fake_dependencies
    first = ExportErrorSession(error_code="EXPORT_FAILED")
    second = FakeSession()
    sessions = [first, second]
    dependencies.session_factory = lambda: sessions.pop(0)

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "SUCCESS"
    assert repository.saved
    assert first.exported == 1 and second.exported == 1


def test_download_timeout_retries_at_most_once(fake_dependencies):
    dependencies, _session, repository, _events = fake_dependencies
    sessions = [FakeSession(error_code="DOWNLOAD_TIMEOUT"), FakeSession()]
    dependencies.session_factory = lambda: sessions.pop(0)

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "SUCCESS"
    assert repository.saved
    assert sessions == []


def test_invalid_export_from_importer_is_not_persisted_or_retried(fake_dependencies):
    dependencies, session, repository, _events = fake_dependencies

    def invalid_importer(_context, _artifact):
        raise SellerSpriteImportError("INVALID_EXPORT")

    dependencies.importer = invalid_importer
    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "INVALID_EXPORT"
    assert result.error_code == "INVALID_EXPORT"
    assert session.exported == 1
    assert repository.saved == []


def test_non_retryable_error_after_an_export_click_never_clicks_again(fake_dependencies):
    dependencies, _session, repository, _events = fake_dependencies
    first = ExportErrorSession(error_code="CAPTCHA")
    second = FakeSession()
    sessions = [first, second]
    dependencies.session_factory = lambda: sessions.pop(0)

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "NEEDS_HUMAN"
    assert result.error_code == "CAPTCHA"
    assert first.exported == 1
    assert len(sessions) == 1
    assert repository.saved == []


def test_cancellation_stops_before_browser_or_persistence(fake_dependencies):
    dependencies, session, repository, _events = fake_dependencies
    dependencies.is_cancelled = lambda: True

    result = run_reverse_keyword_export("B00Q7OAN50", dependencies=dependencies)

    assert result.status == "CANCELLED"
    assert session.opened == []
    assert repository.saved == []
