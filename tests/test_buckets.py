from datetime import date

from tentpole.buckets import (
    bucket_for_date, bucket_for_issue, buckets_for, effective_deadline,
    sprint_equivalents_until,
)
from tentpole.model import Config, FixVersion, Issue


def test_buckets_for_builds_sprints_then_coarse(make_bundle):
    b = make_bundle()  # six 10-day sprints starting 2026-07-13
    ids = [bk.id for bk in buckets_for(b)]
    assert ids == ["sprint:1", "sprint:2", "sprint:3", "sprint:4", "sprint:5",
                   "sprint:6", "plan+1", "plan+2", "beyond", "unscheduled"]
    plan1 = next(bk for bk in buckets_for(b) if bk.id == "plan+1")
    # last sprint ends 2026-09-10; plan+1 covers the next 60 days
    assert plan1.start == date(2026, 9, 11)
    assert plan1.end == date(2026, 11, 9)


def test_past_sprints_are_excluded(make_bundle, make_sprints):
    old = make_sprints(start=date(2026, 5, 1), n=2, first_id=90)
    b = make_bundle(sprints=old + make_sprints())
    ids = [bk.id for bk in buckets_for(b)]
    assert "sprint:90" not in ids and "sprint:1" in ids


def test_bucket_for_date(make_bundle):
    b = make_bundle()
    bks = buckets_for(b)
    assert bucket_for_date(date(2026, 7, 15), bks) == "sprint:1"
    assert bucket_for_date(date(2026, 10, 1), bks) == "plan+1"
    assert bucket_for_date(date(2027, 6, 1), bks) == "beyond"


def test_effective_deadline_inherits_from_epic(make_bundle):
    epic = Issue(key="E-1", summary="Epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v2.3"])
    child = Issue(key="T-1", summary="t", issue_type="Task",
                  status_category="todo", epic_key="E-1")
    b = make_bundle(
        issues=[epic, child],
        fix_versions=[FixVersion("v2.3", release_date=date(2026, 10, 1))])
    assert effective_deadline(child, b) == date(2026, 10, 1)
    orphan = Issue(key="T-2", summary="t", issue_type="Task",
                   status_category="todo")
    b2 = make_bundle(issues=[orphan])
    assert effective_deadline(orphan, b2) is None


def test_bucket_for_issue_prefers_sprint_then_deadline(make_bundle):
    in_sprint = Issue(key="T-1", summary="t", issue_type="Task",
                      status_category="todo", sprint_id=2)
    dated = Issue(key="T-2", summary="t", issue_type="Task",
                  status_category="todo", fix_versions=["v9"])
    neither = Issue(key="T-3", summary="t", issue_type="Task",
                    status_category="todo")
    b = make_bundle(
        issues=[in_sprint, dated, neither],
        fix_versions=[FixVersion("v9", release_date=date(2026, 10, 1))])
    bks = buckets_for(b)
    assert bucket_for_issue(in_sprint, b, bks) == "sprint:2"
    assert bucket_for_issue(dated, b, bks) == "plan+1"
    assert bucket_for_issue(neither, b, bks) == "unscheduled"


def test_sprint_equivalents_until(make_bundle):
    bks = buckets_for(make_bundle())
    # end of sprint 3 -> exactly 3 sprints of runway
    assert sprint_equivalents_until(date(2026, 8, 11), bks, 10.0) == 3.0
    # 30 days into plan+1 -> 6 sprints + ~3 more
    val = sprint_equivalents_until(date(2026, 10, 11), bks, 10.0)
    assert 8.5 < val < 9.5


def test_default_sprints_per_plan_reproduces_60_120_day_spans(make_bundle):
    """Regression guard: 6 sprints x the default 10-day sprint is exactly
    today's 60/120-day coarse horizon, so existing configs and fixtures
    are unaffected by the new knob."""
    b = make_bundle()
    assert b.config.sprints_per_plan == 6
    bks = buckets_for(b)
    plan1 = next(bk for bk in bks if bk.id == "plan+1")
    plan2 = next(bk for bk in bks if bk.id == "plan+2")
    anchor = date(2026, 9, 10)          # last of the six default sprints
    assert (plan1.end - anchor).days == 60
    assert (plan2.end - anchor).days == 120


def test_sprints_per_plan_scales_coarse_bucket_spans(make_bundle):
    b = make_bundle(config=Config(team=["ada", "grace"], sprints_per_plan=4))
    bks = buckets_for(b)
    plan1 = next(bk for bk in bks if bk.id == "plan+1")
    plan2 = next(bk for bk in bks if bk.id == "plan+2")
    # last sprint ends 2026-09-10; 4 sprints x 10 days = a 40-day bucket
    assert plan1.start == date(2026, 9, 11)
    assert plan1.end == date(2026, 10, 20)
    assert plan2.start == date(2026, 10, 21)
    assert plan2.end == date(2026, 11, 29)


def test_sprint_equivalents_at_plan_boundary_equals_sprints_per_plan(
        make_bundle):
    """tentpole_runway converts coarse-bucket days into sprint equivalents
    with sprint_equivalents_until. Because the spans are now derived from
    sprints_per_plan, the end of plan+1 is exactly (near sprints +
    sprints_per_plan) sprints of runway. With the spans hardcoded at 60
    days, a sprints_per_plan of 4 would still have counted ~6 here."""
    b = make_bundle(config=Config(team=["ada"], sprints_per_plan=4))
    bks = buckets_for(b)
    plan1_end = next(bk for bk in bks if bk.id == "plan+1").end
    got = sprint_equivalents_until(plan1_end, bks,
                                   b.config.sprint_length_days)
    assert got == 10.0          # 6 near sprints + 4 plan sprints
