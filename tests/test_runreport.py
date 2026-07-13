from tentpole.changeplan import Change
from tentpole.diagnostics import assemble
from tentpole.model import Ghost, Issue
from tentpole.runreport import build_report, render_report


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


def test_build_report(make_bundle):
    b = make_bundle(
        issues=[_task("T-1", assignee="ada", sprint_id=1,
                      remaining_estimate_days=12.0)],       # overload red
        ghosts=[Ghost(title="Stale ghost", estimate_days=1.0,
                      target="plan+1", jira_key="GONE-9")])
    plans = {"issues": [Change("add", "T-1", {}),
                        Change("flag_gone", "T-9", {"In Jira": False})],
             "capacity": []}
    report = build_report(b, assemble(b), plans)
    assert report["as_of"] == "2026-07-12"
    assert report["issues"] == 1
    assert report["reds"] >= 1
    assert report["findings"]["sprint_overload"] == 1
    assert report["ghosts_unknown_jira_key"] == ["Stale ghost"]
    assert report["changes"]["issues"] == {"add": 1, "flag_gone": 1}
    assert "capacity" not in report["changes"]


def test_render_report(make_bundle):
    b = make_bundle(issues=[_task("T-1")])
    report = build_report(b, assemble(b), {"issues": [Change("add", "T-1", {})]})
    text = render_report(report)
    assert "SYNC HEALTH" in text
    assert "issues" in text
    assert "2026-07-12" in text
