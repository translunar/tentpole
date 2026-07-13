from tentpole.buckets import buckets_for
from tentpole.checks import sprint_overload, team_subscription
from tentpole.demand import compile_demand
from tentpole.model import Config, Ghost, Issue


def _task(key, person, est, sprint_id=None, **kw):
    return Issue(key=key, summary="t", issue_type="Task",
                 status_category="todo", assignee=person,
                 remaining_estimate_days=est, sprint_id=sprint_id, **kw)


def test_sprint_overload_flags_only_over_capacity(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", "ada", 9.0, sprint_id=1),   # prior is ~7.65 -> overloaded
        _task("T-2", "grace", 2.0, sprint_id=1),  # fine
    ])
    bks = buckets_for(b)
    findings = sprint_overload(b, bks, compile_demand(b, bks))
    assert len(findings) == 1
    f = findings[0]
    assert (f.check, f.severity, f.subject, f.bucket_id) == (
        "sprint_overload", "red", "ada", "sprint:1")
    assert "9.0" in f.message


def test_team_subscription_counts_ghosts_and_tbd(make_bundle):
    # Team of 2, prior ~7.65 each -> sprint capacity ~15.3; plan+1 ~91.8
    b = make_bundle(
        issues=[_task("T-1", "ada", 4.0, sprint_id=1)],
        ghosts=[Ghost(title="Big ghost", estimate_days=100.0,
                      target="plan+1", owner=None)])
    bks = buckets_for(b)
    findings = team_subscription(b, bks, compile_demand(b, bks))
    assert [f.bucket_id for f in findings] == ["plan+1"]
    assert findings[0].subject == "team"
    assert "100.0" in findings[0].message
