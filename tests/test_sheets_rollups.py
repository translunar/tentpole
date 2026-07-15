from datetime import date

from tentpole.diagnostics import assemble
from tentpole.model import FixVersion, Issue
from tentpole.sheets import epics_sheet, fixversions_sheet, issues_sheet


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


def test_epics_sheet_rollup(make_bundle):
    epic = Issue(key="E-1", summary="Epic one", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v9"],
                 program="telemetry")
    b = make_bundle(
        fix_versions=[FixVersion("v9", release_date=date(2026, 8, 1))],
        issues=[
            epic,
            _task("T-1", epic_key="E-1", assignee="ada",
                  remaining_estimate_days=60.0, sprint_id=1),
            _task("T-2", epic_key="E-1", assignee="grace",
                  remaining_estimate_days=4.0, sprint_id=2),
            _task("T-3", epic_key="E-1", status_category="done",
                  remaining_estimate_days=9.0),
        ])
    spec = epics_sheet(b, assemble(b))
    assert spec.sheet == "epics"
    row = next(r for r in spec.rows if r.key == "E-1")
    assert row.cells["Open Tickets"] == 2
    assert row.cells["Remaining Days"] == 64.0
    assert row.cells["People"] == "ada, grace"
    assert row.cells["Deadline"] == "2026-08-01"
    assert row.cells["Runway"] == "AT RISK"   # 64d >> runway before 08-01


def test_fixversions_sheet_rollup(make_bundle):
    fv = FixVersion("v1", release_date=date(2026, 8, 1))
    b = make_bundle(fix_versions=[fv], issues=[
        _task("T-1", fix_versions=["v1"], assignee="ada",
              remaining_estimate_days=3.0, sprint_id=1),
        _task("T-2", fix_versions=["v1"], assignee="ada",
              remaining_estimate_days=2.0, sprint_id=4),   # past deadline
        _task("T-3", fix_versions=["v1"], status_category="done"),
    ])
    spec = fixversions_sheet(b, assemble(b))
    row = next(r for r in spec.rows if r.key == "v1")
    assert row.cells["Open Tickets"] == 2
    assert row.cells["Remaining Days"] == 5.0
    assert row.cells["Remaining By Person"] == "ada: 5.0"
    assert row.cells["Released"] is False
    assert row.cells["Risk"] == "AT RISK"


def test_issue_epic_rollups_equal_retired_epics_builder(make_bundle):
    # TRANSITIONAL equivalence pin (spec §5, §11): the merged epic-row
    # rollups must equal the old epics_sheet builder's output for the same
    # bundle. Removed in Task 2 with the builder.
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
            _task("T-3", epic_key="E-1", status_category="done"),
        ])
    diag = assemble(b)
    old = {r.key: r.cells for r in epics_sheet(b, diag).rows}["E-1"]
    new = {r.key: r.cells for r in issues_sheet(b, diag).rows}["E-1"]
    for col in ["Deadline", "Open Tickets", "Remaining Days", "People",
                "Runway"]:
        assert new[col] == old[col], col
