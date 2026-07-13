from tentpole.model import Issue
from tentpole.sync import run_sync


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


def test_run_sync_end_to_end(make_bundle):
    b = make_bundle(issues=[_task("T-1", assignee="ada", sprint_id=1,
                                  remaining_estimate_days=3.0)])
    result = run_sync(b, None, {})
    assert set(result.specs) == {"issues", "epics", "fixversions",
                                 "dependencies", "capacity", "accuracy"}
    issue_ops = {(c.op, c.key) for c in result.plans["issues"]}
    assert ("add", "T-1") in issue_ops
    assert result.snapshots[0]["key"] == "T-1"
    assert result.report["changes"]["issues"]["add"] == 1
    assert result.diag["as_of"] == b.as_of


def test_run_sync_uses_current_state(make_bundle):
    b = make_bundle(issues=[_task("T-1", assignee="ada", sprint_id=1,
                                  remaining_estimate_days=3.0)])
    first = run_sync(b, None, {})
    # replay: state now exactly matches the spec for T-1's synced cells
    add = next(c for c in first.plans["issues"] if c.key == "T-1")
    state = {"issues": {"T-1": dict(add.cells)}}
    second = run_sync(b, None, state)
    t1_changes = [c for c in second.plans["issues"] if c.key == "T-1"]
    assert t1_changes == []
