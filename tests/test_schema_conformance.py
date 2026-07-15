"""FIX 5: guard against schema/sheet-builder drift. Each machine sheet
builder in sheets.py must emit a cells dict whose keys match the columns
of the corresponding schema in schema.py exactly. Nothing else enforces
this: plan_changes's `if c in synced` filter would silently drop a cell
if a column got renamed in one file and not the other, with zero test
failures elsewhere."""
from __future__ import annotations

from datetime import date

from tentpole.diagnostics import assemble
from tentpole.model import FixVersion, Issue, Link
from tentpole.schema import SCHEMAS
from tentpole.sheets import build_sheetspecs


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    kw.setdefault("status_category", base.pop("status_category"))
    base.update(kw)
    return Issue(key=key, **base)


def test_all_machine_sheet_rows_match_their_schema_columns(make_bundle):
    epic = Issue(key="E-1", summary="Epic one", issue_type="Epic",
                status_category="in_progress")
    child = _task("T-1", assignee="ada", sprint_id=1, epic_key="E-1",
                  remaining_estimate_days=2.0,
                  links=[Link("Blocks", "inward", "X-1")])
    external = _task("X-1", external=True, status_category="in_progress",
                     sprint_id=3)
    done = _task("T-2", assignee="grace", status_category="done",
                original_estimate_days=4.0,
                first_in_progress=date(2026, 6, 1),
                done_at=date(2026, 6, 8))
    bundle = make_bundle(
        issues=[epic, child, external, done],
        fix_versions=[FixVersion("v1", release_date=date(2026, 8, 1))],
    )
    diag = assemble(bundle)
    specs = build_sheetspecs(bundle, diag)

    assert set(specs) == {"issues", "fixversions", "dependencies",
                          "capacity", "accuracy"}

    for name, spec in specs.items():
        schema = SCHEMAS[name]
        expected = set(schema.column_names(gantt=False))
        assert spec.rows, f"{name} sheet produced no rows to check"
        for row in spec.rows:
            assert set(row.cells) == expected, (
                f"{name} row '{row.key}' cell names {set(row.cells)} "
                f"do not match schema columns {expected}")
