from datetime import date

from tentpole.checks import carryover
from tentpole.model import Issue


def _issue(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_carryover_fires_for_replanned_ticket(make_bundle):
    # T-42 was sprint-planned in the prior run, is still not done, and is
    # sprint-planned again -> yellow, subject = assignee, carries epic_key.
    prior = [{"run": "2026-05-01", "key": "T-42", "sprint_id": 3,
              "status": "in_progress", "remaining": 5.0,
              "assignee": "ada", "epic_key": "E-1"}]
    b = make_bundle(issues=[
        _issue("T-42", assignee="ada", sprint_id=5, epic_key="E-1",
               status_category="in_progress", remaining_estimate_days=3.0)])
    findings = carryover(b, prior)
    assert len(findings) == 1
    f = findings[0]
    assert (f.check, f.severity, f.subject) == ("carryover", "yellow", "ada")
    assert f.epic_key == "E-1"
    assert "T-42" in f.message and "5.0d" in f.message and "3.0d" in f.message


def test_carryover_quiet_when_done_or_unplanned(make_bundle):
    prior = [
        {"run": "2026-05-01", "key": "T-1", "sprint_id": 3},
        {"run": "2026-05-01", "key": "T-2", "sprint_id": 3},
    ]
    b = make_bundle(issues=[
        _issue("T-1", sprint_id=5, status_category="done"),   # done now
        _issue("T-2", sprint_id=None),                         # not planned now
    ])
    assert carryover(b, prior) == []


def test_carryover_quiet_when_not_planned_before(make_bundle):
    prior = [{"run": "2026-05-01", "key": "T-1", "sprint_id": None}]
    b = make_bundle(issues=[_issue("T-1", sprint_id=5)])
    assert carryover(b, prior) == []


def test_carryover_no_prior_no_findings(make_bundle):
    b = make_bundle(issues=[_issue("T-1", sprint_id=5)])
    assert carryover(b, None) == []
    assert carryover(b, []) == []


def test_carryover_uses_only_most_recent_prior_run(make_bundle):
    # Two prior runs; only the most recent (2026-06-01) counts as "was
    # planned". T-1 was planned in the OLD run but not the recent one -> no
    # carryover.
    prior = [
        {"run": "2026-05-01", "key": "T-1", "sprint_id": 3},
        {"run": "2026-06-01", "key": "T-1", "sprint_id": None},
    ]
    b = make_bundle(issues=[_issue("T-1", sprint_id=5)])
    assert carryover(b, prior) == []
