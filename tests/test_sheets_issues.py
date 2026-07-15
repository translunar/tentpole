from datetime import date

from tentpole.diagnostics import assemble
from tentpole.hygiene import Rule
from tentpole.model import Issue, Link
from tentpole.sheets import issues_sheet


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


def test_issues_sheet_hierarchy_and_cells(make_bundle):
    epic = Issue(key="E-1", summary="Epic one", issue_type="Epic",
                 status_category="in_progress")
    child = _task("T-1", assignee="ada", sprint_id=1, epic_key="E-1",
                  original_estimate_days=5.0, remaining_estimate_days=2.0,
                  fix_versions=["v1", "v2"], program="telemetry",
                  first_in_progress=date(2026, 7, 10),
                  links=[Link("Blocks", "inward", "X-1"),
                         Link("Blocks", "outward", "Y-1")])
    orphan = _task("T-2")
    external = _task("X-1", external=True)
    b = make_bundle(issues=[epic, child, orphan, external])
    spec = issues_sheet(b, assemble(b))
    assert spec.sheet == "issues"
    rows = {r.key: r for r in spec.rows}
    assert "X-1" not in rows                      # externals excluded
    assert rows["T-1"].parent_key == "E-1"        # indented under epic
    assert rows["E-1"].parent_key is None
    assert rows["T-2"].parent_key is None
    cells = rows["T-1"].cells
    assert cells["Fix Versions"] == "v1, v2"
    assert cells["Sprint"] == "S1"
    assert cells["Blocked By"] == "X-1"
    assert cells["Blocks"] == "Y-1"
    assert cells["In Progress"] == "2026-07-10"
    assert cells["Done"] is None
    assert cells["In Jira"] is True
    assert cells["Remaining Est"] == 2.0
    # epics come before their children
    keys = [r.key for r in spec.rows]
    assert keys.index("E-1") < keys.index("T-1")


def test_issues_sheet_hygiene_column(make_bundle):
    b = make_bundle(issues=[_task("T-1")],
                    hygiene_memberships={"orphan-task": ["T-1"]})
    rules = [Rule(name="orphan-task", severity="yellow", message="No epic",
                  jql="issuetype != Bug AND parent is EMPTY")]
    spec = issues_sheet(b, assemble(b, rules=rules))
    row = next(r for r in spec.rows if r.key == "T-1")
    assert row.cells["Hygiene"] == "yellow:orphan-task"


def test_issues_sheet_epic_rows_carry_rollups(make_bundle):
    from datetime import date as _date
    from tentpole.model import FixVersion
    epic = Issue(key="E-1", summary="Epic one", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v9"],
                 program="telemetry")
    b = make_bundle(
        fix_versions=[FixVersion("v9", release_date=_date(2026, 8, 1))],
        issues=[
            epic,
            _task("T-1", epic_key="E-1", assignee="ada",
                  remaining_estimate_days=60.0, sprint_id=1),
            _task("T-2", epic_key="E-1", assignee="grace",
                  remaining_estimate_days=4.0, sprint_id=2),
            _task("T-3", epic_key="E-1", status_category="done",
                  remaining_estimate_days=9.0),
        ])
    spec = issues_sheet(b, assemble(b))
    rows = {r.key: r for r in spec.rows}
    e = rows["E-1"].cells
    assert e["Open Tickets"] == 2
    assert e["Remaining Days"] == 64.0
    assert e["People"] == "ada, grace"
    assert e["Deadline"] == "2026-08-01"
    assert e["Runway"] == "AT RISK"
    # ticket rows leave the rollups blank
    t = rows["T-1"].cells
    assert t["Open Tickets"] is None
    assert t["Remaining Days"] is None
    assert t["People"] is None
    assert t["Deadline"] is None
    assert t["Runway"] == ""
    # ticket-level Remaining Est is unaffected by the rollup
    assert t["Remaining Est"] == 60.0


def test_issues_sheet_first_planned_from_snapshots(make_bundle):
    prior = [
        {"run": "2026-03-01", "key": "T-1", "sprint_id": None},  # not planned
        {"run": "2026-04-01", "key": "T-1", "sprint_id": 2},     # earliest planned
        {"run": "2026-05-01", "key": "T-1", "sprint_id": 2},
        {"run": "2026-04-01", "key": "T-9", "sprint_id": 1},     # not in bundle
    ]
    b = make_bundle(issues=[_task("T-1", sprint_id=1),
                            _task("T-2", sprint_id=1)])   # T-2 has no history
    spec = issues_sheet(b, assemble(b), prior_snapshots=prior)
    rows = {r.key: r for r in spec.rows}
    assert rows["T-1"].cells["First Planned"] == "2026-04-01"
    assert rows["T-2"].cells["First Planned"] is None
