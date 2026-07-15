# Gantt and Memory Implementation Plan (0.5.0, Plan 5b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**DEPENDS ON PLAN 5a BEING MERGED.** This plan starts from the end state of `docs/superpowers/plans/2026-07-14-discovery-and-people.md`: the `epics` schema still exists (5a did not touch it), `people` has replaced `team`/`exceptions`, sheet name resolution and `expect:` are in place, snapshots are unwidened, and there is no gantt mode. Do not begin until 5a is on `master`.

**Goal:** Fold the `epics` sheet into `issues` as rollup columns on epic rows; add an opt-in Gantt mode (arrows + milestone diamonds) driven by Smartsheet's dependency engine on the merged issues sheet; add between-plan memory (widened snapshots, a ticket-level carryover check, a `First Planned` column) and extract-time link-hygiene findings; document the planning cadence; ship 0.5.0.

**Architecture:** The `issues` sheet becomes the single place epics live (rollup columns) and, when the sheet has Smartsheet dependencies enabled, a Gantt: tentpole seeds forecast date/duration/predecessor columns distinct from the factual `In Progress`/`Done` columns, and the engine chains the bars and draws the arrows. The pure core computes seeding, the curated arrow subset, deterministic cycle-breaking, and milestone rows; the adapter (behind the injectable `http` seam, with documented-but-unverified shapes) detects the toggle and encodes predecessor cells. Longitudinal memory rides append-only snapshot JSONL, loaded by the CLI and passed into the pure core.

**Tech Stack:** Python 3.11+, stdlib + PyYAML only. pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-14-simplify-sheets-design.md` — §5 (epic/issue merge), §6 (gantt mode), §7 (cadence, link hygiene, between-plan memory), §9 (sheet inventory), §12 (decisions). Every §-numbered decision there is settled.

## Global Constraints

- **Pure core.** No I/O and no clock under `src/tentpole/` except `model.load_bundle`, `hygiene.load_rules`, `cli.py`, and everything under `adapters/`. `date.today()` only in adapters. Gantt-mode detection and predecessor encoding are network facts, so they live in adapters and reach the core as data-in (a `gantt` flag, `prior_snapshots` records); the core never reads the clock (it uses `bundle.as_of` for "today").
- **Fail loud but actionable.** Every rejection is a `ValueError` (or CLI `ERROR:` + exit 1) naming the sheet/row/value and the fix.
- **stdlib + pyyaml only.**
- **Append-only tests** except at explicitly-sanctioned edit sites (each called out inline as **SANCTIONED EDIT**). The full sanctioned-edit list for 5b:
  1. `tests/test_sheets_rollups.py` — `test_epics_sheet_rollup` is replaced by the transitional equivalence-pin test (Task 1) and then removed with the builder (Task 2).
  2. `tests/test_schema.py` — registry set drops `epics` (Task 2).
  3. `tests/test_sync.py` — `test_run_sync_end_to_end` specs set drops `epics` (Task 2).
  4. `tests/test_schema_conformance.py` — specs set drops `epics`; expected-columns logic becomes gantt-aware (Tasks 2, 7).
  5. `tests/test_sheets_rest.py` — `test_build_sheetspecs_covers_machine_sheets` set drops `epics` (Task 2).
  6. `tests/test_changeplan.py` — `test_refuses_mismatched_spec_and_schema` stops using `epics` as the spec name (Task 2).
  7. `tests/test_smartsheet_push.py` — `test_preflight_validates_every_sheet_before_first_write` uses `epics` as its second sheet → swap to `fixversions` (Task 2).
  8. `tests/test_bootstrap.py` — `test_cli_bootstrap_prints_config_snippet` monkeypatch returns `{"issues": 1000, "epics": 1001}` → change `epics` to `fixversions` (Task 2).
  9. `tests/test_snapshots.py` — `test_snapshot_records_shape` expected dict gains `epic_key`/`program` (Task 3).
  10. `tests/test_smartsheet_push.py` — the literal `COLS` fixture (kept literal on purpose as a schema-shape tripwire) gains the five rollup columns in **Task 1** and `First Planned` in **Task 5**; without these, `_validate_columns` throws for every push test that pushes the issues sheet against `COLS`.

  **Rebase note (against the merged 5a):** 5a made `pull_state` return a per-schema resolution report (`{name: {"state","sheet_id","owned"}}`), not a `list[str]`. 5b Task 7's `pull_state` rewrite is built on that shape (adds `settings.json` capture, keeps the report return). 5b's gantt-preflight tests (Task 9) and the preflight test (Task 2) use real schema names (`issues`, `fixversions`), so 5a's new `resolve_sheets` unknown-explicit-key validation passes them unchanged.
- **Test baseline is a variable.** 5a's review may add tests, so 5b's absolute count is not knowable here. The team lead pins `BASE = <5a final passing count>` at dispatch (5a's Task-9 running total was **257**; use the actual number). Each task states **+N new tests** (deltas), never absolute totals. Verify at start:

```bash
cd /Users/juno/Projects/jira-smartsheet
source .venv/bin/activate 2>/dev/null || true
python -m pytest -q 2>&1 | tail -1     # record this as BASE
```

- **Version bump lives in the final task.** `pyproject.toml` goes `0.4.0 → 0.5.0` only in Task 10, after everything is green.

---

## Task 1: Fold epic rollups into the issues sheet (spec §5)

`issues_sheet` already emits epic rows with tickets nested beneath. Give the `issues` schema five columns populated **only on epic rows** (blank on tickets): `Deadline` (DATE), `Open Tickets` (NUMBER), `Remaining Days` (NUMBER — rollup of open children, distinct from the ticket-level `Remaining Est`), `People`, `Runway` ("AT RISK" or blank). Keep the `epics_sheet` builder for now and add a transitional **equivalence pin** proving the merged epic-row rollups equal the retired builder's output for the same bundle. Task 2 removes the builder.

**Files:**
- Modify: `src/tentpole/schema.py` — `issues` schema (lines 38-49): add five columns
- Modify: `src/tentpole/sheets.py` — `issues_sheet` (lines 36-76): emit rollup cells
- Test: `tests/test_sheets_issues.py` (append), `tests/test_sheets_rollups.py` (append equivalence pin), `tests/test_smartsheet_push.py` (SANCTIONED EDIT — extend the literal `COLS` fixture with the five rollup columns)

**Interfaces:**
- Produces: `issues` schema columns gain `Deadline`, `Open Tickets`, `Remaining Days`, `People`, `Runway`. `issues_sheet` emits all five keys on every row — real values on epic rows, `None`/`""` on tickets — so `test_schema_conformance` (which asserts `set(row.cells) == {schema columns}`) keeps passing automatically.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sheets_issues.py`:

```python
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
```

Append to `tests/test_sheets_rollups.py`:

```python
def test_issue_epic_rollups_equal_retired_epics_builder(make_bundle):
    # TRANSITIONAL equivalence pin (spec §5, §11): the merged epic-row
    # rollups must equal the old epics_sheet builder's output for the same
    # bundle. Removed in Task 2 with the builder.
    from datetime import date as _date
    from tentpole.model import FixVersion
    from tentpole.sheets import issues_sheet
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_sheets_issues.py -k rollups tests/test_sheets_rollups.py -k equal -q
```
Expected: FAIL — epic rows have no `Open Tickets` key.

- [ ] **Step 3: Add the five columns to the issues schema**

In `src/tentpole/schema.py`, in the `"issues"` schema (lines 38-49), add after the `ColumnDef("Hygiene")` line (line 46) — placement is cosmetic but keep it before the `In Progress`/`Done`/`In Jira` trio for readability:

```python
        ColumnDef("Deadline", "DATE"),
        ColumnDef("Open Tickets", "NUMBER"),
        ColumnDef("Remaining Days", "NUMBER"),
        ColumnDef("People"), ColumnDef("Runway"),
```

- [ ] **Step 4: Emit rollups in `issues_sheet`**

In `src/tentpole/sheets.py`, rewrite `issues_sheet` (lines 36-76). Replace the whole function with:

```python
def issues_sheet(bundle: Bundle, diag: dict) -> SheetSpec:
    hygiene: dict[str, list[str]] = {}
    for fl in diag["hygiene"]:
        hygiene.setdefault(fl.key, []).append(f"{fl.severity}:{fl.rule}")
    sprint_names = {s.id: s.name for s in bundle.sprints}
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "tentpole_runway"}
    open_work = _open_work(bundle)

    def rollups_for(issue: Issue) -> dict:
        # Populated only on epic rows; blank on tickets (spec §5). Remaining
        # Days is the rollup of OPEN children -- distinct from the
        # ticket-level Remaining Est, which on an epic row stays the epic's
        # own timetracking.
        if issue.issue_type != "Epic":
            return {"Deadline": None, "Open Tickets": None,
                    "Remaining Days": None, "People": None, "Runway": ""}
        children = [i for i in open_work if i.epic_key == issue.key]
        return {
            "Deadline": _iso(effective_deadline(issue, bundle)),
            "Open Tickets": len(children),
            "Remaining Days": sum(estimate_of(i) for i in children),
            "People": ", ".join(sorted({i.assignee for i in children
                                        if i.assignee})),
            "Runway": "AT RISK" if issue.key in at_risk else "",
        }

    def cells_for(issue: Issue) -> dict:
        cells = {
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
        cells.update(rollups_for(issue))
        return cells

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

(`effective_deadline` is already imported at the top of `sheets.py` — `from tentpole.buckets import effective_deadline`; `estimate_of` from `tentpole.demand`; `_open_work` is defined below in the same module.)

- [ ] **Step 5: Extend the shared `COLS` fixture (SANCTIONED EDIT)**

`tests/test_smartsheet_push.py` hardcodes the live 17-column issues shape in the module-level `COLS` fixture (its `ISSUES_SCHEMA = SCHEMAS["issues"]` is a live reference). Adding five synced columns to the schema makes `_validate_columns` throw for every push test that pushes the issues sheet against `COLS`. Keep the fixture **literal** (it is a deliberate schema-shape tripwire — do not switch it to a dynamic helper); extend it. Change the tail of `COLS` from:

```python
    {"id": 33, "title": "Done"},
    {"id": 12, "title": "In Jira"},
]}
```

to:

```python
    {"id": 33, "title": "Done"},
    {"id": 12, "title": "In Jira"},
    {"id": 34, "title": "Deadline"},
    {"id": 35, "title": "Open Tickets"},
    {"id": 36, "title": "Remaining Days"},
    {"id": 37, "title": "People"},
    {"id": 38, "title": "Runway"},
]}
```

- [ ] **Step 6: Run to verify pass**

```bash
python -m pytest tests/test_sheets_issues.py tests/test_sheets_rollups.py tests/test_smartsheet_push.py -q
```
Expected: PASS.

- [ ] **Step 7: Full suite**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: `BASE + 2 passed`. `test_schema_conformance` still passes (issues rows now carry all five new keys, so `set(row.cells)` still equals the schema's column set); the push tests pass because `COLS` now carries the five rollup columns.

- [ ] **Step 8: Commit**

```bash
git add src/tentpole/schema.py src/tentpole/sheets.py tests/test_sheets_issues.py tests/test_sheets_rollups.py tests/test_smartsheet_push.py
git commit -m "feat: epic rollup columns on the issues sheet (spec §5)"
```

**Delta: +2.**

---

## Task 2: Retire the epics schema, builder, and state (spec §5, §9)

Remove the `epics` schema, the `epics_sheet` builder, and its slot in `build_sheetspecs`. Resolution now treats a workspace sheet named `epics` as matching no schema; the push run report prints a one-line hint for it so upgraders aren't confused. This task's sanctioned edits touch every place that named `epics`.

**Files:**
- Modify: `src/tentpole/schema.py` — remove the `epics` schema (lines 50-57)
- Modify: `src/tentpole/sheets.py` — remove `epics_sheet` (lines 86-106), remove from `build_sheetspecs` (line 198)
- Modify: `src/tentpole/adapters/cli.py` — `_push` prints the epics hint
- Modify: `src/tentpole/adapters/smartsheet_load.py` — surface workspace sheet names for the hint
- Tests (SANCTIONED EDITs): `test_schema.py`, `test_sync.py`, `test_schema_conformance.py`, `test_sheets_rest.py`, `test_changeplan.py`, `test_sheets_rollups.py`, `test_smartsheet_push.py`, `test_bootstrap.py`

**Interfaces:**
- Produces: `SCHEMAS` no longer contains `epics`; `build_sheetspecs` returns `{issues, fixversions, dependencies, capacity, accuracy}`. `push_plans` result includes a top-level `_workspace_names: list[str]` (or `_push` calls `_workspace_sheets`) so the CLI can print the `epics` fold hint.

- [ ] **Step 1: Edit the tests first (SANCTIONED EDITs)**

`tests/test_schema.py` — in `test_registry_has_all_sheets_with_ownership`, change the set literal to drop `epics`:

```python
    assert set(SCHEMAS) == {"issues", "fixversions", "dependencies",
                            "capacity", "accuracy", "future_work", "people"}
```

`tests/test_sync.py` — in `test_run_sync_end_to_end`, change the specs set:

```python
    assert set(result.specs) == {"issues", "fixversions",
                                 "dependencies", "capacity", "accuracy"}
    # and drop the epics line entirely
```

`tests/test_sheets_rest.py` — in `test_build_sheetspecs_covers_machine_sheets`:

```python
    assert set(specs) == {"issues", "fixversions", "dependencies",
                          "capacity", "accuracy"}
```

`tests/test_schema_conformance.py` — in `test_all_machine_sheet_rows_match_their_schema_columns`, change the specs-set assertion:

```python
    assert set(specs) == {"issues", "fixversions", "dependencies",
                          "capacity", "accuracy"}
```

`tests/test_changeplan.py` — in `test_refuses_mismatched_spec_and_schema` (lines 61-63), stop naming `epics` (now a non-schema) and use two real, different schema names:

```python
def test_refuses_mismatched_spec_and_schema():
    with pytest.raises(ValueError, match="capacity.*issues|issues.*capacity"):
        plan_changes(SheetSpec("capacity", []), {}, SCHEMAS["issues"])
```

`tests/test_sheets_rollups.py` — **delete** `test_epics_sheet_rollup` (lines 15-37) and the transitional `test_issue_epic_rollups_equal_retired_epics_builder` added in Task 1 (the builder it compares against is gone), and change the import at line 5 from:

```python
from tentpole.sheets import epics_sheet, fixversions_sheet
```

to:

```python
from tentpole.sheets import fixversions_sheet
```

(`test_fixversions_sheet_rollup` stays.)

`tests/test_smartsheet_push.py` — in `test_preflight_validates_every_sheet_before_first_write` (lines 451-469), swap the second sheet from `epics` to `fixversions` (a still-real schema). Change `sheets={"issues": 111, "epics": 222}` to `sheets={"issues": 111, "fixversions": 222}`, the plan file and GET route from `epics` to `fixversions`, and `_cols_for("epics", drop="Runway")` to a `fixversions` column drop — `fixversions` has a `Risk` column, so use `_cols_for("fixversions", drop="Risk")` and `pytest.raises(ValueError, match="Risk")`:

```python
def test_preflight_validates_every_sheet_before_first_write(
        tmp_path, fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111, "fixversions": 222})
    fake_http.add("GET", "/sheets/111", COLS)
    fake_http.add("GET", "/sheets/222",
                  _cols_for("fixversions", drop="Risk"))
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "issues.json").write_text(
        json.dumps([_add("T-1", {"Summary": "s"})]))
    (plans / "fixversions.json").write_text(
        json.dumps([_add("v1", {"Version": "v1"})]))
    (tmp_path / "state").mkdir()
    with pytest.raises(ValueError, match="Risk"):
        push_plans(cfg, plans, tmp_path / "state", http=fake_http)
    assert all(c["method"] == "GET" for c in fake_http.calls)
```

`tests/test_bootstrap.py` — in `test_cli_bootstrap_prints_config_snippet`, change the monkeypatch return and the two assertions from `epics` to `fixversions`:

```python
    monkeypatch.setattr(edge_cli.smartsheet_load, "bootstrap",
                        lambda cfg, names=None: {"issues": 1000,
                                                 "fixversions": 1001})
    ...
    assert "issues: 1000" in out and "fixversions: 1001" in out
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_schema.py tests/test_sync.py tests/test_sheets_rest.py tests/test_schema_conformance.py -q
```
Expected: FAIL — `epics` still in `SCHEMAS`/`build_sheetspecs`.

- [ ] **Step 3: Remove the epics schema and builder**

In `src/tentpole/schema.py`, delete the `"epics"` entry (lines 50-57).

In `src/tentpole/sheets.py`, delete the `epics_sheet` function (lines 86-106), and in `build_sheetspecs` (lines 195-203) remove the `"epics": epics_sheet(bundle, diag),` line so it returns:

```python
def build_sheetspecs(bundle: Bundle, diag: dict) -> dict[str, SheetSpec]:
    return {
        "issues": issues_sheet(bundle, diag),
        "fixversions": fixversions_sheet(bundle, diag),
        "dependencies": dependencies_sheet(bundle),
        "capacity": capacity_sheet(diag),
        "accuracy": accuracy_sheet(bundle),
    }
```

- [ ] **Step 4: Add the `epics`-folded run-report hint**

In `src/tentpole/adapters/cli.py`, in `_push`, after building `report` and before the enumeration loop, fetch workspace names and print the hint if an `epics` sheet is present. Add near the top of `_push` (after the `report = ...` try/except), import and call `_workspace_sheets`:

Change the import at the top of `adapters/cli.py` — it currently imports `smartsheet_load` as a module, so use `smartsheet_load._workspace_sheets`. In `_push`, after the successful `report = ...`:

```python
    # Upgraders may still have an `epics` sheet in the workspace; it now
    # matches no schema (folded into issues in 0.5.0). Say so once.
    try:
        ws_names = set(smartsheet_load._workspace_sheets(cfg.smartsheet))
    except Exception:
        ws_names = set()
    if "epics" in ws_names:
        print("note: a sheet named 'epics' is in the workspace but no longer "
              "matches a schema -- its rollups folded into 'issues' in 0.5.0")
```

(This is a second workspace call; acceptable for a hint. If the extra call is undesirable, Task 9's push path can thread the names through `push_plans`; for now the simple form is fine and testable.)

- [ ] **Step 5: Run to verify pass**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: green; two tests removed relative to Task 1's total (the retired `test_epics_sheet_rollup` and the transitional equivalence pin), the hint test is added in Step 6. Confirm no `epics` references remain in source:

```bash
grep -rn "epics" src/ | grep -v "epic_key\|epics folded\|folded into issues"
```
Expected: no functional references (only comments/hints).

- [ ] **Step 6: Add a hint test**

Append to `tests/test_smartsheet_push.py`:

```python
def test_cli_push_prints_epics_fold_hint(tmp_path, monkeypatch, capsys):
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  workspace_id: 999\n"
        "  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    ws = {"sheets": [{"id": 1, "name": "issues"},
                     {"id": 2, "name": "epics"}]}
    routes = [("GET", "/workspaces/999", ws), ("GET", "/sheets/1", COLS)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "folded into issues" in out
```

Note: `resolve_sheets` already calls `GET /workspaces/999` once; `_push`'s hint call is a second `GET /workspaces/999`. `_fake_urlopen` matches by substring and returns the same payload for repeated calls, so one route entry serves both. Run:

```bash
python -m pytest tests/test_smartsheet_push.py -k epics_fold -q
```
Expected: PASS.

- [ ] **Step 7: Full suite + commit**

```bash
python -m pytest -q 2>&1 | tail -1     # Expected: green (net +1 test vs BASE across Tasks 1-2)
git add src/tentpole/schema.py src/tentpole/sheets.py src/tentpole/adapters/cli.py tests/test_schema.py tests/test_sync.py tests/test_sheets_rest.py tests/test_schema_conformance.py tests/test_changeplan.py tests/test_sheets_rollups.py tests/test_smartsheet_push.py tests/test_bootstrap.py
git commit -m "feat: retire epics schema/builder; epics-fold hint (spec §5, §9)"
```

**Delta from BASE after Tasks 1+2: +1** (Task 1 +2; Task 2 removes 2, adds 1).

---

## Task 3: Widen snapshot records (spec §7)

Each per-ticket snapshot line gains `epic_key` and `program` so future longitudinal analyses have linkage from now on. The parser stays tolerant of old lines lacking the fields (consumers use `.get(...)`). Append-only as ever.

**Files:**
- Modify: `src/tentpole/snapshots.py` — `snapshot_records` (lines 11-24)
- Test (SANCTIONED EDIT): `tests/test_snapshots.py` — `test_snapshot_records_shape`

**Interfaces:**
- Produces: each dict from `snapshot_records` gains `"epic_key"` and `"program"`.

- [ ] **Step 1: Edit the shape test (SANCTIONED EDIT) and add an old-line test**

In `tests/test_snapshots.py`, update the expected dict in `test_snapshot_records_shape` to include the new fields (the fixture issue has no epic/program → both `None`):

```python
    assert records == [{
        "run": "2026-07-12", "key": "T-1", "status": "in_progress",
        "sprint_id": 2, "assignee": "ada", "original": 5.0,
        "remaining": 3.0, "epic_key": None, "program": None,
    }]
```

Append:

```python
def test_snapshot_records_carry_epic_and_program(make_bundle):
    from tentpole.model import Issue
    from tentpole.snapshots import snapshot_records
    b = make_bundle(issues=[
        Issue(key="T-1", summary="t", issue_type="Task",
              status_category="todo", assignee="ada", sprint_id=1,
              epic_key="E-9", program="telemetry")])
    r = snapshot_records(b)[0]
    assert r["epic_key"] == "E-9" and r["program"] == "telemetry"


def test_parse_jsonl_tolerates_old_lines_without_new_fields():
    from tentpole.snapshots import parse_jsonl
    # An old-format line (no epic_key/program) still parses; consumers use
    # .get(...) so the absence is not an error.
    text = '{"run": "2026-01-01", "key": "T-1", "sprint_id": 1}\n'
    parsed = parse_jsonl(text)
    assert parsed[0].get("epic_key") is None
    assert parsed[0]["key"] == "T-1"
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_snapshots.py -q
```
Expected: FAIL — records lack `epic_key`/`program`.

- [ ] **Step 3: Widen `snapshot_records`**

In `src/tentpole/snapshots.py`, add two keys to the dict in `snapshot_records` (after `"remaining": ...`):

```python
            "epic_key": issue.epic_key,
            "program": issue.program,
```

- [ ] **Step 4: Run to verify pass + full suite**

```bash
python -m pytest tests/test_snapshots.py -q
python -m pytest -q 2>&1 | tail -1     # Expected: green (+2 vs previous total)
```

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/snapshots.py tests/test_snapshots.py
git commit -m "feat: widen snapshot records with epic_key and program (spec §7)"
```

**Delta: +2 (net; the shape test is an in-place edit).**

---

## Task 4: Carryover check + prior snapshots as sync input (spec §7)

Prior snapshots become an optional input to the pure sync: the CLI loads the existing `snapshots.jsonl` (before appending the current run) and passes the records in. The **carryover check** compares the two most recent snapshot runs — a ticket that was sprint-planned, is not done, and is sprint-planned again yields a yellow finding, subject = assignee, carrying `epic_key` so reports can group by epic. First run ever (no prior snapshot) → no findings. The epic-level rollup finding is parked for 0.6.

**Files:**
- Modify: `src/tentpole/checks.py` — add `epic_key` field to `Finding`; add `carryover`
- Modify: `src/tentpole/sync.py` — `run_sync` accepts `prior_snapshots`
- Modify: `src/tentpole/diagnostics.py` — `assemble` accepts `prior_snapshots`, runs `carryover`
- Modify: `src/tentpole/cli.py` — sync loads prior JSONL, passes it in; `_SECTION_ORDER` gains `carryover`
- Test: `tests/test_checks_flow.py` or new `tests/test_carryover.py` (append), `tests/test_cli_sync.py` (append)

**Interfaces:**
- Consumes: widened snapshot records (Task 3).
- Produces:
  - `Finding` gains `epic_key: str | None = None` (frozen dataclass, defaulted — backward compatible; existing checks omit it).
  - `carryover(bundle: Bundle, prior_snapshots: list[dict] | None) -> list[Finding]`.
  - `assemble(bundle, rules=None, prior_snapshots=None)`.
  - `run_sync(bundle, rules, current, prior_snapshots=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_carryover.py`:

```python
from datetime import date

from tentpole.checks import carryover
from tentpole.model import Issue


def _issue(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_carryover_fires_for_replanned_ticket(make_bundle):
    # T-42 was sprint-planned in the prior run, is still not done, and is
    # sprint-planned again -> yellow, subject = assignee, carries epic_key.
    prior = [{"run": "2026-05-01", "key": "T-42", "sprint_id": 3,
              "status": "in_progress", "remaining": 5.0,
              "assignee": "ada", "epic_key": "E-1"}]
    b = make_bundle(issues=[
        _issue("T-42", assignee="ada", sprint_id=5, epic_key="E-1",
               status_category="in_progress", remaining_estimate_days=3.0)])
    findings = carryover(b, prior)
    assert len(findings) == 1
    f = findings[0]
    assert (f.check, f.severity, f.subject) == ("carryover", "yellow", "ada")
    assert f.epic_key == "E-1"
    assert "T-42" in f.message and "5.0d" in f.message and "3.0d" in f.message


def test_carryover_quiet_when_done_or_unplanned(make_bundle):
    prior = [
        {"run": "2026-05-01", "key": "T-1", "sprint_id": 3},
        {"run": "2026-05-01", "key": "T-2", "sprint_id": 3},
    ]
    b = make_bundle(issues=[
        _issue("T-1", sprint_id=5, status_category="done"),   # done now
        _issue("T-2", sprint_id=None),                         # not planned now
    ])
    assert carryover(b, prior) == []


def test_carryover_quiet_when_not_planned_before(make_bundle):
    prior = [{"run": "2026-05-01", "key": "T-1", "sprint_id": None}]
    b = make_bundle(issues=[_issue("T-1", sprint_id=5)])
    assert carryover(b, prior) == []


def test_carryover_no_prior_no_findings(make_bundle):
    b = make_bundle(issues=[_issue("T-1", sprint_id=5)])
    assert carryover(b, None) == []
    assert carryover(b, []) == []


def test_carryover_uses_only_most_recent_prior_run(make_bundle):
    # Two prior runs; only the most recent (2026-06-01) counts as "was
    # planned". T-1 was planned in the OLD run but not the recent one -> no
    # carryover.
    prior = [
        {"run": "2026-05-01", "key": "T-1", "sprint_id": 3},
        {"run": "2026-06-01", "key": "T-1", "sprint_id": None},
    ]
    b = make_bundle(issues=[_issue("T-1", sprint_id=5)])
    assert carryover(b, prior) == []
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_carryover.py -q
```
Expected: FAIL — `cannot import name 'carryover'`.

- [ ] **Step 3: Add the `epic_key` field to `Finding` and the `carryover` check**

In `src/tentpole/checks.py`, add a field to `Finding` (lines 14-20):

```python
@dataclass(frozen=True)
class Finding:
    check: str
    severity: str          # "red" | "yellow"
    subject: str           # person, epic key, fixVersion name, or "team"
    bucket_id: str | None
    message: str
    epic_key: str | None = None   # set by carryover so reports group by epic
```

Append to `src/tentpole/checks.py`:

```python
def carryover(bundle: Bundle, prior_snapshots: list[dict] | None) -> list[Finding]:
    # Spec §7: compare the two most recent snapshot runs (the most recent
    # prior run vs the current bundle). A ticket sprint-planned then, still
    # not done, and sprint-planned again now is a yellow carryover. First
    # run ever (no prior) -> nothing. Ticket-level (sprints hold tickets);
    # the epic-level rollup is parked for 0.6.
    if not prior_snapshots:
        return []
    latest_run = max(r["run"] for r in prior_snapshots)
    was_planned = {
        r["key"]: r for r in prior_snapshots
        if r["run"] == latest_run and r.get("sprint_id") is not None}
    findings = []
    for issue in bundle.issues:
        if issue.external or issue.issue_type == "Epic":
            continue
        if issue.status_category == "done" or issue.sprint_id is None:
            continue
        prev = was_planned.get(issue.key)
        if prev is None:
            continue
        prev_rem = prev.get("remaining")
        prev_txt = f"{prev_rem:.1f}d" if isinstance(prev_rem, (int, float)) \
            else "?"
        cur_rem = issue.remaining_estimate_days
        cur_txt = f"{cur_rem:.1f}d" if isinstance(cur_rem, (int, float)) \
            else "?"
        findings.append(Finding(
            "carryover", "yellow", issue.assignee or "unassigned", None,
            f"{issue.key}: second consecutive plan; {prev_txt} -> {cur_txt} "
            f"remaining", epic_key=issue.epic_key))
    return findings
```

- [ ] **Step 4: Thread `prior_snapshots` through `assemble` and `run_sync`**

In `src/tentpole/diagnostics.py`, import `carryover` (add to the `from tentpole.checks import (...)` list) and change `assemble`'s signature + findings:

```python
def assemble(bundle: Bundle, rules: list[Rule] | None = None,
             prior_snapshots: list[dict] | None = None) -> dict:
    buckets = buckets_for(bundle)
    demand = compile_demand(bundle, buckets)
    findings = (
        sprint_overload(bundle, buckets, demand)
        + team_subscription(bundle, buckets, demand)
        + deadline_risk(bundle, buckets)
        + tentpole_runway(bundle, buckets, demand)
        + dependency_readiness(bundle, buckets)
        + ghost_claims(bundle, buckets)
        + team_drift(bundle, buckets, demand)
        + unmatched_exception(bundle, buckets)
        + carryover(bundle, prior_snapshots)
    )
```

(The `unmatched_exception` line is from Plan 5a Task 6.)

In `src/tentpole/sync.py`, change `run_sync` (lines 27-41):

```python
def run_sync(bundle: Bundle, rules: list[Rule] | None,
             current: dict[str, dict[str, dict]],
             prior_snapshots: list[dict] | None = None) -> SyncResult:
    diag = assemble(bundle, rules=rules, prior_snapshots=prior_snapshots)
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

- [ ] **Step 5: Load prior snapshots in the CLI sync command**

In `src/tentpole/cli.py`, add `carryover` to `_SECTION_ORDER` (append `"carryover"`).

In the `sync` command, load the existing snapshots **before** the run (they are appended after), and pass them in. Just before `result = run_sync(bundle, rules, current)`, add:

```python
        snap_path = args.state / "snapshots.jsonl"
        prior_snapshots = None
        if snap_path.exists():
            from tentpole.snapshots import parse_jsonl
            prior_snapshots = parse_jsonl(snap_path.read_text())
        result = run_sync(bundle, rules, current,
                          prior_snapshots=prior_snapshots)
```

(Replace the existing `result = run_sync(bundle, rules, current)` line.)

- [ ] **Step 6: Add a CLI-level carryover test**

Append to `tests/test_cli_sync.py`:

```python
def test_sync_carryover_fires_on_second_run(dirs, capsys):
    # First run seeds snapshots.jsonl (T-1 sprint-planned, not done). Second
    # run over the same bundle -> carryover yellow finding.
    bundle, state, out = dirs
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    main(["sync", "--bundle", str(bundle), "--state", str(state),
          "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert report["findings"].get("carryover") == 1
```

(The `dirs` fixture's T-1 is `todo`, `sprint_id=1` — not done, sprint-planned; the first run records it, the second flags it.)

- [ ] **Step 7: Run + full suite + commit**

```bash
python -m pytest tests/test_carryover.py tests/test_cli_sync.py -q
python -m pytest -q 2>&1 | tail -1     # Expected: green (+6 vs previous total)
git add src/tentpole/checks.py src/tentpole/sync.py src/tentpole/diagnostics.py src/tentpole/cli.py tests/test_carryover.py tests/test_cli_sync.py
git commit -m "feat: ticket-level carryover check; prior snapshots as sync input (spec §7)"
```

**Delta: +6.**

---

## Task 5: `First Planned` column on the issues sheet (spec §7)

A plain DATE column, tentpole-owned, no engine coupling: the earliest snapshot run in which the ticket had a sprint. Blank when there is no history. Chronic drifters become sortable in the plan of record. It needs the prior snapshots threaded into the sheet builder.

**Files:**
- Modify: `src/tentpole/schema.py` — `issues` schema: add `First Planned` (DATE)
- Modify: `src/tentpole/sheets.py` — `issues_sheet` and `build_sheetspecs` take `prior_snapshots`; compute First Planned per issue
- Modify: `src/tentpole/sync.py` — pass `prior_snapshots` into `build_sheetspecs`
- Test: `tests/test_sheets_issues.py` (append), `tests/test_smartsheet_push.py` (SANCTIONED EDIT — extend the literal `COLS` fixture with `First Planned`)

**Interfaces:**
- Produces: `issues` schema gains `First Planned` (DATE, synced). `build_sheetspecs(bundle, diag, prior_snapshots=None)`; `issues_sheet(bundle, diag, prior_snapshots=None)`. First Planned = earliest `run` among **prior** snapshot records for that key with `sprint_id` set, else `None` (the current run is not yet snapshotted at sheet-build time, so a ticket first planned this period reads blank now and dates itself next period).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sheets_issues.py`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_sheets_issues.py -k first_planned -q
```
Expected: FAIL — `issues_sheet()` takes no `prior_snapshots`; no `First Planned` key.

- [ ] **Step 3: Add the column**

In `src/tentpole/schema.py`, in the `issues` schema, add after the five rollup columns (from Task 1):

```python
        ColumnDef("First Planned", "DATE"),
```

- [ ] **Step 4: Compute First Planned in `issues_sheet`**

In `src/tentpole/sheets.py`, change `issues_sheet`'s signature and precompute the earliest planned run per key. Replace the `def issues_sheet(bundle: Bundle, diag: dict) -> SheetSpec:` line and the start of its body with:

```python
def issues_sheet(bundle: Bundle, diag: dict,
                 prior_snapshots: list[dict] | None = None) -> SheetSpec:
    hygiene: dict[str, list[str]] = {}
    for fl in diag["hygiene"]:
        hygiene.setdefault(fl.key, []).append(f"{fl.severity}:{fl.rule}")
    sprint_names = {s.id: s.name for s in bundle.sprints}
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "tentpole_runway"}
    open_work = _open_work(bundle)
    first_planned = _first_planned(prior_snapshots)
```

Add a helper above `issues_sheet` (after `_links`, line 33):

```python
def _first_planned(prior_snapshots: list[dict] | None) -> dict[str, str]:
    # Earliest PRIOR snapshot run in which each ticket had a sprint (spec §7).
    # Blank (absent from the map) when there is no history -- the current run
    # is not yet snapshotted at sheet-build time, so a ticket first planned
    # this period shows blank now and dates itself next period.
    earliest: dict[str, str] = {}
    for r in (prior_snapshots or []):
        if r.get("sprint_id") is None:
            continue
        key, run = r["key"], r["run"]
        if key not in earliest or run < earliest[key]:
            earliest[key] = run
    return earliest
```

In `issues_sheet`, the precompute line becomes `first_planned = _first_planned(prior_snapshots)` (as shown in the signature edit above). In `cells_for`, add `First Planned` to the base cells dict (after `"In Jira": True,`):

```python
            "First Planned": first_planned.get(issue.key),
```

- [ ] **Step 5: Thread `prior_snapshots` through `build_sheetspecs` and `run_sync`**

In `src/tentpole/sheets.py`, change `build_sheetspecs`:

```python
def build_sheetspecs(bundle: Bundle, diag: dict,
                     prior_snapshots: list[dict] | None = None
                     ) -> dict[str, SheetSpec]:
    return {
        "issues": issues_sheet(bundle, diag, prior_snapshots),
        "fixversions": fixversions_sheet(bundle, diag),
        "dependencies": dependencies_sheet(bundle),
        "capacity": capacity_sheet(diag),
        "accuracy": accuracy_sheet(bundle),
    }
```

In `src/tentpole/sync.py`, change the `specs = build_sheetspecs(bundle, diag)` line to:

```python
    specs = build_sheetspecs(bundle, diag, prior_snapshots)
```

- [ ] **Step 6: Extend the shared `COLS` fixture (SANCTIONED EDIT)**

`First Planned` is a synced (non-gantt) column, so — exactly as in Task 1 — `tests/test_smartsheet_push.py`'s literal `COLS` fixture must gain it or `_validate_columns` throws for the issues push tests. Keep it literal. Change the `COLS` tail (already extended with the five rollup columns in Task 1) from:

```python
    {"id": 37, "title": "People"},
    {"id": 38, "title": "Runway"},
]}
```

to:

```python
    {"id": 37, "title": "People"},
    {"id": 38, "title": "Runway"},
    {"id": 39, "title": "First Planned"},
]}
```

- [ ] **Step 7: Run + full suite**

```bash
python -m pytest tests/test_sheets_issues.py tests/test_smartsheet_push.py -q
python -m pytest -q 2>&1 | tail -1     # Expected: prior + 1
```
`test_schema_conformance` still passes (issues rows now carry `First Planned` on every row, matching the widened schema); the push tests pass because `COLS` now carries it.

- [ ] **Step 8: Commit**

```bash
git add src/tentpole/schema.py src/tentpole/sheets.py src/tentpole/sync.py tests/test_sheets_issues.py tests/test_smartsheet_push.py
git commit -m "feat: First Planned column from snapshot history (spec §7)"
```

**Delta: +1.**

---

## Task 6: Link-hygiene findings (spec §7)

Extract-time link pruning lives in Jira, surfaced as findings so links get fixed at the source during planning week. Three new findings over the bundle's `Blocks` links: **cycle members** (naming which edge would be dropped), **blocks-links into done work** (stale), **links to out-of-scope targets** (the blocker/blocked issue is not in the bundle). These are deterministic checks, not an overlay file.

Note: these compute over the same `Blocks` link graph the gantt arrow subset uses (Task 8). To avoid duplication, put the cycle-detection primitive in a shared pure module `src/tentpole/linkgraph.py` that both this task and Task 8 import.

**Files:**
- Create: `src/tentpole/linkgraph.py` — pure blocks-edge extraction + deterministic cycle-breaking
- Modify: `src/tentpole/checks.py` — add `link_hygiene`
- Modify: `src/tentpole/diagnostics.py` — run `link_hygiene` in `assemble`
- Modify: `src/tentpole/cli.py` — `_SECTION_ORDER` gains `link_hygiene`
- Test: `tests/test_linkgraph.py` (new), `tests/test_checks_flow.py` (append) or a new `tests/test_link_hygiene.py`

**Interfaces:**
- Produces:
  - `blocks_edges(bundle) -> list[tuple[str, str]]` — directed `(blocker_key, blocked_key)` edges from `Blocks` links between issues, deduped and sorted. A `Blocks`/`inward` link on X with `other_key` O means O blocks X → edge `(O, X)`. A `Blocks`/`outward` link on X to O means X blocks O → edge `(X, O)`.
  - `break_cycles(edges) -> tuple[list[tuple[str,str]], list[tuple[str,str]]]` — `(kept, dropped)`. Greedy over edges sorted ascending: add an edge unless it would close a cycle (its target already reaches its source in the DAG so far); the closing edge (the higher sorted key) is dropped. Deterministic.
  - `link_hygiene(bundle) -> list[Finding]`.

- [ ] **Step 1: Write the failing linkgraph tests**

Create `tests/test_linkgraph.py`:

```python
from tentpole.linkgraph import blocks_edges, break_cycles
from tentpole.model import Issue, Link


def _issue(key, links=None, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, links=links or [], **base)


def test_blocks_edges_direction(make_bundle):
    # X-1 is blocked by B-1 (inward) -> edge (B-1, X-1).
    # X-1 blocks A-1 (outward) -> edge (X-1, A-1).
    b = make_bundle(issues=[
        _issue("X-1", links=[Link("Blocks", "inward", "B-1"),
                             Link("Blocks", "outward", "A-1")]),
        _issue("A-1"), _issue("B-1")])
    assert blocks_edges(b) == [("B-1", "X-1"), ("X-1", "A-1")]


def test_break_cycles_drops_highest_key_deterministically():
    # A->B, B->C, C->A is a cycle. Sorted ascending the closing edge is the
    # last one added; ("C","A") is the highest key -> dropped.
    edges = [("A", "B"), ("B", "C"), ("C", "A")]
    kept, dropped = break_cycles(edges)
    assert dropped == [("C", "A")]
    assert set(kept) == {("A", "B"), ("B", "C")}


def test_break_cycles_noop_on_dag():
    edges = [("A", "B"), ("A", "C"), ("B", "C")]
    kept, dropped = break_cycles(edges)
    assert dropped == [] and set(kept) == set(edges)
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_linkgraph.py -q
```
Expected: FAIL — no module `tentpole.linkgraph`.

- [ ] **Step 3: Write `linkgraph.py`**

Create `src/tentpole/linkgraph.py`:

```python
"""Pure blocks-link graph helpers: directed edge extraction and
deterministic cycle-breaking. Shared by link-hygiene findings (checks.py)
and the gantt arrow subset (gantt.py). No I/O, no clock."""
from __future__ import annotations

from tentpole.model import Bundle


def blocks_edges(bundle: Bundle) -> list[tuple[str, str]]:
    # Directed (blocker, blocked) edges from Blocks links. inward on X from
    # O means O blocks X; outward on X to O means X blocks O. Deduped and
    # sorted for determinism. Both endpoints' issues may or may not be in
    # the bundle -- callers filter by scope.
    seen = set()
    for issue in bundle.issues:
        if issue.external:
            continue
        for link in issue.links:
            if link.type != "Blocks":
                continue
            if link.direction == "inward":
                seen.add((link.other_key, issue.key))
            else:
                seen.add((issue.key, link.other_key))
    return sorted(seen)


def _reaches(adj: dict[str, set[str]], src: str, dst: str) -> bool:
    # Does src reach dst following adj (DFS)?
    stack = [src]
    seen = set()
    while stack:
        node = stack.pop()
        if node == dst:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, ()))
    return False


def break_cycles(edges: list[tuple[str, str]]
                 ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    # Greedy DAG construction over edges sorted ascending: add each edge
    # unless its target already reaches its source (adding would close a
    # cycle). The closing edge -- the highest sorted key in the cycle --
    # is the one dropped (spec §6: "highest sorted key loses"). Deterministic.
    adj: dict[str, set[str]] = {}
    kept, dropped = [], []
    for src, dst in sorted(edges):
        if _reaches(adj, dst, src):
            dropped.append((src, dst))
            continue
        adj.setdefault(src, set()).add(dst)
        kept.append((src, dst))
    return kept, dropped
```

- [ ] **Step 4: Run linkgraph tests**

```bash
python -m pytest tests/test_linkgraph.py -q
```
Expected: PASS.

- [ ] **Step 5: Write the failing link-hygiene tests**

Create `tests/test_link_hygiene.py`:

```python
from tentpole.checks import link_hygiene
from tentpole.model import Issue, Link


def _issue(key, links=None, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, links=links or [], **base)


def _by_check(findings):
    out = {}
    for f in findings:
        out.setdefault(f.check, []).append(f)
    return out


def test_link_hygiene_flags_cycle_members(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "B")]),
        _issue("B", links=[Link("Blocks", "outward", "C")]),
        _issue("C", links=[Link("Blocks", "outward", "A")]),
    ])
    findings = [f for f in link_hygiene(b) if f.check == "link_cycle"]
    # The dropped edge (C, A) is named; both endpoints flagged.
    assert findings
    assert all("C" in f.message and "A" in f.message for f in findings)


def test_link_hygiene_flags_blocks_into_done(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "B")]),
        _issue("B", status_category="done"),
    ])
    findings = [f for f in link_hygiene(b) if f.check == "link_stale_done"]
    assert len(findings) == 1
    assert "B" in findings[0].message


def test_link_hygiene_flags_out_of_scope_target(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "OUT-9")]),
    ])   # OUT-9 not in the bundle
    findings = [f for f in link_hygiene(b) if f.check == "link_out_of_scope"]
    assert len(findings) == 1
    assert "OUT-9" in findings[0].message


def test_link_hygiene_quiet_on_clean_graph(make_bundle):
    b = make_bundle(issues=[
        _issue("A", links=[Link("Blocks", "outward", "B")]),
        _issue("B")])
    assert link_hygiene(b) == []
```

- [ ] **Step 6: Run to verify fail**

```bash
python -m pytest tests/test_link_hygiene.py -q
```
Expected: FAIL — `cannot import name 'link_hygiene'`.

- [ ] **Step 7: Add `link_hygiene` to `checks.py`**

At the top of `src/tentpole/checks.py`, add the import:

```python
from tentpole.linkgraph import blocks_edges, break_cycles
```

Append:

```python
def link_hygiene(bundle: Bundle) -> list[Finding]:
    # Spec §7: extract-time link pruning surfaces as findings so links get
    # fixed in Jira (never an overlay file). Three kinds: cycle members
    # (naming the droppable edge), blocks-links into done work (stale), and
    # links to out-of-scope targets (not in the bundle).
    in_scope = {i.key for i in bundle.issues if not i.external}
    findings = []
    edges = blocks_edges(bundle)

    # Out-of-scope: one endpoint is not a bundle issue.
    for src, dst in edges:
        missing = [k for k in (src, dst) if k not in in_scope]
        for k in missing:
            other = dst if k == src else src
            findings.append(Finding(
                "link_out_of_scope", "yellow", other, None,
                f"blocks-link {src} -> {dst} points at {k}, which is not in "
                f"scope -- fix or remove the link in Jira"))

    # Stale: blocker or blocked is done (a blocks-link into/out of done work).
    for src, dst in edges:
        for k, role in ((src, "blocker"), (dst, "blocked")):
            issue = bundle.issue(k)
            if issue is not None and issue.status_category == "done":
                findings.append(Finding(
                    "link_stale_done", "yellow", k, None,
                    f"blocks-link {src} -> {dst} involves done work {k} "
                    f"({role}) -- stale, prune it in Jira"))

    # Cycles: name the edge cycle-breaking would drop, flag both endpoints.
    in_scope_edges = [(s, d) for s, d in edges
                      if s in in_scope and d in in_scope]
    _kept, dropped = break_cycles(in_scope_edges)
    for src, dst in dropped:
        for endpoint in (src, dst):
            findings.append(Finding(
                "link_cycle", "yellow", endpoint, None,
                f"blocks-link cycle: edge {src} -> {dst} would be dropped to "
                f"break the cycle -- resolve it in Jira"))
    return findings
```

- [ ] **Step 8: Wire into `assemble` and `_SECTION_ORDER`**

In `src/tentpole/diagnostics.py`, add `link_hygiene` to the `from tentpole.checks import (...)` list and to the `findings` sum (append `+ link_hygiene(bundle)`).

In `src/tentpole/cli.py`, append `"link_hygiene"` to `_SECTION_ORDER`. Note: `link_hygiene` emits three distinct `check` names (`link_cycle`, `link_stale_done`, `link_out_of_scope`), so add all three to `_SECTION_ORDER` for rendering:

```python
_SECTION_ORDER = [
    "sprint_overload", "deadline_risk", "tentpole_runway",
    "dependency_readiness", "ghost_claims", "team_subscription",
    "team_drift", "unmatched_exception", "carryover",
    "link_cycle", "link_stale_done", "link_out_of_scope",
]
```

- [ ] **Step 9: Run + full suite + commit**

```bash
python -m pytest tests/test_linkgraph.py tests/test_link_hygiene.py -q
python -m pytest -q 2>&1 | tail -1     # Expected: prior + 7
git add src/tentpole/linkgraph.py src/tentpole/checks.py src/tentpole/diagnostics.py src/tentpole/cli.py tests/test_linkgraph.py tests/test_link_hygiene.py
git commit -m "feat: link-hygiene findings (cycles, stale-done, out-of-scope) (spec §7)"
```

**Delta: +7.**

---

## Task 7: Gantt columns, mode flag, and pre-flight plumbing (spec §6)

Introduce the five gantt columns as a distinct, mode-gated subset of the `issues` schema, thread a pure `gantt` flag through `build_sheetspecs`/`issues_sheet` (default `False`, behavior unchanged), realize the **write-never** concept by having the seeder omit engine-owned cells, and add the detection plumbing: `pull` records whether the issues sheet has dependencies enabled, `sync` reads that marker and sets the flag. Actual seeding content is Task 8; here the flag exists and non-gantt behavior is untouched.

**Ambiguity flagged:** §6 says "the four gantt columns" in one place and lists **five** (`Forecast Start`, `Forecast Finish`, `Duration`, `Predecessors`, `Flags`) in another. This plan implements **all five** and pre-flights all five plus the designated `Forecast Start`/`Forecast Finish` pair — the safe superset. The exact `dependenciesEnabled` field name and the designated-column API shape are **unverified** and marked smoke-before-trust.

**Files:**
- Modify: `src/tentpole/schema.py` — `ColumnDef` gains `gantt: bool`; `SheetSchema` gains gantt-aware accessors; `issues` schema gains five gantt columns
- Modify: `src/tentpole/sheets.py` — `issues_sheet`/`build_sheetspecs` accept `gantt`
- Modify: `src/tentpole/sync.py` — `run_sync` accepts `gantt`
- Modify: `src/tentpole/adapters/smartsheet_load.py` — `pull_sheet` captures `dependenciesEnabled`; `pull_state` writes `state/settings.json`
- Modify: `src/tentpole/cli.py` — sync reads `state/settings.json` → gantt flag
- Test (SANCTIONED EDIT): `tests/test_schema_conformance.py` — gantt-aware expected set
- Test: `tests/test_schema.py`, `tests/test_smartsheet_pull.py` (append)

**Interfaces:**
- Produces:
  - `ColumnDef.gantt: bool = False`.
  - `SheetSchema.column_names(gantt=False) -> list[str]` (all columns, gantt ones only when `gantt=True`); `synced_names(gantt=False)` gains the same parameter.
  - `GANTT_COLUMNS = ("Forecast Start", "Forecast Finish", "Duration", "Predecessors", "Flags")` in `schema.py`.
  - `issues_sheet(bundle, diag, prior_snapshots=None, gantt=False)`, `build_sheetspecs(..., gantt=False)`, `run_sync(..., gantt=False)`.
  - `pull_state` writes `settings.json = {"issues": {"dependencies_enabled": bool}}` when it pulls the issues sheet.

- [ ] **Step 1: Write the failing schema tests**

Append to `tests/test_schema.py`:

```python
def test_issues_schema_has_gantt_columns_flagged():
    from tentpole.schema import GANTT_COLUMNS, SCHEMAS
    names = {c.name: c for c in SCHEMAS["issues"].columns}
    for col in GANTT_COLUMNS:
        assert col in names, col
        assert names[col].gantt is True
    # Non-gantt accessor excludes them; gantt accessor includes them.
    assert set(GANTT_COLUMNS).isdisjoint(SCHEMAS["issues"].synced_names())
    assert set(GANTT_COLUMNS).issubset(
        SCHEMAS["issues"].synced_names(gantt=True))
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_schema.py -k gantt -q
```
Expected: FAIL — `GANTT_COLUMNS` undefined; `ColumnDef` has no `gantt`.

- [ ] **Step 3: Extend `ColumnDef`/`SheetSchema` and add gantt columns**

In `src/tentpole/schema.py`, extend `ColumnDef` (lines 10-15):

```python
@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str = "TEXT"      # TEXT | NUMBER | DATE | CHECKBOX
    primary: bool = False
    synced: bool = True     # False = human-owned; the sync never writes it
    gantt: bool = False     # gantt-mode-only column (spec §6)
```

Extend `SheetSchema` accessors (lines 27-28):

```python
    def synced_names(self, gantt: bool = False) -> list[str]:
        return [c.name for c in self.columns
                if c.synced and (gantt or not c.gantt)]

    def column_names(self, gantt: bool = False) -> list[str]:
        return [c.name for c in self.columns if gantt or not c.gantt]
```

Below the imports (after `_human`, before `SCHEMAS`), add:

```python
GANTT_COLUMNS = ("Forecast Start", "Forecast Finish", "Duration",
                 "Predecessors", "Flags")
```

In the `issues` schema, add the gantt columns (after `First Planned` from Task 5, before `In Progress`):

```python
        ColumnDef("Forecast Start", "DATE", gantt=True),
        ColumnDef("Forecast Finish", "DATE", gantt=True),
        ColumnDef("Duration", "NUMBER", gantt=True),
        ColumnDef("Predecessors", gantt=True),
        ColumnDef("Flags", gantt=True),
```

Note: `render_schemas` iterates all columns and will list gantt columns; that is fine (they exist, just mode-gated). The existing `_human` helper is unaffected (people/future_work have no gantt columns).

- [ ] **Step 4: Make the conformance test gantt-aware (SANCTIONED EDIT)**

In `tests/test_schema_conformance.py`, the invariant `set(row.cells) == {c.name for c in schema.columns}` now over-counts gantt columns (which are absent in non-gantt mode). Change the expected set to exclude gantt columns:

```python
    for name, spec in specs.items():
        schema = SCHEMAS[name]
        expected = set(schema.column_names(gantt=False))
        assert spec.rows, f"{name} sheet produced no rows to check"
        for row in spec.rows:
            assert set(row.cells) == expected, (
                f"{name} row '{row.key}' cell names {set(row.cells)} "
                f"do not match schema columns {expected}")
```

(`build_sheetspecs(bundle, diag)` here runs in non-gantt mode, so issues rows carry exactly the non-gantt columns — the assertion holds.)

- [ ] **Step 5: Thread the `gantt` flag (no behavior change yet)**

In `src/tentpole/sheets.py`, change `issues_sheet`'s signature to accept `gantt=False` (add the parameter; do not use it yet — Task 8 fills it in):

```python
def issues_sheet(bundle: Bundle, diag: dict,
                 prior_snapshots: list[dict] | None = None,
                 gantt: bool = False) -> SheetSpec:
```

Change `build_sheetspecs`:

```python
def build_sheetspecs(bundle: Bundle, diag: dict,
                     prior_snapshots: list[dict] | None = None,
                     gantt: bool = False) -> dict[str, SheetSpec]:
    return {
        "issues": issues_sheet(bundle, diag, prior_snapshots, gantt),
        "fixversions": fixversions_sheet(bundle, diag),
        "dependencies": dependencies_sheet(bundle),
        "capacity": capacity_sheet(diag),
        "accuracy": accuracy_sheet(bundle),
    }
```

In `src/tentpole/sync.py`, change `run_sync` to accept and forward `gantt`:

```python
def run_sync(bundle: Bundle, rules: list[Rule] | None,
             current: dict[str, dict[str, dict]],
             prior_snapshots: list[dict] | None = None,
             gantt: bool = False) -> SyncResult:
    diag = assemble(bundle, rules=rules, prior_snapshots=prior_snapshots)
    specs = build_sheetspecs(bundle, diag, prior_snapshots, gantt)
    ...
```

- [ ] **Step 6: Capture `dependenciesEnabled` at pull; write `settings.json`**

In `src/tentpole/adapters/smartsheet_load.py`, `pull_sheet` already GETs `/sheets/{id}`. The response carries the sheet's dependency toggle. **UNVERIFIED field name** (`dependenciesEnabled`); mark smoke-before-trust. Change `pull_state` to capture it for the issues sheet and write a settings file. After the `pull_sheet` call inside `pull_state`'s loop, when `name == "issues"`, also record the flag. Simplest: add a small helper and a settings write.

Add a helper near `pull_sheet`:

```python
def _dependencies_enabled(cfg, sheet_id: int, http=request) -> bool:
    # UNVERIFIED shape: the issues sheet's dependency toggle. Field name is
    # a live-smoke item (spec §6) -- fall back to False if absent so a
    # non-gantt sheet behaves exactly as §5.
    data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
    return bool(data.get("dependenciesEnabled")
                or data.get("projectSettings", {}).get("dependenciesEnabled"))
```

Rewrite `pull_state` to capture and persist the flag. **Rebased on 5a's return shape** (5a Task 7 made `pull_state` return a per-schema resolution report `{name: {"state","sheet_id","owned"}}`, not a `list[str]`); this replacement keeps that report and adds the `settings.json` capture. Replace 5a's `pull_state` body with:

```python
def pull_state(cfg, state_dir: Path, http=request) -> dict[str, dict]:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    resolved = resolve_sheets(cfg, http=http)
    report: dict[str, dict] = {}
    settings = {}
    for name in sorted(SCHEMAS):
        owned = SCHEMAS[name].owned
        sheet_id = resolved.get(name)
        if sheet_id is None:
            report[name] = {"state": "OFF", "sheet_id": None, "owned": owned}
            continue
        state = pull_sheet(cfg, sheet_id, http=http, sheet_name=name,
                           human=owned == "human")
        (state_dir / f"{name}.json").write_text(json.dumps(state, indent=2))
        report[name] = {"state": "SYNCED", "sheet_id": sheet_id,
                        "owned": owned}
        if name == "issues":
            settings["issues"] = {
                "dependencies_enabled": _dependencies_enabled(
                    cfg, sheet_id, http=http)}
    if settings:
        (state_dir / "settings.json").write_text(json.dumps(settings, indent=2))
    return report
```

(This adds a second GET on the issues sheet. Acceptable; a later optimization can reuse the first response. The `_pull` enumeration from 5a is unchanged — it reads the same `state`/`sheet_id`/`owned` keys.)

- [ ] **Step 7: Read the flag in the CLI sync command**

In `src/tentpole/cli.py`, in the sync command, read `state/settings.json` and pass `gantt` to `run_sync`. Replace the `result = run_sync(bundle, rules, current, prior_snapshots=prior_snapshots)` line with:

```python
        settings_path = args.state / "settings.json"
        gantt = False
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            gantt = bool(settings.get("issues", {}).get("dependencies_enabled"))
        result = run_sync(bundle, rules, current,
                          prior_snapshots=prior_snapshots, gantt=gantt)
```

- [ ] **Step 8: Add a pull settings test**

Append to `tests/test_smartsheet_pull.py`:

```python
def test_pull_state_records_issues_dependencies_flag(tmp_path, fake_http):
    from tentpole.adapters.smartsheet_load import pull_state
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111})
    # Two GETs on /sheets/111: pull_sheet, then _dependencies_enabled.
    sheet = dict(SHEET)
    sheet["dependenciesEnabled"] = True
    fake_http.add("GET", "/sheets/111", sheet)
    fake_http.add("GET", "/sheets/111", sheet)
    pull_state(cfg, tmp_path, http=fake_http)
    settings = json.loads((tmp_path / "settings.json").read_text())
    assert settings["issues"]["dependencies_enabled"] is True
```

- [ ] **Step 9: Run + full suite + commit**

```bash
python -m pytest tests/test_schema.py tests/test_schema_conformance.py tests/test_smartsheet_pull.py -q
python -m pytest -q 2>&1 | tail -1     # Expected: prior + 2
git add src/tentpole/schema.py src/tentpole/sheets.py src/tentpole/sync.py src/tentpole/adapters/smartsheet_load.py src/tentpole/cli.py tests/test_schema.py tests/test_schema_conformance.py tests/test_smartsheet_pull.py
git commit -m "feat: gantt columns + mode flag + dependency-toggle detection (spec §6)"
```

**Delta: +2.**

---

## Task 8: Gantt seeding, curated arrows, cycle-breaking, milestones (spec §6)

The pure core of Gantt mode. When `gantt=True`, `issues_sheet` emits gantt cells per row by status, adds the curated arrow subset as `Predecessors` (deterministically cycle-broken, with dropped/external edges named in `Flags`), and appends synthetic milestone rows for unreleased fixVersions. Engine-owned cells (forecast dates on predecessor'd rows, epic rollups) are **omitted** — that is the write-never realization: an omitted cell is never diffed and never written.

**Files:**
- Create: `src/tentpole/gantt.py` — pure seeding + arrow subset + milestone rows
- Modify: `src/tentpole/sheets.py` — `issues_sheet` uses `gantt.py` when `gantt=True`
- Test: `tests/test_gantt.py` (new)

**Interfaces:**
- Consumes: `blocks_edges`/`break_cycles` (Task 6's `linkgraph`), `estimate_of` (`demand`), buckets/sprints.
- Produces:
  - `gantt_cells(bundle) -> dict[str, dict]` — issue key → gantt cell dict for that row (only the keys that row owns; engine-owned keys omitted). Non-gantt rows (epics) map to `{}`.
  - `milestone_rows(bundle) -> list[Row]` — synthetic `milestone:<version>` rows (zero-duration, Forecast Start == Forecast Finish == release date) for unreleased fixVersions with a release date.
  - `DEFAULT_DURATION = 1.0` and the "no estimate" / dropped-edge / external-edge `Flags` text.

- [ ] **Step 1: Write the failing gantt tests**

Create `tests/test_gantt.py`:

```python
from datetime import date

from tentpole.gantt import gantt_cells, milestone_rows
from tentpole.model import FixVersion, Issue, Link


def _t(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_seed_root_gets_start_and_duration(make_bundle):
    # A todo ticket with no incoming arrow: Forecast Start (today = as_of,
    # no future sprint) + Duration; no Predecessors.
    b = make_bundle(issues=[_t("T-1", remaining_estimate_days=3.0)])
    cells = gantt_cells(b)["T-1"]
    assert cells["Forecast Start"] == "2026-07-12"   # bundle.as_of
    assert cells["Duration"] == 3.0
    assert "Predecessors" not in cells                # root has none


def test_seed_root_future_sprint_starts_at_sprint_window(make_bundle):
    # Sprint 2 starts 2026-07-23 (make_sprints default), which is after
    # as_of -> Forecast Start is the sprint window start.
    b = make_bundle(issues=[_t("T-1", remaining_estimate_days=2.0,
                               sprint_id=2)])
    assert gantt_cells(b)["T-1"]["Forecast Start"] == "2026-07-23"


def test_seed_unstarted_with_incoming_edge_gets_duration_and_predecessors(
        make_bundle):
    # B-1 blocks T-1 (T-1 inward). T-1 is unstarted -> Duration +
    # Predecessors=[B-1], and NO Forecast Start (engine chains it =
    # write-never).
    b = make_bundle(issues=[
        _t("B-1", remaining_estimate_days=2.0),
        _t("T-1", remaining_estimate_days=3.0,
           links=[Link("Blocks", "inward", "B-1")])])
    cells = gantt_cells(b)["T-1"]
    assert cells["Predecessors"] == "B-1"
    assert cells["Duration"] == 3.0
    assert "Forecast Start" not in cells


def test_seed_started_anchors_at_actual_start_drops_arrows(make_bundle):
    b = make_bundle(issues=[
        _t("B-1", remaining_estimate_days=2.0),
        _t("T-1", status_category="in_progress",
           first_in_progress=date(2026, 7, 5), remaining_estimate_days=3.0,
           links=[Link("Blocks", "inward", "B-1")])])
    cells = gantt_cells(b)["T-1"]
    assert cells["Forecast Start"] == "2026-07-05"    # actual start
    assert cells["Duration"] == 3.0
    assert "Predecessors" not in cells                # reality retires arrows


def test_seed_done_bars_from_actuals_no_arrows(make_bundle):
    b = make_bundle(issues=[
        _t("T-1", status_category="done",
           first_in_progress=date(2026, 6, 1), done_at=date(2026, 6, 8))])
    cells = gantt_cells(b)["T-1"]
    assert cells["Forecast Start"] == "2026-06-01"
    assert cells["Forecast Finish"] == "2026-06-08"
    assert "Predecessors" not in cells


def test_seed_missing_estimate_defaults_and_flags(make_bundle):
    b = make_bundle(issues=[_t("T-1")])   # no estimate
    cells = gantt_cells(b)["T-1"]
    assert cells["Duration"] == 1.0
    assert "no estimate" in cells["Flags"]


def test_external_edge_renders_as_flag_not_arrow(make_bundle):
    b = make_bundle(issues=[
        _t("T-1", remaining_estimate_days=3.0,
           links=[Link("Blocks", "inward", "OTHER-9")])])   # OTHER-9 not in scope
    cells = gantt_cells(b)["T-1"]
    assert "Predecessors" not in cells
    assert "OTHER-9" in cells["Flags"] and "external" in cells["Flags"]


def test_cycle_dropped_edge_named_in_flags(make_bundle):
    b = make_bundle(issues=[
        _t("A", remaining_estimate_days=1.0,
           links=[Link("Blocks", "outward", "B")]),
        _t("B", remaining_estimate_days=1.0,
           links=[Link("Blocks", "outward", "A")]),
    ])
    cells = gantt_cells(b)
    # (B, A) is the highest-sorted edge -> dropped; both A and B name it.
    flags = cells["A"]["Flags"] + cells["B"]["Flags"]
    assert "B" in flags and "A" in flags and "cycle" in flags.lower()


def test_epic_rows_have_no_gantt_cells(make_bundle):
    epic = Issue(key="E-1", summary="e", issue_type="Epic",
                 status_category="in_progress")
    b = make_bundle(issues=[epic, _t("T-1", epic_key="E-1",
                                     remaining_estimate_days=2.0)])
    assert gantt_cells(b)["E-1"] == {}    # engine rolls epics up (write-never)


def test_epic_blocks_link_renders_as_flag_not_arrow(make_bundle):
    # Spec §6: epic-level blocks links render in Flags, not arrows. An epic
    # E-1 blocking a ticket T-1 flags the non-epic endpoint (T-1) and draws
    # no Predecessors arrow; an epic-to-epic link flags both epic rows.
    e1 = Issue(key="E-1", summary="e", issue_type="Epic",
               status_category="in_progress",
               links=[Link("Blocks", "outward", "T-1"),
                      Link("Blocks", "outward", "E-2")])
    e2 = Issue(key="E-2", summary="e2", issue_type="Epic",
               status_category="todo")
    b = make_bundle(issues=[e1, e2,
                            _t("T-1", remaining_estimate_days=2.0)])
    cells = gantt_cells(b)
    assert "Predecessors" not in cells["T-1"]           # no arrow
    assert "E-1 -> T-1" in cells["T-1"]["Flags"]         # flagged on ticket
    assert "E-1 -> E-2" in cells["E-1"]["Flags"]         # both epics flagged
    assert "E-1 -> E-2" in cells["E-2"]["Flags"]


def test_milestone_rows_for_unreleased_versions(make_bundle):
    b = make_bundle(fix_versions=[
        FixVersion("v1", release_date=date(2026, 9, 1)),
        FixVersion("v2", release_date=date(2026, 9, 1), released=True),
        FixVersion("v3", release_date=None)])
    rows = milestone_rows(b)
    keys = {r.key for r in rows}
    assert keys == {"milestone:v1"}      # released and dateless excluded
    m = rows[0].cells
    assert m["Forecast Start"] == "2026-09-01"
    assert m["Forecast Finish"] == "2026-09-01"
    assert m["Duration"] == 0
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_gantt.py -q
```
Expected: FAIL — no module `tentpole.gantt`.

- [ ] **Step 3: Write `gantt.py`**

Create `src/tentpole/gantt.py`:

```python
"""Pure Gantt seeding (spec §6): forecast columns, the curated arrow
subset with deterministic cycle-breaking, and synthetic milestone rows.
No I/O, no clock -- "today" is bundle.as_of. Engine-owned cells are
OMITTED (the write-never realization: an omitted cell is never diffed and
never written)."""
from __future__ import annotations

from tentpole.demand import estimate_of
from tentpole.linkgraph import blocks_edges, break_cycles
from tentpole.model import Bundle, Issue
from tentpole.sheets import Row

DEFAULT_DURATION = 1.0


def _iso(d):
    return d.isoformat() if d else None


def _duration(issue: Issue) -> tuple[float, str | None]:
    est = estimate_of(issue)
    if est and est > 0:
        return est, None
    return DEFAULT_DURATION, "no estimate (defaulted to 1d)"


def _root_start(issue: Issue, bundle: Bundle) -> str:
    # Future sprint-assigned work starts at the sprint window; else today.
    if issue.sprint_id is not None:
        for s in bundle.sprints:
            if s.id == issue.sprint_id and s.start > bundle.as_of:
                return s.start.isoformat()
    return bundle.as_of.isoformat()


def gantt_cells(bundle: Bundle) -> dict[str, dict]:
    ours = {i.key: i for i in bundle.issues if not i.external}
    # Curated arrows: Blocks edges between in-scope non-done tickets where
    # the target has not started; then cycle-broken deterministically.
    candidate = []
    external_into: dict[str, list[str]] = {}
    epic_flag: dict[str, list[str]] = {}
    for src, dst in blocks_edges(bundle):
        target = ours.get(dst)
        source = ours.get(src)
        if target is None or source is None:
            # External / cross-team edge: render as Flags text on whichever
            # endpoint is in scope (mark where the schedule depends on others).
            if target is not None:
                external_into.setdefault(dst, []).append(src)
            continue
        src_epic = source.issue_type == "Epic"
        dst_epic = target.issue_type == "Epic"
        if src_epic or dst_epic:
            # Epic-level blocks links render in Flags, not arrows (spec §6).
            # Flag the non-epic endpoint; when both are epics, flag both epic
            # rows (Flags is our text column, not engine-owned).
            note = f"epic-level blocks link {src} -> {dst}"
            targets = ([src, dst] if src_epic and dst_epic
                       else [dst] if src_epic else [src])
            for ep in targets:
                epic_flag.setdefault(ep, []).append(note)
            continue
        if (target.status_category == "done"
                or source.status_category == "done"):
            continue   # done work takes no arrow (link-hygiene flags staleness)
        if target.first_in_progress is not None \
                or target.status_category == "in_progress":
            continue   # target already started: not schedulable-blocked
        candidate.append((src, dst))
    kept, dropped = break_cycles(candidate)
    preds: dict[str, list[str]] = {}
    for src, dst in kept:
        preds.setdefault(dst, []).append(src)
    cycle_flag: dict[str, list[str]] = {}
    for src, dst in dropped:
        for endpoint in (src, dst):
            cycle_flag.setdefault(endpoint, []).append(f"{src}->{dst}")

    cells: dict[str, dict] = {}
    for key, issue in ours.items():
        if issue.issue_type == "Epic":
            # Engine rolls epic bars up (omit forecast cells), but an
            # epic-level blocks link still renders in the epic's Flags.
            ef = epic_flag.get(key)
            cells[key] = {"Flags": "; ".join(ef)} if ef else {}
            continue
        c: dict = {}
        flags: list[str] = []
        if issue.status_category == "done":
            # Bars from actuals; no arrows, no Duration seed.
            c["Forecast Start"] = _iso(issue.first_in_progress)
            c["Forecast Finish"] = _iso(issue.done_at)
        elif issue.first_in_progress is not None \
                or issue.status_category == "in_progress":
            # Started: anchor at actual start, drop incoming arrows.
            c["Forecast Start"] = _iso(issue.first_in_progress) \
                or bundle.as_of.isoformat()
            dur, note = _duration(issue)
            c["Duration"] = dur
            if note:
                flags.append(note)
        elif key in preds:
            # Unstarted with an included incoming edge: Duration +
            # Predecessors only. Forecast Start is engine-chained (omit).
            dur, note = _duration(issue)
            c["Duration"] = dur
            c["Predecessors"] = ", ".join(sorted(preds[key]))
            if note:
                flags.append(note)
        else:
            # Root: Forecast Start + Duration.
            c["Forecast Start"] = _root_start(issue, bundle)
            dur, note = _duration(issue)
            c["Duration"] = dur
            if note:
                flags.append(note)
        for ext in external_into.get(key, []):
            flags.append(f"blocked by {ext} (external)")
        for edge in cycle_flag.get(key, []):
            flags.append(f"cycle edge dropped: {edge}")
        for note in epic_flag.get(key, []):
            flags.append(note)
        if flags:
            c["Flags"] = "; ".join(flags)
        cells[key] = c
    return cells


def milestone_rows(bundle: Bundle) -> list[Row]:
    # Synthetic zero-duration diamonds for unreleased fixVersions with a
    # release date. Stable keys (milestone:<version>) so they diff cleanly.
    rows = []
    for fv in sorted(bundle.fix_versions, key=lambda f: f.name):
        if fv.released or fv.release_date is None:
            continue
        # "Key" carries the stable primary so the row round-trips through
        # pull; "Summary" labels the diamond. The only rows in the mirror
        # that do not correspond to a Jira issue.
        rows.append(Row(f"milestone:{fv.name}", {
            "Key": f"milestone:{fv.name}",
            "Summary": f"milestone: {fv.name}",
            "Forecast Start": fv.release_date.isoformat(),
            "Forecast Finish": fv.release_date.isoformat(),
            "Duration": 0,
        }))
    return rows
```

- [ ] **Step 4: Run gantt tests**

```bash
python -m pytest tests/test_gantt.py -q
```
Expected: PASS.

- [ ] **Step 5: Wire gantt cells into `issues_sheet`**

Do **not** add a top-level import of `gantt` in `sheets.py`: `gantt.py` imports `Row` from `sheets.py`, so a top-level import would be circular. Import lazily inside `issues_sheet` instead (by the time `issues_sheet` runs, `sheets.py` is fully loaded, so `gantt.py`'s `from tentpole.sheets import Row` resolves cleanly).

In `issues_sheet`, when `gantt=True`, merge the gantt cells into each row's cells and append milestone rows. At the end of `issues_sheet`, before `return SheetSpec("issues", rows)`, add:

```python
    if gantt:
        from tentpole.gantt import gantt_cells, milestone_rows
        gcells = gantt_cells(bundle)
        for row in rows:
            row.cells.update(gcells.get(row.key, {}))
        rows.extend(milestone_rows(bundle))
```

Because gantt cells are only *some* of `GANTT_COLUMNS` per row (write-never omits the rest), the gantt-mode issues rows are intentionally NOT subject to the exact-column conformance invariant (which runs in non-gantt mode only, Task 7 Step 4).

- [ ] **Step 6: Add a gantt-mode sheet test**

Append to `tests/test_sheets_issues.py`:

```python
def test_issues_sheet_gantt_mode_adds_cells_and_milestones(make_bundle):
    from datetime import date as _date
    from tentpole.model import FixVersion
    b = make_bundle(
        issues=[_task("T-1", remaining_estimate_days=3.0)],
        fix_versions=[FixVersion("v1", release_date=_date(2026, 9, 1))])
    spec = issues_sheet(b, assemble(b), gantt=True)
    rows = {r.key: r for r in spec.rows}
    assert rows["T-1"].cells["Duration"] == 3.0
    assert "milestone:v1" in rows
    assert rows["milestone:v1"].cells["Duration"] == 0
```

- [ ] **Step 7: Run + full suite + commit**

```bash
python -m pytest tests/test_gantt.py tests/test_sheets_issues.py -q
python -m pytest -q 2>&1 | tail -1     # Expected: prior + 12
git add src/tentpole/gantt.py src/tentpole/sheets.py tests/test_gantt.py tests/test_sheets_issues.py
git commit -m "feat: gantt seeding, curated arrows, cycle-breaking, milestones (spec §6)"
```

**Delta: +12** (11 gantt/sheet tests + the epic-blocks-as-Flags test).

---

## Task 9: Gantt push — column pre-flight, predecessor encoding, write-never diffing (spec §6)

The adapter side. When the issues sheet is gantt-enabled, **pre-flight** that the five gantt columns exist and the `Forecast Start`/`Forecast Finish` pair is designated (else an actionable error before any write). Translate the core's canonical `Predecessors` string (comma-separated blocker keys) into Smartsheet's predecessor cell encoding on write. Prove that engine-computed forecast dates differing from seeds produce **zero updates** (the write-never regression).

**Everything shape-sensitive here is UNVERIFIED and behind the `http` seam with documented-shape fixtures** — the designated-column check, the `PREDECESSOR_LIST` cell object, and the row-number references. The README (Task 10) marks all of it smoke-before-trust. If the live predecessor decode is not yet implemented, predecessors re-write every run (harmless, but noted).

**Files:**
- Modify: `src/tentpole/adapters/smartsheet_load.py` — gantt pre-flight; predecessor encoding in `_cells_payload`/`push_plan`
- Test: `tests/test_smartsheet_push.py` (append)

**Interfaces:**
- Produces:
  - `gantt_preflight(schema, sheet_id, col_ids, project_settings) -> str | None` — returns an actionable error string (or `None`) when gantt is enabled but a gantt column is missing or the forecast pair is not the designated start/end.
  - Predecessor translation: when a change's cells include `"Predecessors"` (a canonical string) and the sheet is gantt-enabled, `push_plan` encodes it as the API predecessor object using the target rows' row ids; otherwise the string passes through unchanged.

- [ ] **Step 1: Write the failing pre-flight test (documented shape)**

Append to `tests/test_smartsheet_push.py`:

```python
from tentpole.adapters.smartsheet_load import gantt_preflight  # noqa: E402


def _gantt_cols():
    # A gantt-enabled issues sheet. COLS already carries the five rollup
    # columns (Task 1) and First Planned (Task 5); add only the five gantt
    # columns so titles aren't duplicated.
    cols = list(COLS["columns"])
    next_id = 60
    for title in ["Forecast Start", "Forecast Finish", "Duration",
                  "Predecessors", "Flags"]:
        cols.append({"id": next_id, "title": title})
        next_id += 1
    return cols


def test_gantt_preflight_ok_when_columns_present_and_designated():
    from tentpole.schema import SCHEMAS
    col_ids = {c["title"]: c["id"] for c in _gantt_cols()}
    project_settings = {"startDateColumnId": col_ids["Forecast Start"],
                        "endDateColumnId": col_ids["Forecast Finish"]}
    assert gantt_preflight(SCHEMAS["issues"], 111, col_ids,
                           project_settings) is None


def test_gantt_preflight_errors_on_missing_gantt_column():
    from tentpole.schema import SCHEMAS
    col_ids = {c["title"]: c["id"] for c in _gantt_cols()
               if c["title"] != "Predecessors"}
    ps = {"startDateColumnId": col_ids["Forecast Start"],
          "endDateColumnId": col_ids["Forecast Finish"]}
    problem = gantt_preflight(SCHEMAS["issues"], 111, col_ids, ps)
    assert problem is not None and "Predecessors" in problem


def test_gantt_preflight_errors_when_forecast_not_designated():
    from tentpole.schema import SCHEMAS
    col_ids = {c["title"]: c["id"] for c in _gantt_cols()}
    ps = {"startDateColumnId": 999, "endDateColumnId": 998}   # wrong columns
    problem = gantt_preflight(SCHEMAS["issues"], 111, col_ids, ps)
    assert problem is not None and "designated" in problem.lower()
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_smartsheet_push.py -k gantt_preflight -q
```
Expected: FAIL — `cannot import name 'gantt_preflight'`.

- [ ] **Step 3: Add `gantt_preflight`**

In `src/tentpole/adapters/smartsheet_load.py`, add (near `_validate_columns`):

```python
from tentpole.schema import GANTT_COLUMNS  # add to the existing schema import


def gantt_preflight(schema, sheet_id: int, col_ids: dict,
                    project_settings: dict) -> str | None:
    # Spec §6: when dependencies are enabled, the five gantt columns must
    # exist and Forecast Start/Finish must be the designated date pair, else
    # an actionable error BEFORE any write. Shapes UNVERIFIED (smoke first).
    missing = [c for c in GANTT_COLUMNS if c not in col_ids]
    if missing:
        return (f"sheet {schema.name!r} (id {sheet_id}) has dependencies "
                f"enabled (gantt mode) but is missing gantt column(s) "
                f"{missing}. Add them exactly as named by `tentpole schema "
                f"show`, or turn off the sheet's dependency setting.")
    want_start = col_ids.get("Forecast Start")
    want_end = col_ids.get("Forecast Finish")
    if (project_settings.get("startDateColumnId") != want_start
            or project_settings.get("endDateColumnId") != want_end):
        return (f"sheet {schema.name!r} (id {sheet_id}): gantt mode requires "
                f"'Forecast Start' and 'Forecast Finish' to be the "
                f"designated start/end date columns in project settings. "
                f"Designate them in the Smartsheet UI (the API cannot).")
    return None
```

(Import note: `smartsheet_load.py` already does `from tentpole.schema import SCHEMAS, SheetSchema` — extend it to `from tentpole.schema import GANTT_COLUMNS, SCHEMAS, SheetSchema`.)

- [ ] **Step 4: Wire pre-flight + predecessor encoding into the push path (documented-shape, seam-injected)**

The full wiring — reading `dependenciesEnabled`/`projectSettings` from the live `GET /sheets/{id}` during `push_plans`, calling `gantt_preflight` for the issues sheet, and encoding `Predecessors` — is shape-sensitive. Implement it guarded so a non-gantt sheet path is byte-identical to today.

In `push_plans`, after the column pre-flight loop and before writing, add a gantt pre-flight for the issues target when the sheet reports dependencies enabled. Extend the per-target pre-flight to also fetch settings for `issues`:

```python
    # Gantt pre-flight (spec §6): only for an issues sheet with dependencies
    # enabled. The GET response shape (dependenciesEnabled, projectSettings,
    # designated column ids) is UNVERIFIED -- smoke before trusting.
    for name, schema, _plan, sheet_id in targets:
        if name != "issues":
            continue
        data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
        enabled = bool(data.get("dependenciesEnabled")
                       or data.get("projectSettings", {})
                       .get("dependenciesEnabled"))
        if enabled:
            problem = gantt_preflight(
                schema, sheet_id, col_ids_by_name[name],
                data.get("projectSettings", {}))
            if problem:
                raise ValueError(problem)
```

Predecessor encoding: the core emits `Predecessors` as `"B-1, B-2"`. On a gantt-enabled issues sheet, the adapter must translate that into the API predecessor object referencing the target rows' ids. Because the exact object shape is unverified, encapsulate it in one function and call it only when writing the issues sheet in gantt mode. Add:

```python
def _encode_predecessors(value: str, row_ids: dict[str, int]) -> dict:
    # UNVERIFIED shape (spec §6, live-smoke item): Smartsheet predecessor
    # cell as an objectValue PREDECESSOR_LIST of {rowId} references. Keys
    # not resolvable to a row id are skipped (their arrow simply won't draw
    # until both rows exist -- a self-healing next run).
    predecessors = []
    for key in [k.strip() for k in value.split(",") if k.strip()]:
        if key in row_ids:
            predecessors.append({"rowId": row_ids[key]})
    return {"objectType": "PREDECESSOR_LIST", "predecessors": predecessors}
```

This function is unit-tested below against its documented shape; wiring it into `_cells_payload` requires threading `row_ids` and a gantt flag into `_cells_payload`, which is a larger change. Given the shape is unverified, keep the wiring minimal and explicit: the plan documents the function and its test; the live push wiring (replacing the `"Predecessors"` string with `_encode_predecessors(...)` in the add/update payloads for a gantt issues sheet) is completed during the SmartsheetGov smoke, when the real cell shape is confirmed. **Mark this clearly in code and README as smoke-gated.**

- [ ] **Step 5: Write the predecessor-encoding + write-never tests**

Append to `tests/test_smartsheet_push.py`:

```python
def test_encode_predecessors_documented_shape():
    from tentpole.adapters.smartsheet_load import _encode_predecessors
    row_ids = {"B-1": 900, "B-2": 901}
    obj = _encode_predecessors("B-1, B-2, GHOST", row_ids)
    assert obj["objectType"] == "PREDECESSOR_LIST"
    assert obj["predecessors"] == [{"rowId": 900}, {"rowId": 901}]  # GHOST skipped
```

The write-never regression test needs `plan_changes` to be gantt-aware first (gantt columns are `synced=True, gantt=True`, so `synced_names()` with no argument excludes them — they must be diffed only in gantt mode). Step 6 makes that change and adds the write-never test.

- [ ] **Step 6: Make `plan_changes` gantt-aware**

For gantt columns to be written at all, `plan_changes` must include them when planning the issues sheet in gantt mode. Add a `gantt` parameter:

In `src/tentpole/changeplan.py`, change `plan_changes` signature and the `synced` set:

```python
def plan_changes(spec: SheetSpec, current: dict[str, dict],
                 schema: SheetSchema, gantt: bool = False) -> list[Change]:
    if schema.owned != "machine":
        raise ValueError(
            f"refusing to plan changes for human-owned sheet "
            f"'{schema.name}'")
    if spec.sheet != schema.name:
        raise ValueError(
            f"spec sheet '{spec.sheet}' does not match schema "
            f"'{schema.name}'")
    synced = set(schema.synced_names(gantt=gantt))
    ...
```

(The rest of the function is unchanged. When `gantt=True`, gantt columns are in `synced`, so seeded gantt cells diff and write; omitted ones — write-never — are simply absent from `spec.cells` and never diffed. This is exactly the write-never behavior.)

In `src/tentpole/sync.py`, pass `gantt` to `plan_changes` for the issues sheet:

```python
    plans = {
        name: plan_changes(spec, current.get(name, {}), SCHEMAS[name],
                           gantt=(gantt and name == "issues"))
        for name, spec in specs.items()
    }
```

Now correct the write-never test from Step 5 to call `plan_changes(..., gantt=True)`:

```python
def test_write_never_engine_dates_produce_zero_updates():
    from tentpole.changeplan import plan_changes
    from tentpole.sheets import SheetSpec, Row
    from tentpole.schema import SCHEMAS
    spec_cells = {"Key": "T-1", "In Jira": True, "Duration": 3.0,
                  "Predecessors": "B-1"}   # NO Forecast Start (write-never)
    spec = SheetSpec("issues", [Row("T-1", spec_cells)])
    current = {"Key": "T-1", "In Jira": True, "Duration": 3.0,
               "Predecessors": "B-1", "Forecast Start": "2026-08-15"}
    changes = plan_changes(spec, {"T-1": current}, SCHEMAS["issues"],
                           gantt=True)
    assert changes == []
```

- [ ] **Step 7: Run + full suite + commit**

```bash
python -m pytest tests/test_smartsheet_push.py -k "gantt or predecessor or write_never" -q
python -m pytest -q 2>&1 | tail -1     # Expected: green (+5 vs previous total)
git add src/tentpole/adapters/smartsheet_load.py src/tentpole/changeplan.py src/tentpole/sync.py tests/test_smartsheet_push.py
git commit -m "feat: gantt pre-flight, predecessor encoding, write-never diffing (spec §6)"
```

**Delta: +5.**

---

## Task 10: Cadence + inter-team README, and the 0.5.0 version bump (spec §6, §7)

Document the planning cadence, the draft-then-polish contract, the link-hygiene loop, the baseline/archive planning-close ritual, gantt mode setup (with smoke-before-trust), and the inter-team linkage contract. Bump to 0.5.0.

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml` — `0.4.0 → 0.5.0`

- [ ] **Step 1: Add a "Planning cadence and the human loop" section**

In `README.md`, after the "The people sheet" section (added in 5a), add:

```markdown
## Planning cadence and the human loop

tentpole is a planning-week instrument, run at period boundaries (the team
plans every sixty days) and ad hoc — not a cron daemon. Estimates
propagate to sister teams only at planning boundaries, so what they see is
the plan of record, not a moving target.

**Draft, then polish.** `push` produces a draft plan-of-record. During
planning week, humans polish the sheet directly — delete an arrow the
engine drew from a technically-true-but-unhelpful link, nudge a bar,
annotate. Those edits persist for the whole period because nothing runs
behind them. The next planning period regenerates the draft from fresh
Jira and the polish ritual repeats: tentpole does the mechanical 95%;
judgment is applied to a fresh draft each period, never maintained as
overlay state.

**Prune links in Jira, not in an overlay.** Extract surfaces link-hygiene
findings — cycle members (naming the edge that would be dropped),
blocks-links into done work, links to out-of-scope targets — so links get
fixed at the source. There is deliberately no exclusions file (a second
source of truth that drifts).

**Recommended planning-week loop:** extract → review the link report →
fix links in Jira → re-extract → sync → push → polish in the sheet.

**At the next boundary**, re-planning is a diff, not a rebuild: persisting
tickets update in place (row identity survives, so sister-team cell links
keep working), new work is added, out-of-scope rows are deleted, forecasts
re-seed, and the engine re-chains. Two consequences: polish does not carry
over (an arrow you deleted returns if its Jira blocks-link still exists —
pruning that should persist belongs in Jira), and **planning close is a
two-click ritual: set a Smartsheet baseline, then Save-as-New an archive
copy named for the period.** The baseline gives the live chart its
ghost-bar memory; the archive is the inert frozen plan of record; the live
sheet is always the current plan. (A `tentpole archive` command may
automate the copy later — not 0.5.0 scope.)

**Between-plan memory in the data** is automatic: snapshot records widen
with `epic_key`/`program`, a ticket-level carryover check flags a ticket
that was sprint-planned, isn't done, and is sprint-planned again across the
last two runs, and the `First Planned` column dates each ticket's earliest
sprinted run so chronic drifters sort to the top.
```

- [ ] **Step 2: Add a "Gantt mode" section**

Add:

```markdown
## Gantt mode (experimental)

Gantt mode is on when the `issues` sheet has Smartsheet **dependencies
enabled** — there is no config key (consistent with existence-as-config).
With dependencies off, the sheet behaves exactly as the epic-rollup issues
sheet and the gantt columns are not required.

When on, tentpole seeds five columns distinct from the factual
`In Progress`/`Done` mirror dates — `Forecast Start`, `Forecast Finish`,
`Duration`, `Predecessors`, `Flags` — and Smartsheet's engine chains the
bars and draws the arrows. Facts and forecast coexist as separate columns;
the engine never touches `In Progress`/`Done`. Engine-derived cells
(forecast dates on predecessor'd rows, epic rollups) are pulled but never
written and never diffed.

Seeding by status: unstarted tickets with an included incoming arrow get
`Duration` + `Predecessors` (the engine chains their start); roots get
`Forecast Start` + `Duration`; started tickets anchor at their actual start
with incoming arrows dropped; done tickets bar from actuals. An edge
becomes an arrow only if it is a Jira blocks-link between two in-scope,
non-done tickets whose target has not started and it survived deterministic
cycle-breaking (highest-sorted edge dropped, named in both rows' `Flags`).
External/cross-team edges render as `Flags` text. Missing estimates default
to 1d with a flag. Unreleased fixVersions become synthetic zero-duration
`milestone:<version>` diamond rows.

Between-plan memory on the chart comes from **Smartsheet baselines** set at
planning close, not from stretching bars.

**One-time UI setup (the API cannot do it):** enable dependencies on the
sheet and designate `Forecast Start`/`Forecast Finish` as the project
start/end date columns. `push` pre-flights this and refuses with an
actionable error if a gantt column is missing or the pair is not
designated.

**Smoke before you trust it.** Workspace discovery, `bootstrap --sheets`,
and especially the gantt dependency-toggle detection, the designated-column
pre-flight, and the predecessor cell encoding are shape-sensitive and
unverified against SmartsheetGov. Run one real `pull`/`push` cycle on a
throwaway sheet and confirm the arrows, milestones, and baseline behave
before wiring gantt mode into your planning loop.

### Inter-team linkage

Sister teams reference the mirror `issues` sheet, whose change plan updates
rows in place — a row's identity survives every sync, so cell links and
formulas pointing at it keep working across planning periods. The sturdiest
pattern: cross-sheet formulas keyed on the `Key` column (INDEX/MATCH
against `issues`), which survive even a row's delete-and-recreate. Inbound
dependency detail stays on the opt-in `dependencies` sheet; estimates
propagate outward only at planning boundaries, so sister teams always see
the plan of record.
```

- [ ] **Step 3: Bump the version**

In `pyproject.toml`, change `version = "0.4.0"` to `version = "0.5.0"`.

- [ ] **Step 4: Sanity checks**

```bash
grep -n "Gantt mode\|Planning cadence\|baseline\|smoke before" README.md | head
grep -n 'version = "0.5.0"' pyproject.toml
```
Expected: matches present.

- [ ] **Step 5: Full suite + final verification**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: all green (BASE + total 5b deltas). Confirm the version:

```bash
python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
```
Expected: `0.5.0`.

- [ ] **Step 6: Commit**

```bash
git add README.md pyproject.toml
git commit -m "docs: cadence, gantt mode, inter-team contract; bump 0.5.0 (spec §6, §7)"
```

**Delta: 0. Plan 5b complete; 0.5.0 shipped.**

---

## 5b Self-Review

1. **Spec coverage (§5, §6, §7, §9):**
   - §5 epic/issue merge (five rollups on epic rows; epics schema/builder/state retired; equivalence pin; epics-fold hint) → Tasks 1, 2 ✓.
   - §6 gantt (dependenciesEnabled toggle; five gantt columns + Flags; write-never via seeder omission + gantt-aware `plan_changes`; seeding by status; curated arrow subset; deterministic cycle-breaking with Flags naming; milestone rows; pre-flight; inter-team contract; baselines documented) → Tasks 7, 8, 9, 10 ✓.
   - §7 cadence docs; link-hygiene findings (cycle/stale-done/out-of-scope); widened snapshots; ticket-level carryover; First Planned; prior snapshots as CLI-loaded sync input → Tasks 3, 4, 5, 6, 10 ✓.
   - §9 inventory (seven schemas; epics gone) → Task 2 ✓.
2. **Placeholder scan:** every code step shows complete code; every test step shows assertions; every command has an expected result. The one deliberately smoke-gated item (live predecessor-cell **wiring** into the push payload) is called out explicitly with its unit-tested `_encode_predecessors` function and a documented shape — flagged, not hand-waved.
3. **Type consistency:** `gantt_cells(bundle) -> dict[str, dict]`; `milestone_rows(bundle) -> list[Row]`; `blocks_edges`/`break_cycles` shared in `linkgraph`; `carryover(bundle, prior_snapshots)`; `Finding.epic_key`; `run_sync(bundle, rules, current, prior_snapshots=None, gantt=False)`; `build_sheetspecs`/`issues_sheet` carry `prior_snapshots` then `gantt`; `plan_changes(..., gantt=False)`; `gantt_preflight(schema, sheet_id, col_ids, project_settings)`; `GANTT_COLUMNS` in `schema.py`. Signatures introduced in a task match every later call site.

### Flagged spec ambiguities (surfaced, not silently resolved)
- **§6 "four gantt columns" vs the five listed** (`Forecast Start`, `Forecast Finish`, `Duration`, `Predecessors`, `Flags`). Implemented all five; pre-flight requires all five plus the designated pair. Confirm during smoke.
- **`dependenciesEnabled` field name and `projectSettings` designated-column shape are unverified.** Detection falls back to `False` (non-gantt = §5 behavior) so an absent/renamed field degrades safely; pre-flight and predecessor encoding are behind the `http` seam with documented fixtures and a README smoke caveat.
- **Predecessor cell encoding is unverified.** `_encode_predecessors` is unit-tested against a documented `PREDECESSOR_LIST` shape; the final substitution into the live push payload is smoke-gated (until then predecessors re-write each run — harmless).
