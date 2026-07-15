from datetime import date

from tentpole.diagnostics import assemble
from tentpole.model import Issue, Link
from tentpole.sheets import (
    accuracy_sheet, build_sheetspecs, capacity_sheet, dependencies_sheet,
)


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


def test_dependencies_sheet_edges(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", links=[Link("Blocks", "inward", "X-1")]),
        _task("T-2", links=[Link("Blocks", "outward", "X-2")]),
        _task("T-3", links=[Link("Blocks", "inward", "T-1")]),  # internal: skip
        _task("X-1", external=True, status_category="in_progress",
              sprint_id=3),
    ])
    spec = dependencies_sheet(b)
    rows = {r.key: r for r in spec.rows}
    assert set(rows) == {"T-1<-X-1", "T-2->X-2"}
    edge = rows["T-1<-X-1"].cells
    assert edge["Their Status"] == "in_progress"
    assert edge["Direction"] == "blocked by"
    missing = rows["T-2->X-2"].cells
    assert missing["Their Status"] == "unknown"


def test_capacity_sheet_rows(make_bundle):
    b = make_bundle(issues=[_task("T-1", assignee="ada", sprint_id=1,
                                  remaining_estimate_days=12.0)])
    spec = capacity_sheet(assemble(b))
    row = next(r for r in spec.rows if r.key == "ada|sprint:1")
    assert row.cells["Overloaded"] is True
    assert row.cells["Load"] == 12.0


def test_accuracy_sheet_rows(make_bundle):
    done = _task("T-1", assignee="ada", status_category="done",
                 original_estimate_days=4.0, program="telemetry",
                 first_in_progress=date(2026, 6, 1),
                 done_at=date(2026, 6, 8))
    no_dates = _task("T-2", status_category="done",
                     original_estimate_days=3.0)
    b = make_bundle(issues=[done, no_dates])
    spec = accuracy_sheet(b)
    assert [r.key for r in spec.rows] == ["T-1"]
    cells = spec.rows[0].cells
    assert cells["Cycle Days"] == 8
    assert cells["Ratio"] == 2.0
    assert cells["Done"] == "2026-06-08"


def test_build_sheetspecs_covers_machine_sheets(make_bundle):
    b = make_bundle(issues=[_task("T-1")])
    specs = build_sheetspecs(b, assemble(b))
    assert set(specs) == {"issues", "fixversions", "dependencies",
                          "capacity", "accuracy"}
    assert all(specs[k].sheet == k for k in specs)
