from datetime import date

from tentpole.buckets import buckets_for
from tentpole.demand import compile_demand, estimate_of, is_overhead
from tentpole.model import Config, FixVersion, Ghost, Issue


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_is_overhead_by_label_and_summary():
    cfg = Config()
    assert is_overhead(_task("T-1", labels=["overhead"]), cfg)
    assert is_overhead(_task("T-2", summary="On console week 3"), cfg)
    assert not is_overhead(_task("T-3", summary="Parse frames"), cfg)


def test_estimate_prefers_remaining():
    assert estimate_of(_task("T-1", original_estimate_days=5.0,
                             remaining_estimate_days=2.0)) == 2.0
    assert estimate_of(_task("T-2", original_estimate_days=5.0)) == 5.0
    assert estimate_of(_task("T-3")) == 0.0


def test_compile_demand_kinds_and_exclusions(make_bundle):
    issues = [
        _task("T-1", assignee="ada", sprint_id=1, remaining_estimate_days=3.0,
              epic_key="E-1", program="telemetry"),
        _task("T-2", assignee="ada", sprint_id=1, remaining_estimate_days=4.0,
              labels=["overhead"]),
        _task("T-3", assignee="ada", status_category="done",
              remaining_estimate_days=9.0),           # done: excluded
        Issue(key="E-1", summary="Epic", issue_type="Epic",
              status_category="in_progress"),          # epic: excluded
        _task("X-1", assignee="sam", external=True,
              remaining_estimate_days=9.0),            # external: excluded
    ]
    b = make_bundle(issues=issues)
    items = compile_demand(b, buckets_for(b))
    by_source = {i.source: i for i in items}
    assert by_source["T-1"].kind == "real"
    assert by_source["T-1"].bucket_id == "sprint:1"
    assert by_source["T-1"].fix_versions == ()
    assert by_source["T-2"].kind == "overhead"
    assert {"T-3", "E-1", "X-1"}.isdisjoint(by_source)


def test_compile_demand_ghosts(make_bundle):
    ghosts = [
        Ghost(title="Cal pipeline", estimate_days=8.0, target="plan+1",
              owner=None, intended_epic="E-1", program="telemetry"),
        Ghost(title="Already real", estimate_days=5.0, target="plan+1",
              jira_key="T-9"),                          # superseded: excluded
        Ghost(title="Sprint-targeted", estimate_days=2.0, target="sprint:3",
              owner="grace"),
        Ghost(title="Milestone-targeted", estimate_days=2.0,
              target="fixversion:v9"),
    ]
    b = make_bundle(
        ghosts=ghosts,
        fix_versions=[FixVersion("v9", release_date=date(2026, 10, 1))])
    items = {i.source: i for i in compile_demand(b, buckets_for(b))}
    assert items["Cal pipeline"].kind == "ghost"
    assert items["Cal pipeline"].who is None
    assert items["Cal pipeline"].epic_key == "E-1"
    assert "Already real" not in items
    assert items["Sprint-targeted"].bucket_id == "sprint:3"
    assert items["Milestone-targeted"].bucket_id == "plan+1"
