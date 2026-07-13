# Sheet Layer (Plan 2 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The sheet layer of `tentpole`: declarative sheet schemas, SheetSpec builders for all six machine-owned mirrors, a change-planning diff engine that can never touch human-owned data, append-only snapshots, human-sheet read-back parsing, a run report, and a `tentpole sync` CLI orchestrating bundle → outputs.

**Architecture:** Everything stays pure (spec §3): `run_sync(bundle, rules, current_states)` returns a `SyncResult`; only `cli.py` reads/writes files. "Load" in this plan means *emitting change-plan JSON files* — executing them against real Smartsheet is Plan 3's adapter work. Sheet cells are JSON-safe primitives only, so specs diff cleanly against JSON state files.

**Tech Stack:** Python ≥3.12 on the existing Plan 1 core (model/buckets/demand/throughput/checks/hygiene/diagnostics). No new dependencies.

## Global Constraints

- Everything from Plan 1 still binds: Python ≥3.12; runtime dep `pyyaml>=6` only; src layout; severities exactly "red"/"yellow"; bucket ids exactly `"sprint:<id>"`, `"plan+1"`, `"plan+2"`, `"beyond"`, `"unscheduled"`; no clock reads — "today" is `bundle.as_of`.
- I/O locations are exactly: `model.load_bundle`, `hygiene.load_rules`, and `cli.py`. Every new module in this plan is pure.
- **Cell values are JSON-safe primitives only**: `str | float | int | bool | None`. Dates render as ISO `YYYY-MM-DD` strings inside cells. Never put `date`/dataclass objects in a `Row.cells` dict.
- Sheet registry keys (and `SheetSchema.name`) are exactly: `"issues"`, `"epics"`, `"fixversions"`, `"dependencies"`, `"capacity"`, `"accuracy"` (machine-owned) and `"future_work"`, `"exceptions"` (human-owned).
- Change ops are exactly: `"add"`, `"update"`, `"remove"`, `"flag_gone"`.
- The change planner MUST refuse (raise `ValueError`) to plan changes for a human-owned schema — this is the "sync never writes human sheets" guarantee (spec §7).
- Run tests with `.venv/bin/pytest` from the repo root.
- Commit after every task; imperative mood, `feat:`/`test:`/`chore:`/`fix:` prefixes.

---

### Task 1: Sheet schemas + `render_schemas`

**Files:**
- Create: `src/tentpole/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing new (pure declarations).
- Produces: `ColumnDef(name: str, type: str = "TEXT", primary: bool = False, synced: bool = True)` (frozen; type ∈ TEXT/NUMBER/DATE/CHECKBOX); `SheetSchema(name: str, owned: str, columns: tuple[ColumnDef, ...])` (frozen; owned ∈ "machine"/"human") with methods `primary_column() -> ColumnDef` and `synced_names() -> list[str]`; `SCHEMAS: dict[str, SheetSchema]` with the eight keys from Global Constraints; `render_schemas() -> str` (human-readable listing used by `schema show` for manual sheet creation, spec §7 provisioning).

- [ ] **Step 1: Write the failing tests**

`tests/test_schema.py`:

```python
from tentpole.schema import SCHEMAS, render_schemas


def test_registry_has_all_sheets_with_ownership():
    assert set(SCHEMAS) == {"issues", "epics", "fixversions", "dependencies",
                            "capacity", "accuracy", "future_work", "exceptions"}
    assert SCHEMAS["issues"].owned == "machine"
    assert SCHEMAS["future_work"].owned == "human"
    assert SCHEMAS["exceptions"].owned == "human"


def test_every_schema_has_exactly_one_primary():
    for schema in SCHEMAS.values():
        primaries = [c for c in schema.columns if c.primary]
        assert len(primaries) == 1, schema.name
        assert schema.primary_column() is primaries[0]


def test_human_sheets_have_no_synced_columns():
    assert SCHEMAS["future_work"].synced_names() == []
    assert SCHEMAS["exceptions"].synced_names() == []
    assert "Key" in SCHEMAS["issues"].synced_names()


def test_render_schemas_lists_every_sheet_and_column():
    text = render_schemas()
    for schema in SCHEMAS.values():
        assert schema.name in text
        for col in schema.columns:
            assert col.name in text
    assert "human" in text and "machine" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.schema'`.

- [ ] **Step 3: Implement `src/tentpole/schema.py`**

```python
"""Declarative sheet schemas (spec section 7). One source of truth for
sheet shape: change planning validates against these; `schema show`
renders them for manual sheet creation; Plan 3's bootstrap will create
sheets from them."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str = "TEXT"      # TEXT | NUMBER | DATE | CHECKBOX
    primary: bool = False
    synced: bool = True     # False = human-owned; the sync never writes it


@dataclass(frozen=True)
class SheetSchema:
    name: str
    owned: str              # "machine" | "human"
    columns: tuple[ColumnDef, ...]

    def primary_column(self) -> ColumnDef:
        return next(c for c in self.columns if c.primary)

    def synced_names(self) -> list[str]:
        return [c.name for c in self.columns if c.synced]


def _human(name: str, *cols: ColumnDef) -> SheetSchema:
    unsynced = tuple(
        ColumnDef(c.name, c.type, c.primary, synced=False) for c in cols)
    return SheetSchema(name, "human", unsynced)


SCHEMAS: dict[str, SheetSchema] = {
    "issues": SheetSchema("issues", "machine", (
        ColumnDef("Key", primary=True),
        ColumnDef("Summary"), ColumnDef("Type"), ColumnDef("Status"),
        ColumnDef("Assignee"),
        ColumnDef("Original Est", "NUMBER"),
        ColumnDef("Remaining Est", "NUMBER"),
        ColumnDef("Epic"), ColumnDef("Fix Versions"), ColumnDef("Sprint"),
        ColumnDef("Program"), ColumnDef("Blocked By"), ColumnDef("Blocks"),
        ColumnDef("Hygiene"),
        ColumnDef("In Progress", "DATE"), ColumnDef("Done", "DATE"),
        ColumnDef("In Jira", "CHECKBOX"),
    )),
    "epics": SheetSchema("epics", "machine", (
        ColumnDef("Epic", primary=True),
        ColumnDef("Summary"), ColumnDef("Program"),
        ColumnDef("Deadline", "DATE"),
        ColumnDef("Open Tickets", "NUMBER"),
        ColumnDef("Remaining Days", "NUMBER"),
        ColumnDef("People"), ColumnDef("Runway"),
    )),
    "fixversions": SheetSchema("fixversions", "machine", (
        ColumnDef("Version", primary=True),
        ColumnDef("Release Date", "DATE"),
        ColumnDef("Released", "CHECKBOX"),
        ColumnDef("Open Tickets", "NUMBER"),
        ColumnDef("Remaining Days", "NUMBER"),
        ColumnDef("Remaining By Person"), ColumnDef("Risk"),
    )),
    "dependencies": SheetSchema("dependencies", "machine", (
        ColumnDef("Edge", primary=True),
        ColumnDef("Our Issue"), ColumnDef("Direction"),
        ColumnDef("Their Issue"), ColumnDef("Their Status"),
        ColumnDef("Their Sprint"),
    )),
    "capacity": SheetSchema("capacity", "machine", (
        ColumnDef("Cell", primary=True),
        ColumnDef("Person"), ColumnDef("Bucket"),
        ColumnDef("Load", "NUMBER"), ColumnDef("Capacity", "NUMBER"),
        ColumnDef("Overloaded", "CHECKBOX"),
    )),
    "accuracy": SheetSchema("accuracy", "machine", (
        ColumnDef("Key", primary=True),
        ColumnDef("Assignee"), ColumnDef("Program"),
        ColumnDef("Original Est", "NUMBER"),
        ColumnDef("Cycle Days", "NUMBER"), ColumnDef("Ratio", "NUMBER"),
        ColumnDef("Done", "DATE"),
    )),
    "future_work": _human(
        "future_work",
        ColumnDef("Title", primary=True),
        ColumnDef("Program"), ColumnDef("Owner"),
        ColumnDef("Estimate Days", "NUMBER"),
        ColumnDef("Target"), ColumnDef("Intended Epic"),
        ColumnDef("Jira Key"),
    ),
    "exceptions": _human(
        "exceptions",
        ColumnDef("Cell", primary=True),
        ColumnDef("Person"), ColumnDef("Sprint", "NUMBER"),
        ColumnDef("Day Cost", "NUMBER"),
    ),
}


def render_schemas() -> str:
    lines = ["tentpole sheet schemas", "======================", ""]
    for schema in SCHEMAS.values():
        lines.append(f"{schema.name}  ({schema.owned}-owned)")
        for col in schema.columns:
            marks = []
            if col.primary:
                marks.append("primary")
            if not col.synced:
                marks.append("human-edited")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            lines.append(f"  - {col.name}: {col.type}{suffix}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/schema.py tests/test_schema.py
git commit -m "feat: declarative sheet schemas with render for manual creation"
```

---

### Task 2: SheetSpec model + issues mirror builder

**Files:**
- Create: `src/tentpole/sheets.py`
- Test: `tests/test_sheets_issues.py`

**Interfaces:**
- Consumes: `Bundle`/`Issue` (model), `diag` dict from `diagnostics.assemble` (uses `diag["hygiene"]`: list of `Flag(rule, severity, key, message)`).
- Produces: `Row(key: str, cells: dict, parent_key: str | None = None)` (plain dataclass); `SheetSpec(sheet: str, rows: list[Row])` (plain dataclass); `issues_sheet(bundle, diag) -> SheetSpec`. Cells: JSON-safe primitives; dates as ISO strings; column names exactly as in the `issues` schema (Task 1).

- [ ] **Step 1: Write the failing tests**

`tests/test_sheets_issues.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sheets_issues.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.sheets'`.

- [ ] **Step 3: Implement `src/tentpole/sheets.py`**

```python
"""SheetSpec builders: bundle + diagnostics -> desired mirror-sheet contents
(spec section 7). Cells are JSON-safe primitives; dates are ISO strings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tentpole.model import Bundle, Issue


@dataclass
class Row:
    key: str
    cells: dict
    parent_key: str | None = None


@dataclass
class SheetSpec:
    sheet: str
    rows: list[Row]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _links(issue: Issue, direction: str) -> str:
    return ", ".join(sorted(
        l.other_key for l in issue.links
        if l.type == "Blocks" and l.direction == direction))


def issues_sheet(bundle: Bundle, diag: dict) -> SheetSpec:
    hygiene: dict[str, list[str]] = {}
    for fl in diag["hygiene"]:
        hygiene.setdefault(fl.key, []).append(f"{fl.severity}:{fl.rule}")
    sprint_names = {s.id: s.name for s in bundle.sprints}

    def cells_for(issue: Issue) -> dict:
        return {
            "Key": issue.key,
            "Summary": issue.summary,
            "Type": issue.issue_type,
            "Status": issue.status_category,
            "Assignee": issue.assignee,
            "Original Est": issue.original_estimate_days,
            "Remaining Est": issue.remaining_estimate_days,
            "Epic": issue.epic_key,
            "Fix Versions": ", ".join(issue.fix_versions),
            "Sprint": sprint_names.get(issue.sprint_id),
            "Program": issue.program,
            "Blocked By": _links(issue, "inward"),
            "Blocks": _links(issue, "outward"),
            "Hygiene": "; ".join(sorted(hygiene.get(issue.key, []))),
            "In Progress": _iso(issue.first_in_progress),
            "Done": _iso(issue.done_at),
            "In Jira": True,
        }

    ours = [i for i in bundle.issues if not i.external]
    epics = sorted((i for i in ours if i.issue_type == "Epic"),
                   key=lambda i: i.key)
    epic_keys = {e.key for e in epics}
    non_epics = sorted((i for i in ours if i.issue_type != "Epic"),
                       key=lambda i: i.key)
    rows: list[Row] = []
    for epic in epics:
        rows.append(Row(epic.key, cells_for(epic)))
        rows.extend(Row(i.key, cells_for(i), parent_key=epic.key)
                    for i in non_epics if i.epic_key == epic.key)
    rows.extend(Row(i.key, cells_for(i)) for i in non_epics
                if i.epic_key not in epic_keys)
    return SheetSpec("issues", rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sheets_issues.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/sheets.py tests/test_sheets_issues.py
git commit -m "feat: issues mirror sheet builder with epic hierarchy"
```

---

### Task 3: Epics and fixVersions rollup builders

**Files:**
- Modify: `src/tentpole/sheets.py` (append two functions + imports)
- Test: `tests/test_sheets_rollups.py`

**Interfaces:**
- Consumes: Task 2 `Row`/`SheetSpec`/`_iso`; `effective_deadline` (buckets), `estimate_of`, `is_overhead` (demand); `diag["findings"]` (list of `Finding(check, severity, subject, bucket_id, message)`).
- Produces: `epics_sheet(bundle, diag) -> SheetSpec` (sheet="epics"; Runway cell = "AT RISK" iff a `tentpole_runway` finding has subject == epic key, else ""); `fixversions_sheet(bundle, diag) -> SheetSpec` (sheet="fixversions"; Risk cell = "AT RISK" iff any `deadline_risk` finding has subject == version name, else "").

- [ ] **Step 1: Write the failing tests**

`tests/test_sheets_rollups.py`:

```python
from datetime import date

from tentpole.diagnostics import assemble
from tentpole.model import FixVersion, Issue
from tentpole.sheets import epics_sheet, fixversions_sheet


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sheets_rollups.py -v`
Expected: FAIL with `ImportError: cannot import name 'epics_sheet'`.

- [ ] **Step 3: Append to `src/tentpole/sheets.py`**

Add imports at top (merge with existing):

```python
from tentpole.buckets import effective_deadline
from tentpole.demand import estimate_of, is_overhead
```

Append:

```python
def _open_work(bundle: Bundle) -> list[Issue]:
    return [i for i in bundle.issues
            if not i.external and i.issue_type != "Epic"
            and i.status_category != "done"
            and not is_overhead(i, bundle.config)]


def epics_sheet(bundle: Bundle, diag: dict) -> SheetSpec:
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "tentpole_runway"}
    open_work = _open_work(bundle)
    rows = []
    for epic in sorted((i for i in bundle.issues
                        if i.issue_type == "Epic" and not i.external),
                       key=lambda i: i.key):
        children = [i for i in open_work if i.epic_key == epic.key]
        rows.append(Row(epic.key, {
            "Epic": epic.key,
            "Summary": epic.summary,
            "Program": epic.program,
            "Deadline": _iso(effective_deadline(epic, bundle)),
            "Open Tickets": len(children),
            "Remaining Days": sum(estimate_of(i) for i in children),
            "People": ", ".join(sorted({i.assignee for i in children
                                        if i.assignee})),
            "Runway": "AT RISK" if epic.key in at_risk else "",
        }))
    return SheetSpec("epics", rows)


def fixversions_sheet(bundle: Bundle, diag: dict) -> SheetSpec:
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "deadline_risk"}
    open_work = _open_work(bundle)
    rows = []
    for fv in sorted(bundle.fix_versions, key=lambda f: f.name):
        mine = [i for i in open_work if fv.name in i.fix_versions]
        by_person: dict[str, float] = {}
        for i in mine:
            who = i.assignee or "unassigned"
            by_person[who] = by_person.get(who, 0.0) + estimate_of(i)
        rows.append(Row(fv.name, {
            "Version": fv.name,
            "Release Date": _iso(fv.release_date),
            "Released": fv.released,
            "Open Tickets": len(mine),
            "Remaining Days": sum(estimate_of(i) for i in mine),
            "Remaining By Person": "; ".join(
                f"{p}: {d}" for p, d in sorted(by_person.items())),
            "Risk": "AT RISK" if fv.name in at_risk else "",
        }))
    return SheetSpec("fixversions", rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sheets_rollups.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/sheets.py tests/test_sheets_rollups.py
git commit -m "feat: epics and fixversions rollup sheet builders"
```

---

### Task 4: Dependencies, capacity, accuracy builders + `build_sheetspecs`

**Files:**
- Modify: `src/tentpole/sheets.py` (append four functions)
- Test: `tests/test_sheets_rest.py`

**Interfaces:**
- Consumes: Tasks 2-3 internals; `diag["capacity"]` rows (`{"person","bucket_id","load","capacity"}`).
- Produces: `dependencies_sheet(bundle) -> SheetSpec` (edge key `"<our>-><their>"` for outward, `"<our><-<their>"` for inward; one row per Blocks link on our non-external issues whose other side is external or absent); `capacity_sheet(diag) -> SheetSpec` (key `"<person>|<bucket_id>"`); `accuracy_sheet(bundle) -> SheetSpec` (one row per done, non-external, non-Epic, non-overhead issue having original estimate > 0, first_in_progress, and done_at; Cycle Days = (done − first_in_progress).days + 1; Ratio = round(cycle/original, 2)); `build_sheetspecs(bundle, diag) -> dict[str, SheetSpec]` with exactly the six machine sheet keys.

- [ ] **Step 1: Write the failing tests**

`tests/test_sheets_rest.py`:

```python
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
    assert set(specs) == {"issues", "epics", "fixversions", "dependencies",
                          "capacity", "accuracy"}
    assert all(specs[k].sheet == k for k in specs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sheets_rest.py -v`
Expected: FAIL with `ImportError: cannot import name 'accuracy_sheet'`.

- [ ] **Step 3: Append to `src/tentpole/sheets.py`**

```python
def dependencies_sheet(bundle: Bundle) -> SheetSpec:
    internal = {i.key for i in bundle.issues if not i.external}
    rows = []
    for issue in sorted(bundle.issues, key=lambda i: i.key):
        if issue.external:
            continue
        for link in issue.links:
            if link.type != "Blocks" or link.other_key in internal:
                continue
            other = bundle.issue(link.other_key)
            inward = link.direction == "inward"
            key = (f"{issue.key}<-{link.other_key}" if inward
                   else f"{issue.key}->{link.other_key}")
            rows.append(Row(key, {
                "Edge": key,
                "Our Issue": issue.key,
                "Direction": "blocked by" if inward else "blocks",
                "Their Issue": link.other_key,
                "Their Status": other.status_category if other else "unknown",
                "Their Sprint": (str(other.sprint_id)
                                 if other and other.sprint_id else None),
            }))
    return SheetSpec("dependencies", rows)


def capacity_sheet(diag: dict) -> SheetSpec:
    rows = []
    for r in diag["capacity"]:
        key = f"{r['person']}|{r['bucket_id']}"
        rows.append(Row(key, {
            "Cell": key,
            "Person": r["person"],
            "Bucket": r["bucket_id"],
            "Load": r["load"],
            "Capacity": r["capacity"],
            "Overloaded": r["load"] > r["capacity"],
        }))
    return SheetSpec("capacity", rows)


def accuracy_sheet(bundle: Bundle) -> SheetSpec:
    rows = []
    for issue in sorted(bundle.issues, key=lambda i: i.key):
        if (issue.external or issue.issue_type == "Epic"
                or issue.status_category != "done"
                or is_overhead(issue, bundle.config)
                or not issue.original_estimate_days
                or not issue.first_in_progress or not issue.done_at):
            continue
        cycle = (issue.done_at - issue.first_in_progress).days + 1
        rows.append(Row(issue.key, {
            "Key": issue.key,
            "Assignee": issue.assignee,
            "Program": issue.program,
            "Original Est": issue.original_estimate_days,
            "Cycle Days": cycle,
            "Ratio": round(cycle / issue.original_estimate_days, 2),
            "Done": _iso(issue.done_at),
        }))
    return SheetSpec("accuracy", rows)


def build_sheetspecs(bundle: Bundle, diag: dict) -> dict[str, SheetSpec]:
    return {
        "issues": issues_sheet(bundle, diag),
        "epics": epics_sheet(bundle, diag),
        "fixversions": fixversions_sheet(bundle, diag),
        "dependencies": dependencies_sheet(bundle),
        "capacity": capacity_sheet(diag),
        "accuracy": accuracy_sheet(bundle),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sheets_rest.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/sheets.py tests/test_sheets_rest.py
git commit -m "feat: dependencies, capacity, accuracy builders and build_sheetspecs"
```

---

### Task 5: Change planning

**Files:**
- Create: `src/tentpole/changeplan.py`
- Test: `tests/test_changeplan.py`

**Interfaces:**
- Consumes: Task 2 `Row`/`SheetSpec`; Task 1 `SheetSchema`/`SCHEMAS`.
- Produces: `Change(op: str, key: str, cells: dict | None = None, parent_key: str | None = None)` (frozen is NOT possible with dict — plain dataclass); `plan_changes(spec: SheetSpec, current: dict[str, dict], schema: SheetSchema) -> list[Change]`. `current` maps primary-key value → {column: value} (what the state file holds). Semantics: add (key absent), update (only changed synced columns in cells), remove (key gone; non-issues sheets), flag_gone (issues sheet: cells exactly `{"In Jira": False}`, skipped if already False). Raises `ValueError` for a human-owned schema.

- [ ] **Step 1: Write the failing tests**

`tests/test_changeplan.py`:

```python
import pytest

from tentpole.changeplan import plan_changes
from tentpole.schema import SCHEMAS
from tentpole.sheets import Row, SheetSpec


def _spec(*rows):
    return SheetSpec("issues", list(rows))


def _row(key, **cells):
    cells.setdefault("Key", key)
    cells.setdefault("In Jira", True)
    return Row(key, cells)


def test_adds_updates_and_flag_gone():
    spec = _spec(_row("T-1", Summary="new title", Status="todo"),
                 _row("T-2", Summary="brand new", Status="todo"))
    current = {
        "T-1": {"Key": "T-1", "Summary": "old title", "Status": "todo",
                "In Jira": True},
        "T-9": {"Key": "T-9", "Summary": "vanished", "In Jira": True},
    }
    changes = {(c.op, c.key): c for c in
               plan_changes(spec, current, SCHEMAS["issues"])}
    assert set(changes) == {("update", "T-1"), ("add", "T-2"),
                            ("flag_gone", "T-9")}
    assert changes[("update", "T-1")].cells == {"Summary": "new title"}
    assert changes[("add", "T-2")].cells["Summary"] == "brand new"
    assert changes[("flag_gone", "T-9")].cells == {"In Jira": False}


def test_no_changes_when_state_matches():
    spec = _spec(_row("T-1", Summary="same", Status="todo"))
    current = {"T-1": {"Key": "T-1", "Summary": "same", "Status": "todo",
                       "In Jira": True}}
    assert plan_changes(spec, current, SCHEMAS["issues"]) == []


def test_already_flagged_gone_not_reflagged():
    spec = _spec()
    current = {"T-9": {"Key": "T-9", "In Jira": False}}
    assert plan_changes(spec, current, SCHEMAS["issues"]) == []


def test_non_issues_sheet_removes_instead_of_flagging():
    spec = SheetSpec("capacity", [])
    current = {"ada|sprint:1": {"Cell": "ada|sprint:1", "Load": 1.0}}
    changes = plan_changes(spec, current, SCHEMAS["capacity"])
    assert [(c.op, c.key) for c in changes] == [("remove", "ada|sprint:1")]


def test_refuses_human_owned_sheets():
    with pytest.raises(ValueError, match="human"):
        plan_changes(SheetSpec("future_work", []), {},
                     SCHEMAS["future_work"])


def test_update_ignores_unsynced_columns():
    spec = _spec(_row("T-1", Summary="same"))
    # a human somehow added a note under an unknown column in state:
    current = {"T-1": {"Key": "T-1", "Summary": "same", "In Jira": True,
                       "My Notes": "human scribble"}}
    assert plan_changes(spec, current, SCHEMAS["issues"]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_changeplan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.changeplan'`.

- [ ] **Step 3: Implement `src/tentpole/changeplan.py`**

```python
"""Diff a SheetSpec against current sheet state into an explicit change
plan (spec section 3: the sync never blind-rewrites, never touches
human-owned data; section 8: deletions are soft on the issues sheet)."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.schema import SheetSchema
from tentpole.sheets import SheetSpec


@dataclass
class Change:
    op: str                        # "add" | "update" | "remove" | "flag_gone"
    key: str
    cells: dict | None = None
    parent_key: str | None = None


def plan_changes(spec: SheetSpec, current: dict[str, dict],
                 schema: SheetSchema) -> list[Change]:
    if schema.owned != "machine":
        raise ValueError(
            f"refusing to plan changes for human-owned sheet "
            f"'{schema.name}'")
    synced = set(schema.synced_names())
    changes: list[Change] = []
    spec_keys = set()
    for row in spec.rows:
        spec_keys.add(row.key)
        cells = {c: v for c, v in row.cells.items() if c in synced}
        existing = current.get(row.key)
        if existing is None:
            changes.append(Change("add", row.key, cells, row.parent_key))
            continue
        changed = {c: v for c, v in cells.items() if existing.get(c) != v}
        if changed:
            changes.append(Change("update", row.key, changed))
    for key in sorted(set(current) - spec_keys):
        if schema.name == "issues":
            if current[key].get("In Jira") is not False:
                changes.append(Change("flag_gone", key, {"In Jira": False}))
        else:
            changes.append(Change("remove", key))
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_changeplan.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/changeplan.py tests/test_changeplan.py
git commit -m "feat: change planning with human-sheet refusal and soft deletes"
```

---

### Task 6: Snapshots

**Files:**
- Create: `src/tentpole/snapshots.py`
- Test: `tests/test_snapshots.py`

**Interfaces:**
- Consumes: `Bundle`/`Issue` (model).
- Produces: `snapshot_records(bundle) -> list[dict]` (one per non-external, non-Epic issue: keys exactly `run`, `key`, `status`, `sprint_id`, `assignee`, `original`, `remaining`; `run` = ISO as_of); `to_jsonl(records: list[dict]) -> str` (one JSON object per line, trailing newline when non-empty); `parse_jsonl(text: str) -> list[dict]` (tolerates blank lines).

- [ ] **Step 1: Write the failing tests**

`tests/test_snapshots.py`:

```python
from tentpole.model import Issue
from tentpole.snapshots import parse_jsonl, snapshot_records, to_jsonl


def test_snapshot_records_shape(make_bundle):
    b = make_bundle(issues=[
        Issue(key="T-1", summary="t", issue_type="Task",
              status_category="in_progress", assignee="ada", sprint_id=2,
              original_estimate_days=5.0, remaining_estimate_days=3.0),
        Issue(key="E-1", summary="e", issue_type="Epic",
              status_category="todo"),
        Issue(key="X-1", summary="x", issue_type="Task",
              status_category="todo", external=True),
    ])
    records = snapshot_records(b)
    assert records == [{
        "run": "2026-07-12", "key": "T-1", "status": "in_progress",
        "sprint_id": 2, "assignee": "ada", "original": 5.0,
        "remaining": 3.0,
    }]


def test_jsonl_round_trip():
    records = [{"run": "2026-07-12", "key": "T-1"},
               {"run": "2026-07-12", "key": "T-2"}]
    text = to_jsonl(records)
    assert text.endswith("\n") and text.count("\n") == 2
    assert parse_jsonl(text + "\n\n") == records
    assert to_jsonl([]) == ""
    assert parse_jsonl("") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_snapshots.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.snapshots'`.

- [ ] **Step 3: Implement `src/tentpole/snapshots.py`**

```python
"""Append-only snapshot records (spec section 6): the longitudinal substrate
for estimation learning. Stored as JSONL by the CLI; this module only
builds/serializes records (pure)."""
from __future__ import annotations

import json

from tentpole.model import Bundle


def snapshot_records(bundle: Bundle) -> list[dict]:
    return [
        {
            "run": bundle.as_of.isoformat(),
            "key": issue.key,
            "status": issue.status_category,
            "sprint_id": issue.sprint_id,
            "assignee": issue.assignee,
            "original": issue.original_estimate_days,
            "remaining": issue.remaining_estimate_days,
        }
        for issue in bundle.issues
        if not issue.external and issue.issue_type != "Epic"
    ]


def to_jsonl(records: list[dict]) -> str:
    if not records:
        return ""
    return "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n"


def parse_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_snapshots.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/snapshots.py tests/test_snapshots.py
git commit -m "feat: append-only snapshot records with JSONL serialization"
```

---

### Task 7: Human-sheet read-back parsing

**Files:**
- Create: `src/tentpole/humansheets.py`
- Test: `tests/test_humansheets.py`

**Interfaces:**
- Consumes: `Ghost`, `ExceptionRow` (model).
- Produces: `ghosts_from_sheet(rows: dict[str, dict]) -> list[Ghost]` and `exceptions_from_sheet(rows: dict[str, dict]) -> list[ExceptionRow]`. Input `rows` maps primary value → cells dict using the human-sheet column names from Task 1 (`Title/Program/Owner/Estimate Days/Target/Intended Epic/Jira Key` and `Cell/Person/Sprint/Day Cost`). Empty-string or missing cells → None; missing Target → "unscheduled"; Estimate Days/Day Cost coerced to float (missing → 0.0); Sprint coerced to int. Rows with an empty Person (exceptions) are skipped.

- [ ] **Step 1: Write the failing tests**

`tests/test_humansheets.py`:

```python
from tentpole.humansheets import exceptions_from_sheet, ghosts_from_sheet
from tentpole.model import ExceptionRow, Ghost


def test_ghosts_from_sheet():
    rows = {
        "Cal pipeline": {"Title": "Cal pipeline", "Program": "telemetry",
                         "Owner": "", "Estimate Days": 8,
                         "Target": "plan+1", "Intended Epic": "E-1",
                         "Jira Key": ""},
        "Bare row": {"Title": "Bare row"},
    }
    ghosts = {g.title: g for g in ghosts_from_sheet(rows)}
    cal = ghosts["Cal pipeline"]
    assert cal == Ghost(title="Cal pipeline", estimate_days=8.0,
                        target="plan+1", program="telemetry", owner=None,
                        intended_epic="E-1", jira_key=None)
    bare = ghosts["Bare row"]
    assert bare.target == "unscheduled" and bare.estimate_days == 0.0


def test_exceptions_from_sheet():
    rows = {
        "ada|3": {"Cell": "ada|3", "Person": "ada", "Sprint": 3,
                  "Day Cost": "5"},
        "junk": {"Cell": "junk", "Person": "", "Sprint": 1, "Day Cost": 1},
    }
    assert exceptions_from_sheet(rows) == [
        ExceptionRow(person="ada", sprint_id=3, day_cost=5.0)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_humansheets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.humansheets'`.

- [ ] **Step 3: Implement `src/tentpole/humansheets.py`**

```python
"""Parse human-owned sheet state (Future Work, Exceptions) back into
bundle inputs (spec section 7: the sync reads these, never writes them)."""
from __future__ import annotations

from tentpole.model import ExceptionRow, Ghost


def _text(cells: dict, name: str) -> str | None:
    value = cells.get(name)
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def _number(cells: dict, name: str) -> float:
    value = cells.get(name)
    if value is None or str(value).strip() == "":
        return 0.0
    return float(value)


def ghosts_from_sheet(rows: dict[str, dict]) -> list[Ghost]:
    ghosts = []
    for cells in rows.values():
        title = _text(cells, "Title")
        if not title:
            continue
        ghosts.append(Ghost(
            title=title,
            estimate_days=_number(cells, "Estimate Days"),
            target=_text(cells, "Target") or "unscheduled",
            program=_text(cells, "Program"),
            owner=_text(cells, "Owner"),
            intended_epic=_text(cells, "Intended Epic"),
            jira_key=_text(cells, "Jira Key"),
        ))
    return ghosts


def exceptions_from_sheet(rows: dict[str, dict]) -> list[ExceptionRow]:
    out = []
    for cells in rows.values():
        person = _text(cells, "Person")
        if not person:
            continue
        out.append(ExceptionRow(
            person=person,
            sprint_id=int(_number(cells, "Sprint")),
            day_cost=_number(cells, "Day Cost"),
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_humansheets.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/humansheets.py tests/test_humansheets.py
git commit -m "feat: parse human-owned sheets back into bundle inputs"
```

---

### Task 8: Run report

**Files:**
- Create: `src/tentpole/runreport.py`
- Test: `tests/test_runreport.py`

**Interfaces:**
- Consumes: `Bundle`; `diag` dict; `plans: dict[str, list[Change]]` (Task 5 `Change`).
- Produces: `build_report(bundle, diag, plans) -> dict` with keys exactly: `as_of` (ISO str), `issues` (int, non-external count), `findings` (dict check → count), `reds` (int), `yellows` (int), `hygiene` (int), `ghosts_unknown_jira_key` (sorted list of ghost titles whose `jira_key` is set but not a bundle issue key), `changes` (dict sheet → dict op → count, only non-zero ops); `render_report(report) -> str` (one-screen text; must contain "SYNC HEALTH", every sheet name with changes, and a "ghosts with unknown Jira keys" line when non-empty).

- [ ] **Step 1: Write the failing tests**

`tests/test_runreport.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_runreport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.runreport'`.

- [ ] **Step 3: Implement `src/tentpole/runreport.py`**

```python
"""Run report / Sync Health (spec section 8): a silently failing or
silently weird sync must be impossible."""
from __future__ import annotations

from tentpole.changeplan import Change
from tentpole.model import Bundle


def build_report(bundle: Bundle, diag: dict,
                 plans: dict[str, list[Change]]) -> dict:
    findings: dict[str, int] = {}
    for f in diag["findings"]:
        findings[f.check] = findings.get(f.check, 0) + 1
    changes = {}
    for sheet, plan in plans.items():
        ops: dict[str, int] = {}
        for change in plan:
            ops[change.op] = ops.get(change.op, 0) + 1
        if ops:
            changes[sheet] = ops
    return {
        "as_of": bundle.as_of.isoformat(),
        "issues": sum(1 for i in bundle.issues if not i.external),
        "findings": findings,
        "reds": sum(1 for f in diag["findings"] if f.severity == "red"),
        "yellows": sum(1 for f in diag["findings"]
                       if f.severity == "yellow"),
        "hygiene": len(diag["hygiene"]),
        "ghosts_unknown_jira_key": sorted(
            g.title for g in bundle.ghosts
            if g.jira_key and bundle.issue(g.jira_key) is None),
        "changes": changes,
    }


def render_report(report: dict) -> str:
    lines = [f"SYNC HEALTH — as of {report['as_of']}",
             f"issues: {report['issues']}   reds: {report['reds']}   "
             f"yellows: {report['yellows']}   hygiene: {report['hygiene']}"]
    for check, n in sorted(report["findings"].items()):
        lines.append(f"  {check}: {n}")
    lines.append("changes:")
    if not report["changes"]:
        lines.append("  (none)")
    for sheet, ops in sorted(report["changes"].items()):
        summary = ", ".join(f"{op} {n}" for op, n in sorted(ops.items()))
        lines.append(f"  {sheet}: {summary}")
    if report["ghosts_unknown_jira_key"]:
        lines.append("ghosts with unknown Jira keys: "
                     + ", ".join(report["ghosts_unknown_jira_key"]))
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_runreport.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/runreport.py tests/test_runreport.py
git commit -m "feat: sync health run report"
```

---

### Task 9: Sync orchestration (pure)

**Files:**
- Create: `src/tentpole/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `assemble` (diagnostics), `build_sheetspecs` (sheets), `plan_changes`/`Change` (changeplan), `SCHEMAS` (schema), `snapshot_records` (snapshots), `build_report` (runreport), `Rule` (hygiene).
- Produces: `SyncResult` (plain dataclass: `diag: dict`, `specs: dict[str, SheetSpec]`, `plans: dict[str, list[Change]]`, `snapshots: list[dict]`, `report: dict`); `run_sync(bundle, rules: list[Rule] | None, current: dict[str, dict[str, dict]]) -> SyncResult`. `current` maps sheet name → (primary value → cells); missing sheets default to `{}`. Pure — no I/O.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.sync'`.

- [ ] **Step 3: Implement `src/tentpole/sync.py`**

```python
"""Pure sync orchestration (spec section 8, steps 2-3): bundle + current
sheet state -> specs, change plans, snapshots, report. All I/O stays in
cli.py."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.changeplan import Change, plan_changes
from tentpole.diagnostics import assemble
from tentpole.hygiene import Rule
from tentpole.model import Bundle
from tentpole.runreport import build_report
from tentpole.schema import SCHEMAS
from tentpole.sheets import SheetSpec, build_sheetspecs
from tentpole.snapshots import snapshot_records


@dataclass
class SyncResult:
    diag: dict
    specs: dict[str, SheetSpec]
    plans: dict[str, list[Change]]
    snapshots: list[dict]
    report: dict


def run_sync(bundle: Bundle, rules: list[Rule] | None,
             current: dict[str, dict[str, dict]]) -> SyncResult:
    diag = assemble(bundle, rules=rules)
    specs = build_sheetspecs(bundle, diag)
    plans = {
        name: plan_changes(spec, current.get(name, {}), SCHEMAS[name])
        for name, spec in specs.items()
    }
    return SyncResult(
        diag=diag,
        specs=specs,
        plans=plans,
        snapshots=snapshot_records(bundle),
        report=build_report(bundle, diag, plans),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sync.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/sync.py tests/test_sync.py
git commit -m "feat: pure sync orchestration"
```

---

### Task 10: CLI — `tentpole sync` and `tentpole schema`

**Files:**
- Modify: `src/tentpole/cli.py` (add two subcommands; do not change `check`)
- Test: `tests/test_cli_sync.py`

**Interfaces:**
- Consumes: `run_sync` (sync), `render_schemas` (schema), `ghosts_from_sheet`/`exceptions_from_sheet` (humansheets), `to_jsonl` (snapshots), `render_report` (runreport), `load_bundle` (model), `load_rules` (hygiene), plus `dataclasses.asdict` and `dataclasses.replace`.
- Produces: `tentpole schema show` (prints `render_schemas()`, exit 0); `tentpole sync --bundle DIR --state DIR --out DIR [--rules FILE]`:
  - State dir (read): `<sheet>.json` per machine sheet = `{primary: {col: value}}` (missing → `{}`); `future_work.json`/`exceptions.json` in the same format — when present they REPLACE `bundle.ghosts`/`bundle.exceptions` via `dataclasses.replace` (Smartsheet is authoritative for human sheets); `snapshots.jsonl` (appended to, created if missing).
  - Out dir (written, created with `mkdir(parents=True, exist_ok=True)`): `plans/<sheet>.json` (list of `asdict(Change)`), `report.json`, `report.txt`.
  - Prints `render_report`, exits 0 (the sync is a pipeline step; `check` is the red-gate).

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_sync.py`:

```python
import json

import pytest

from tentpole.cli import main


@pytest.fixture
def dirs(tmp_path):
    bundle = tmp_path / "bundle"
    state = tmp_path / "state"
    out = tmp_path / "out"
    bundle.mkdir()
    state.mkdir()
    (bundle / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (bundle / "sprints.json").write_text(json.dumps([
        {"id": 1, "name": "S1", "start": "2026-07-13", "end": "2026-07-22"},
    ]))
    (bundle / "issues.json").write_text(json.dumps([
        {"key": "T-1", "summary": "Parse frames", "issue_type": "Task",
         "status_category": "todo", "assignee": "ada", "sprint_id": 1,
         "remaining_estimate_days": 3.0},
    ]))
    (bundle / "config.json").write_text(json.dumps({"team": ["ada"]}))
    return bundle, state, out


def test_schema_show(capsys):
    assert main(["schema", "show"]) == 0
    out = capsys.readouterr().out
    assert "issues" in out and "future_work" in out


def test_sync_writes_outputs(dirs, capsys):
    bundle, state, out = dirs
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    plans = json.loads((out / "plans" / "issues.json").read_text())
    assert any(c["op"] == "add" and c["key"] == "T-1" for c in plans)
    report = json.loads((out / "report.json").read_text())
    assert report["issues"] == 1
    assert "SYNC HEALTH" in (out / "report.txt").read_text()
    assert "SYNC HEALTH" in capsys.readouterr().out
    lines = (state / "snapshots.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["key"] == "T-1"


def test_sync_appends_snapshots_and_reads_human_sheets(dirs):
    bundle, state, out = dirs
    (state / "future_work.json").write_text(json.dumps({
        "Cal pipeline": {"Title": "Cal pipeline", "Estimate Days": 8,
                         "Target": "plan+1"}}))
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    lines = (state / "snapshots.jsonl").read_text().splitlines()
    assert len(lines) == 2                      # appended, not overwritten
    report = json.loads((out / "report.json").read_text())
    assert report["changes"]["capacity"]  # plan present (state never applied)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli_sync.py -v`
Expected: FAIL — `test_schema_show` errors because argparse knows no `schema` command (SystemExit).

- [ ] **Step 3: Modify `src/tentpole/cli.py`**

Add imports (merge with existing):

```python
import json
from dataclasses import asdict, replace

from tentpole.humansheets import exceptions_from_sheet, ghosts_from_sheet
from tentpole.runreport import render_report
from tentpole.schema import SCHEMAS, render_schemas
from tentpole.snapshots import to_jsonl
from tentpole.sync import run_sync
```

Inside `main()`, after the existing `check` parser setup, add:

```python
    schema_cmd = sub.add_parser("schema", help="sheet schema utilities")
    schema_sub = schema_cmd.add_subparsers(dest="schema_command",
                                           required=True)
    schema_sub.add_parser("show", help="print schemas for manual creation")

    sync_cmd = sub.add_parser("sync", help="bundle + state -> change plans")
    sync_cmd.add_argument("--bundle", required=True, type=Path)
    sync_cmd.add_argument("--state", required=True, type=Path)
    sync_cmd.add_argument("--out", required=True, type=Path)
    sync_cmd.add_argument("--rules", type=Path, default=None)
```

And after `args = parser.parse_args(argv)`, route (keep the existing `check` body; restructure into `if args.command == ...` branches):

```python
    if args.command == "schema":
        print(render_schemas())
        return 0

    if args.command == "sync":
        bundle = load_bundle(args.bundle)
        rules = load_rules(args.rules) if args.rules else None

        def _state(name: str) -> dict:
            path = args.state / f"{name}.json"
            return json.loads(path.read_text()) if path.exists() else {}

        future_work = _state("future_work")
        if future_work:
            bundle = replace(bundle, ghosts=ghosts_from_sheet(future_work))
        exceptions = _state("exceptions")
        if exceptions:
            bundle = replace(bundle,
                             exceptions=exceptions_from_sheet(exceptions))
        current = {name: _state(name) for name, schema in SCHEMAS.items()
                   if schema.owned == "machine"}
        result = run_sync(bundle, rules, current)

        plans_dir = args.out / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        for name, plan in result.plans.items():
            (plans_dir / f"{name}.json").write_text(
                json.dumps([asdict(c) for c in plan], indent=2))
        (args.out / "report.json").write_text(
            json.dumps(result.report, indent=2))
        text = render_report(result.report)
        (args.out / "report.txt").write_text(text + "\n")
        with (args.state / "snapshots.jsonl").open("a") as fh:
            fh.write(to_jsonl(result.snapshots))
        print(text)
        return 0
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (70 tests: 41 from Plan 1 + 29 new).

- [ ] **Step 5: Smoke-test**

Run: `.venv/bin/tentpole schema show | head -8`
Expected: schema listing beginning "tentpole sheet schemas".

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/cli.py tests/test_cli_sync.py
git commit -m "feat: tentpole sync and schema show subcommands"
```

---

## Post-plan notes for the reviewer (not tasks)

- **Deliberately deferred to Plan 3:** executing change plans against real Smartsheet (bulk ops, partial success, backoff, Gov base URL), the Jira Cloud extract adapter, `fix apply`, bootstrap-from-schemas, and hygiene fix strategies/proposals.
- **Deliberately NOT done (YAGNI, revisit with real data):** snapshot-based refinement of `throughput.empirical` — the changelog `done_at` signal is adequate until months of snapshots exist; estimation-accuracy "final estimate" column (needs snapshot history; Ratio vs original estimate ships now).
- Test-count expectations inside task steps assume tasks run in order on top of Plan 1's merged master (41 tests).
