from __future__ import annotations

import pytest

from agent.trial_feedback import (
    list_trial_feedback,
    save_trial_feedback,
    summarize_trial_feedback,
)


def _payload(**overrides):
    payload = {
        "job_id": "trialjob0001",
        "job_status": "review_required",
        "source_mode": "keyword",
        "workflow_completed": True,
        "deliverables_ready": True,
        "ease": 4,
        "result_usefulness": 5,
        "would_use_again": True,
        "blocked_stage": "none",
        "comment": "报告说明清楚",
    }
    payload.update(overrides)
    return payload


def test_feedback_is_saved_and_upserted_per_job(tmp_path):
    path = tmp_path / "trial_feedback.json"

    first = save_trial_feedback(_payload(), path=path)
    updated = save_trial_feedback(_payload(ease=2, comment="需要少一步"), path=path)
    rows = list_trial_feedback(job_id="trialjob0001", path=path)

    assert updated["id"] == first["id"]
    assert rows == [updated]
    assert rows[0]["ease"] == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ease", 0),
        ("result_usefulness", 6),
        ("would_use_again", "yes"),
        ("blocked_stage", "unknown"),
        ("source_mode", "asin"),
        ("workflow_completed", "yes"),
        ("deliverables_ready", 1),
        ("comment", "x" * 501),
    ],
)
def test_feedback_rejects_invalid_values(tmp_path, field, value):
    with pytest.raises(ValueError):
        save_trial_feedback(
            _payload(**{field: value}),
            path=tmp_path / "trial_feedback.json",
        )


def test_feedback_summary_waits_for_three_completed_trials(tmp_path):
    path = tmp_path / "trial_feedback.json"
    save_trial_feedback(_payload(job_id="trialjob0001"), path=path)
    save_trial_feedback(_payload(job_id="trialjob0002"), path=path)

    summary = summarize_trial_feedback(path=path)

    assert summary["status"] == "collecting"
    assert summary["ready_for_installer"] is False
    assert summary["sample_size"] == 2
    assert summary["remaining_trials"] == 1
    assert summary["metrics"]["average_ease"] == 4.0
    assert summary["metrics"]["source_mode_count"] == 1


def test_feedback_summary_marks_installer_ready_only_when_all_gates_pass(tmp_path):
    path = tmp_path / "trial_feedback.json"
    for index, ease in enumerate((4, 5, 4), start=1):
        save_trial_feedback(
            _payload(
                job_id=f"trialjob000{index}",
                source_mode="category" if index == 1 else "keyword",
                ease=ease,
                result_usefulness=5,
                would_use_again=index != 3,
                blocked_stage="report" if index == 3 else "none",
            ),
            path=path,
        )

    summary = summarize_trial_feedback(path=path)

    assert summary["status"] == "ready_for_installer"
    assert summary["ready_for_installer"] is True
    assert summary["metrics"]["would_use_again_rate"] == 0.667
    assert summary["metrics"]["no_blocker_rate"] == 0.667
    assert summary["metrics"]["delivery_rate"] == 1.0
    assert summary["metrics"]["source_modes"] == ["category", "keyword"]
    assert all(criterion["passed"] for criterion in summary["criteria"])
    assert summary["top_blocker"] == "report"


def test_feedback_summary_exposes_failed_gate_and_top_blocker(tmp_path):
    path = tmp_path / "trial_feedback.json"
    for index in range(1, 4):
        save_trial_feedback(
            _payload(
                job_id=f"trialjob000{index}",
                source_mode="category" if index == 1 else "keyword",
                ease=3,
                result_usefulness=3,
                would_use_again=False,
                blocked_stage="preflight",
            ),
            path=path,
        )

    summary = summarize_trial_feedback(path=path)

    assert summary["status"] == "needs_improvement"
    assert summary["ready_for_installer"] is False
    assert summary["top_blocker"] == "preflight"
    assert summary["blocker_counts"]["preflight"] == 3
    assert summary["criteria"][0]["passed"] is True
    assert any(
        criterion["key"] == "average_ease" and not criterion["passed"]
        for criterion in summary["criteria"]
    )


def test_feedback_summary_rejects_high_ratings_without_real_delivery(tmp_path):
    path = tmp_path / "trial_feedback.json"
    for index in range(1, 4):
        save_trial_feedback(
            _payload(
                job_id=f"trialjob000{index}",
                source_mode="category" if index == 1 else "keyword",
                ease=5,
                result_usefulness=5,
                would_use_again=True,
                blocked_stage="none",
                workflow_completed=index != 3,
                deliverables_ready=index != 3,
            ),
            path=path,
        )

    summary = summarize_trial_feedback(path=path)

    assert summary["metrics"]["delivery_rate"] == 0.667
    assert summary["status"] == "ready_for_installer"

    save_trial_feedback(
        _payload(
            job_id="trialjob0002",
            source_mode="keyword",
            ease=5,
            result_usefulness=5,
            would_use_again=True,
            blocked_stage="none",
            workflow_completed=False,
            deliverables_ready=False,
        ),
        path=path,
    )
    summary = summarize_trial_feedback(path=path)

    assert summary["metrics"]["delivery_rate"] == 0.333
    assert summary["status"] == "needs_improvement"
    assert any(
        criterion["key"] == "delivery_rate" and not criterion["passed"]
        for criterion in summary["criteria"]
    )
