from datetime import date

from tentpole.diagnostics import assemble
from tentpole.model import FixVersion, Issue
from tentpole.sheets import fixversions_sheet


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


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
