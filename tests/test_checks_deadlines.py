from datetime import date

from tentpole.buckets import buckets_for
from tentpole.checks import deadline_risk, tentpole_runway
from tentpole.demand import compile_demand
from tentpole.model import Config, FixVersion, Ghost, Issue


def _task(key, person=None, est=1.0, **kw):
    kw.setdefault("status_category", "todo")
    return Issue(key=key, summary="t", issue_type="Task",
                 assignee=person, remaining_estimate_days=est, **kw)


def test_deadline_risk(make_bundle):
    # v1 releases 2026-08-01, during sprint 2 (Jul 23 - Aug 1)
    fv = FixVersion("v1", release_date=date(2026, 8, 1))
    b = make_bundle(fix_versions=[fv], issues=[
        _task("OK-1", sprint_id=1, fix_versions=["v1"]),      # before: fine
        _task("LATE-1", sprint_id=4, fix_versions=["v1"]),    # after: red
        _task("LOST-1", fix_versions=["v1"]),  # no sprint -> deadline bucket,
                                               # which is sprint:2 -> fine
        _task("DONE-1", sprint_id=6, fix_versions=["v1"],
              status_category="done"),                        # done: ignored
    ])
    findings = deadline_risk(b, buckets_for(b))
    assert len(findings) == 1
    assert findings[0].subject == "v1"
    assert "LATE-1" in findings[0].message


def test_deadline_risk_flags_truly_unscheduled(make_bundle):
    fv = FixVersion("v1")  # no release date -> issues land unscheduled
    b = make_bundle(fix_versions=[fv],
                    issues=[_task("U-1", fix_versions=["v1"])])
    findings = deadline_risk(b, buckets_for(b))
    assert len(findings) == 1
    assert "unscheduled" in findings[0].message


def test_tentpole_runway(make_bundle):
    # Epic due end of plan+1 (2026-11-01). ada's prior ~7.65/sprint.
    # Runway: 6 sprints + ~5.2 plan+1 sprints ~= 11.2 -> cap ~85d.
    # Epic remaining 60d real + 40d ghost = 100d > 85d -> red.
    epic = Issue(key="E-1", summary="Big epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v9"])
    b = make_bundle(
        config=Config(team=["ada"]),
        fix_versions=[FixVersion("v9", release_date=date(2026, 11, 1))],
        issues=[
            epic,
            _task("T-1", "ada", 60.0, epic_key="E-1", sprint_id=1),
        ],
        ghosts=[Ghost(title="Rest of epic", estimate_days=40.0,
                      target="plan+1", owner="ada", intended_epic="E-1")])
    bks = buckets_for(b)
    findings = tentpole_runway(b, bks, compile_demand(b, bks))
    assert len(findings) == 1
    assert findings[0].subject == "E-1"
    assert findings[0].check == "tentpole_runway"


def test_tentpole_runway_quiet_when_fits(make_bundle):
    epic = Issue(key="E-1", summary="Small epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v9"])
    b = make_bundle(
        fix_versions=[FixVersion("v9", release_date=date(2026, 11, 1))],
        issues=[epic, _task("T-1", "ada", 10.0, epic_key="E-1", sprint_id=1)])
    bks = buckets_for(b)
    assert tentpole_runway(b, bks, compile_demand(b, bks)) == []
