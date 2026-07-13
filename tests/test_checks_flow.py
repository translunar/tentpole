from tentpole.buckets import buckets_for
from tentpole.checks import dependency_readiness, ghost_claims
from tentpole.model import Ghost, Issue, Link


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def blocked_by(other_key):
    return [Link(type="Blocks", direction="inward", other_key=other_key)]


def test_dependency_readiness(make_bundle):
    issues = [
        _task("T-1", assignee="ada", sprint_id=2, links=blocked_by("X-1")),
        _task("X-1", external=True, sprint_id=5),      # finishes after T-1 starts
        _task("T-2", assignee="ada", sprint_id=2, links=blocked_by("X-2")),
        _task("X-2", external=True, status_category="done"),   # fine
        _task("T-3", assignee="grace", sprint_id=2, links=blocked_by("X-3")),
        _task("X-3", external=True),                   # open, unscheduled
        _task("T-4", assignee="grace", sprint_id=2, links=blocked_by("GONE-1")),
    ]
    b = make_bundle(issues=issues)
    findings = dependency_readiness(b, buckets_for(b))
    by_msg = {f.message for f in findings}
    assert len(findings) == 3
    assert any("T-1" in m and "X-1" in m for m in by_msg)
    assert any("T-3" in m and "unscheduled" in m for m in by_msg)
    assert any("GONE-1" in m and "not in data" in m for m in by_msg)
    gone = next(f for f in findings if "GONE-1" in f.message)
    assert gone.severity == "yellow"


def test_ghost_claims_current_plan_only(make_bundle):
    b = make_bundle(ghosts=[
        Ghost(title="Now-ish", estimate_days=3.0, target="sprint:2",
              owner="ada"),
        Ghost(title="Later", estimate_days=3.0, target="plan+1"),
        Ghost(title="Ticketed", estimate_days=3.0, target="sprint:2",
              jira_key="T-1"),
    ])
    findings = ghost_claims(b, buckets_for(b))
    assert len(findings) == 1
    assert findings[0].subject == "ada"
    assert "Now-ish" in findings[0].message
