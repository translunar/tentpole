from datetime import date

from tentpole.buckets import buckets_for
from tentpole.checks import (deadline_risk, sprint_overload, team_drift,
                             team_subscription)
from tentpole.demand import compile_demand
from tentpole.model import Config, FixVersion, Ghost, Issue


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


def test_on_call_only_member_is_not_drift(make_bundle):
    # grace's entire sprint is an on-call rotation ticket: compile_demand
    # classifies it kind == "overhead" via the "overhead" label
    # (Config.overhead_label), not "real" or "ghost". Direction 2 of
    # team_drift must still treat her as present on the team.
    b = make_bundle(issues=[
        _task("T-1", "ada", 3.0, sprint_id=1),
        _task("T-2", "grace", 2.0, sprint_id=1, labels=["overhead"]),
    ])
    assert _drift_findings(b) == []


def test_team_subscription_prices_plan_buckets_at_sprints_per_plan(
        make_bundle):
    """Coarse-bucket capacity is throughput x sprints_per_plan. Prior
    throughput is ~7.65d/sprint, so a team of two is ~91.8d of plan+1
    capacity at 6 sprints and ~61.2d at 4 -- a 70d ghost fits the first
    and overruns the second."""
    def _bundle(**kw):
        return make_bundle(
            ghosts=[Ghost(title="G", estimate_days=70.0, target="plan+1")],
            **kw)

    six = _bundle()
    four = _bundle(config=Config(team=["ada", "grace"], sprints_per_plan=4))
    six_bks, four_bks = buckets_for(six), buckets_for(four)
    assert team_subscription(six, six_bks, compile_demand(six, six_bks)) == []
    over = team_subscription(four, four_bks, compile_demand(four, four_bks))
    assert [f.bucket_id for f in over] == ["plan+1"]
    assert "61.2d team capacity" in over[0].message


def test_sprints_per_plan_moves_deadline_risk_and_capacity_together(
        make_bundle):
    """The date spans and the capacity scale are one number. At
    sprints_per_plan=4 the plan+1 window closes 20 days earlier, so a
    deadline that sat exactly on plan+1's last day under the default now
    lands in plan+2 and deadline_risk fires -- while team_subscription
    prices that same bucket at 4 sprints instead of 6. The two checks can
    no longer disagree about how long a plan bucket is."""
    def _bundle(**kw):
        return make_bundle(
            issues=[_task("T-1", "ada", 8.0, fix_versions=["R1"])],
            fix_versions=[FixVersion("R1",
                                     release_date=date(2026, 11, 9))],
            ghosts=[Ghost(title="G", estimate_days=70.0, target="plan+1")],
            **kw)

    six = _bundle()
    four = _bundle(config=Config(team=["ada", "grace"], sprints_per_plan=4))
    six_bks, four_bks = buckets_for(six), buckets_for(four)

    # Default: the deadline is the last day of plan+1 (2026-11-09) and the
    # 78d of demand fits in ~91.8d of capacity. Both checks are quiet.
    assert deadline_risk(six, six_bks) == []
    assert team_subscription(six, six_bks, compile_demand(six, six_bks)) == []

    # sprints_per_plan=4: plan+1 now ends 2026-10-20, so T-1's deadline
    # falls in plan+2 (ends 2026-11-29, past the deadline) and the ghost
    # alone overruns plan+1's 61.2d.
    late = deadline_risk(four, four_bks)
    assert [f.subject for f in late] == ["R1"]
    assert "past the 2026-11-09 deadline" in late[0].message
    over = team_subscription(four, four_bks, compile_demand(four, four_bks))
    assert [f.bucket_id for f in over] == ["plan+1"]
