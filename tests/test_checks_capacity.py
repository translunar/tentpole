from tentpole.buckets import buckets_for
from tentpole.checks import sprint_overload, team_drift, team_subscription
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


def test_team_subscription_zero_capacity_does_not_crash(make_bundle):
    b = make_bundle(config=Config(team=[]),
                    ghosts=[Ghost(title="Orphan ghost", estimate_days=5.0,
                                  target="plan+1")])
    bks = buckets_for(b)
    findings = team_subscription(b, bks, compile_demand(b, bks))
    assert [f.bucket_id for f in findings] == ["plan+1"]
    assert "subscribed" not in findings[0].message


def _drift_findings(bundle):
    buckets = buckets_for(bundle)
    return team_drift(bundle, buckets, compile_demand(bundle, buckets))


def test_team_drift_flags_both_directions(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", "ada", 3.0, sprint_id=1),
        _task("T-2", "hopper", 4.0, sprint_id=1),
    ])   # team is ["ada", "grace"]
    findings = _drift_findings(b)
    by_subject = {f.subject: f for f in findings}
    assert set(by_subject) == {"hopper", "grace"}
    assert all(f.check == "team_drift" and f.severity == "yellow"
               for f in findings)
    assert "4.0d" in by_subject["hopper"].message
    assert "not in team" in by_subject["hopper"].message
    assert "no work" in by_subject["grace"].message


def test_team_drift_quiet_when_roster_matches_work(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", "ada", 3.0, sprint_id=1),
        _task("T-2", "grace", 1.0, sprint_id=1),
    ])
    assert _drift_findings(b) == []


def test_team_drift_quiet_on_empty_plan(make_bundle):
    assert _drift_findings(make_bundle()) == []


def test_team_drift_ghost_counts_as_presence(make_bundle):
    b = make_bundle(
        issues=[_task("T-1", "ada", 3.0, sprint_id=1)],
        ghosts=[Ghost(title="future thing", estimate_days=5.0,
                      target="sprint:2", owner="grace")])
    assert _drift_findings(b) == []
