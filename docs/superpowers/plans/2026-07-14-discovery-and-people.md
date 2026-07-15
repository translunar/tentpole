# Discovery and People Implementation Plan (0.5.0, Plan 5a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce tentpole's Smartsheet setup burden — sheets resolve by name inside a workspace (existence is the config), one human "people" sheet replaces `team` + `exceptions` and carries recurring non-Jira burden, and a pull-state keying fix makes duplicate primaries fail loud instead of silently merging.

**Architecture:** Three edits to the pure core (a new `recurring_days` config field + a capacity rule that avoids double-counting recurring burden; a hierarchical people-sheet parser; a run-report that enumerates every schema's resolution) plus adapter-edge changes (parent-qualified pull keys, workspace name resolution, an `expect:` strictness opt-in, `bootstrap --sheets`). Jira remains the sole authoring surface; the sync stays one-way.

**Tech Stack:** Python 3.11+, stdlib + PyYAML only. pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-14-simplify-sheets-design.md` — §2 (sheet selection/name resolution), §3 (people sheet), §4 (capacity double-count rule), §8 (pull-state keying), §10/§12 (config summary, decisions). Every §-numbered decision there is settled.

## Global Constraints

Copy these into every task's mental checklist; they are not restated per task.

- **Pure core.** No I/O and no clock under `src/tentpole/` except `model.load_bundle`, `hygiene.load_rules`, `cli.py`, and everything under `adapters/`. `date.today()` appears only in adapters.
- **Fail loud but actionable.** Every rejection is a `ValueError` (or, at a CLI edge, an `ERROR:` line + exit 1) whose message names the sheet, the row, and the offending value, and says what to do. Never coerce a bad human-edited cell to a default — silent understatement of demand is the exact failure class this tool exists to prevent.
- **stdlib + pyyaml only.** No new third-party dependencies.
- **Append-only tests.** Add new test functions; do not edit or delete existing ones **except** at the sites this plan explicitly sanctions (each is called out inline as **SANCTIONED EDIT** with the exact before/after). The full sanctioned-edit list for 5a:
  1. `tests/test_schema.py` — `test_registry_has_all_sheets_with_ownership` and `test_human_sheets_have_no_synced_columns` (schema registry changes, Task 4).
  2. `tests/test_humansheets.py` — replace the `team_from_sheet` and `exceptions_from_sheet` test functions with people-sheet equivalents (Task 5); the 0.3.0 team-sheet *semantics* (ordering, blank-skip, duplicate-raise, present-but-empty authoritative) are **preserved by porting**, not deleted.
  3. `tests/test_cli_sync.py` — `test_sync_team_sheet_overrides_bundle_config`, `test_sync_emptied_team_sheet_drops_stale_bundle_roster`, `test_sync_emptied_exceptions_sheet_drops_stale_bundle_exception` (rewired to the people sheet, Task 6).
  4. `tests/test_smartsheet_push.py` (Task 7) — three edits: `test_push_plans_skips_sheet_without_configured_id` and `test_cli_push_missing_sheet_id_exits_nonzero` (the SKIPPED+exit-1 behavior is removed and replaced with OFF/enumeration); and `test_cli_push_exits_nonzero_on_failures`'s stubbed `push_plans` return dict (fixture correction — it must carry the new `state`/`sheet_id` keys `_push` now reads).
  5. `tests/test_pull_state_writes_files` in `tests/test_smartsheet_pull.py` (Task 7) — `pull_state` now returns a per-schema resolution report (`{name: {"state", "sheet_id", "owned"}}`) instead of a `list[str]`, so this test asserts on `report["issues"]["state"]` rather than `pulled == ["issues"]`.
  6. `tests/test_bootstrap.py` (Task 8) — `test_cli_bootstrap_prints_config_snippet`'s monkeypatch lambda signature (fixture correction — `_bootstrap` now calls `bootstrap(cfg, names=names)`, so the stub must accept `names=None`).

  Not sanctioned — must stay green **unchanged**: `test_pull_state_rejects_unknown_sheet_name` (the unknown-explicit-key guard is preserved, moved into `resolve_sheets`, Task 7).
- **No version bump in 5a.** 0.5.0 ships only after Plan 5b (gantt + memory). `pyproject.toml` stays at `0.4.0` through this plan.
- **Test baseline: 225 passing** (v0.4.0, commit `eac3c4d`). Each task states the running total. Verify the baseline before starting:

```bash
cd /Users/juno/Projects/jira-smartsheet
source .venv/bin/activate 2>/dev/null || true
python -m pytest -q 2>&1 | tail -1
# Expected: 225 passed
```

---

## Task 1: Parent-qualified pull-state keys (spec §8)

Closes the filed 0.3.0 bug: `pull_sheet` keys state by primary-column value, so two future_work rows both titled "Migrate DB" silently collapse to one (demand understated). It is also the prerequisite for the people sheet, where ada's "PTO" child and grace's "PTO" child are the common case.

**IMPORTANT DESIGN NOTE — a spec tension resolved here.** §8 says "state key = `f"{parent_primary}|{primary}"` for rows with a parent, bare primary for roots… uniform for all sheets." §11 says "machine-sheet pulls byte-identical to today." These are in literal conflict for the one hierarchical *machine* sheet, `issues` (epics with nested tickets): qualifying its child keys to `E-1|T-1` would make change-planning re-`add` every child, because spec rows there are keyed by the bare issue key (`sheets.issues_sheet` sets `Row(i.key, ..., parent_key=epic.key)` and `changeplan.plan_changes` matches on `row.key`). We resolve in favor of §11: **qualify child keys only for human-owned sheets** (people, future_work); machine sheets keep today's bare keying byte-for-byte. The duplicate-key **raise** is active on every sheet (it never fires for machine sheets, whose primaries are unique by construction). This closes the future_work bug (human sheet, duplicate roots raise) and enables people children, while leaving `issues` pull output unchanged. *(Flagged to the team lead as a §8/§11 conflict.)*

**Files:**
- Modify: `src/tentpole/adapters/smartsheet_load.py` — `pull_sheet` (lines 25-51), `pull_state` (lines 54-67)
- Test: `tests/test_smartsheet_pull.py` (append)

**Interfaces:**
- Produces: `pull_sheet(cfg, sheet_id, http=request, *, sheet_name=None, human=False) -> dict[str, dict]`. When `human=True`, a row with a parent is keyed `f"{parent_primary}|{primary}"`; otherwise bare primary. A duplicate final key raises `ValueError`. `_parent` still stores the parent's bare primary value (unchanged contract for change-planning). `pull_state` passes `human = SCHEMAS[name].owned == "human"` and `sheet_name=name`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smartsheet_pull.py`:

```python
def test_pull_sheet_human_qualifies_child_keys(fake_http):
    # A people-shaped sheet: two people each with a "PTO" child. Bare-primary
    # keying would collapse both PTO rows; parent-qualified keying keeps them.
    sheet = {
        "columns": [
            {"id": 1, "title": "Item", "primary": True},
            {"id": 2, "title": "Days"},
        ],
        "rows": [
            {"id": 100, "cells": [{"columnId": 1, "value": "ada"}]},
            {"id": 101, "parentId": 100,
             "cells": [{"columnId": 1, "value": "PTO"},
                       {"columnId": 2, "value": 4}]},
            {"id": 200, "cells": [{"columnId": 1, "value": "grace"}]},
            {"id": 201, "parentId": 200,
             "cells": [{"columnId": 1, "value": "PTO"},
                       {"columnId": 2, "value": 2}]},
        ],
    }
    fake_http.add("GET", "/sheets/55", sheet)
    state = pull_sheet(CFG, 55, http=fake_http, sheet_name="people",
                       human=True)
    assert set(state) == {"ada", "grace", "ada|PTO", "grace|PTO"}
    assert state["ada|PTO"]["Days"] == 4
    assert state["ada|PTO"]["_parent"] == "ada"
    assert state["grace|PTO"]["Days"] == 2


def test_pull_sheet_human_duplicate_key_raises(fake_http):
    # Two roots with the same primary (the filed future_work "Migrate DB" bug).
    sheet = {
        "columns": [{"id": 1, "title": "Title", "primary": True}],
        "rows": [
            {"id": 1, "cells": [{"columnId": 1, "value": "Migrate DB"}]},
            {"id": 2, "cells": [{"columnId": 1, "value": "Migrate DB"}]},
        ],
    }
    fake_http.add("GET", "/sheets/55", sheet)
    with pytest.raises(ValueError, match="Migrate DB"):
        pull_sheet(CFG, 55, http=fake_http, sheet_name="future_work",
                   human=True)


def test_pull_sheet_human_duplicate_child_pair_raises(fake_http):
    # Same (person, item) twice -> duplicate qualified key "ada|PTO".
    sheet = {
        "columns": [{"id": 1, "title": "Item", "primary": True}],
        "rows": [
            {"id": 100, "cells": [{"columnId": 1, "value": "ada"}]},
            {"id": 101, "parentId": 100,
             "cells": [{"columnId": 1, "value": "PTO"}]},
            {"id": 102, "parentId": 100,
             "cells": [{"columnId": 1, "value": "PTO"}]},
        ],
    }
    fake_http.add("GET", "/sheets/55", sheet)
    with pytest.raises(ValueError, match="ada.PTO"):
        pull_sheet(CFG, 55, http=fake_http, sheet_name="people", human=True)


def test_pull_sheet_machine_keys_stay_bare_and_byte_identical(fake_http):
    # Machine sheet (human=False, the default): children keep bare keys so
    # change-planning against issues is unaffected (spec §11).
    fake_http.add("GET", "/sheets/111", SHEET)
    state = pull_sheet(CFG, 111, http=fake_http)
    assert set(state) == {"E-1", "T-1"}          # NOT "E-1|T-1"
    assert state["T-1"]["_parent"] == "E-1"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/test_smartsheet_pull.py -k "human or byte_identical" -q
```
Expected: FAIL — `pull_sheet() got an unexpected keyword argument 'sheet_name'`.

- [ ] **Step 3: Rewrite `pull_sheet` and `pull_state`**

Replace `pull_sheet` (lines 25-51) with:

```python
def pull_sheet(cfg, sheet_id: int, http=request, *, sheet_name=None,
               human: bool = False) -> dict[str, dict]:
    data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
    columns = data.get("columns", [])
    titles = {c["id"]: c["title"] for c in columns}
    primary_id = next(c["id"] for c in columns if c.get("primary"))
    primary_by_row_id = {}
    parsed = []                      # (row_id, primary, cells, parent_row_id)
    for row in data.get("rows", []):
        cells = {}
        primary = None
        for cell in row.get("cells", []):
            value = cell.get("value")
            if cell["columnId"] == primary_id and value is not None:
                primary = str(value)
            title = titles.get(cell["columnId"])
            if title is not None and value is not None:
                cells[title] = value
        if primary is None:
            continue   # keyless row: nothing the planner can address
        cells["_row_id"] = row["id"]
        primary_by_row_id[row["id"]] = primary
        parsed.append((row["id"], primary, cells, row.get("parentId")))
    state = {}
    label = sheet_name if sheet_name is not None else sheet_id
    for _row_id, primary, cells, parent_row_id in parsed:
        parent_primary = primary_by_row_id.get(parent_row_id)
        cells["_parent"] = parent_primary
        # Human sheets (people, future_work) can legitimately repeat a
        # primary across parents (ada's "PTO" and grace's "PTO"); qualify
        # their child keys so both survive. Machine sheets keep bare keys
        # (spec §11: byte-identical pulls -- their primaries are unique).
        if human and parent_primary is not None:
            key = f"{parent_primary}|{primary}"
        else:
            key = primary
        if key in state:
            # A duplicate after qualification is always a human error;
            # silent merge understates demand (the future_work bug) or
            # drops a burden. Fail loud (spec §8).
            raise ValueError(
                f"sheet {label!r}: two rows resolve to the same key "
                f"{key!r} -- rename one so each row is unique (a duplicate "
                f"primary would silently merge in pull state)")
        state[key] = cells
    return state
```

Replace `pull_state` (lines 54-67) with:

```python
def pull_state(cfg, state_dir: Path, http=request) -> list[str]:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    pulled = []
    for name in sorted(cfg.sheets):
        if name not in SCHEMAS:
            raise ValueError(
                f"unknown sheet {name!r} in config "
                f"(known: {sorted(SCHEMAS)})")
        state = pull_sheet(cfg, cfg.sheets[name], http=http,
                           sheet_name=name,
                           human=SCHEMAS[name].owned == "human")
        (state_dir / f"{name}.json").write_text(
            json.dumps(state, indent=2))
        pulled.append(name)
    return pulled
```

(Task 7 will replace `cfg.sheets` iteration here with name resolution; the `human=` wiring stays.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/test_smartsheet_pull.py -q
```
Expected: PASS (existing + 4 new).

- [ ] **Step 5: Run the full suite (no regressions)**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: `229 passed` (225 + 4).

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/adapters/smartsheet_load.py tests/test_smartsheet_pull.py
git commit -m "fix: parent-qualify human-sheet pull keys; duplicate raises (spec §8)"
```

**Running total: 229.**

---

## Task 2: `recurring_days` config field and yaml map-form team (spec §3)

`Config.team: list[str]` is unchanged. Add `Config.recurring_days: dict[str, float]` (person → summed recurring days/sprint). The 0.1.x list form `team: [ada, grace]` stays roster-only; the new map form `team: {ada: {}, grace: {ops rotation: 2}}` adds recurring burden. Normalization happens in `load_bundle` (a sanctioned I/O point) so `Config` never sees the map.

**Files:**
- Modify: `src/tentpole/model.py` — `Config` (add field, ~line 85), `load_bundle` (config assembly, ~lines 162-172)
- Test: `tests/test_model.py` (append)

**Interfaces:**
- Produces: `Config.recurring_days: dict[str, float]` (default `{}`). `load_bundle` maps `config.json`'s `team` when it is a dict: `team` becomes the ordered keys, `recurring_days[person]` becomes the sum of that person's `{label: days}` values (labels are documentation; the math needs only the sum). A list `team` yields `recurring_days == {}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_model.py`:

```python
def test_config_recurring_days_defaults_empty():
    from tentpole.model import Config
    assert Config(team=["ada"]).recurring_days == {}


def test_load_bundle_team_map_form_splits_roster_and_recurring(tmp_path):
    import json
    from tentpole.model import load_bundle
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (tmp_path / "config.json").write_text(json.dumps({
        "team": {"ada": {}, "grace": {"ops rotation": 2, "lead": 0.5}}}))
    b = load_bundle(tmp_path)
    assert b.config.team == ["ada", "grace"]           # roster = keys
    assert b.config.recurring_days == {"ada": 0.0, "grace": 2.5}  # summed


def test_load_bundle_team_list_form_unchanged(tmp_path):
    import json
    from tentpole.model import load_bundle
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (tmp_path / "config.json").write_text(json.dumps({"team": ["ada", "grace"]}))
    b = load_bundle(tmp_path)
    assert b.config.team == ["ada", "grace"]
    assert b.config.recurring_days == {}
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_model.py -k "recurring or team_map or team_list" -q
```
Expected: FAIL — `Config.__init__() got an unexpected keyword argument 'recurring_days'` / `AttributeError: recurring_days`.

- [ ] **Step 3: Add the field**

In `src/tentpole/model.py`, in `Config`, immediately after the `team` field (line 85) add:

```python
    recurring_days: dict[str, float] = field(default_factory=dict)
```

(`field` is already imported at the top: `from dataclasses import dataclass, field`.)

- [ ] **Step 4: Normalize the map form in `load_bundle`**

In `src/tentpole/model.py`, in `load_bundle`, replace the block:

```python
    config_raw = _load_json(path / "config.json", {})
    if "overhead_summary_patterns" in config_raw:
        config_raw["overhead_summary_patterns"] = tuple(
            config_raw["overhead_summary_patterns"])
```

with:

```python
    config_raw = _load_json(path / "config.json", {})
    if "overhead_summary_patterns" in config_raw:
        config_raw["overhead_summary_patterns"] = tuple(
            config_raw["overhead_summary_patterns"])
    team_raw = config_raw.get("team")
    if isinstance(team_raw, dict):
        # Map form (spec §3): keys are the roster; each value is a
        # {label: days} dict of recurring burden. Labels are documentation;
        # the capacity math needs only the per-person sum.
        config_raw["team"] = list(team_raw)
        config_raw["recurring_days"] = {
            person: float(sum((burden or {}).values()))
            for person, burden in team_raw.items()
        }
```

- [ ] **Step 5: Run to verify pass**

```bash
python -m pytest tests/test_model.py -q
```
Expected: PASS.

- [ ] **Step 6: Full suite**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: `232 passed` (229 + 3).

- [ ] **Step 7: Commit**

```bash
git add src/tentpole/model.py tests/test_model.py
git commit -m "feat: Config.recurring_days + yaml map-form team (spec §3)"
```

**Running total: 232.**

---

## Task 3: The capacity double-count rule (spec §4)

Recurring burden must not be charged twice. `empirical()` already measures real delivery per sprint — a person carrying 2d/sprint of untracked ops **already** shows reduced empirical throughput. So recurring burden reduces capacity **only while the person's throughput comes from the prior**. All three throughput consumers — `capacity_for`, `team_subscription`'s coarse scaling, and `tentpole_runway`'s pace projection — build on the new `effective_throughput_for`. One-off exceptions always subtract from their specific sprint bucket regardless of throughput source (unchanged). The result is deliberately **not clamped**: a recurring burden exceeding the prior yields non-positive capacity, which makes every capacity check fire — loud and correct for a fully-allocated person.

`tentpole_runway` switches too (team-lead ruling, 2026-07-15, folded into spec §4): runway is a pace projection, so a prior-based person with recurring burden moves slower there as well — otherwise the runway check turns optimistic in exactly the case the feature exists for. After this task no consumer in `checks.py` uses the raw `throughput_for` (it stays in `throughput.py` for `effective_throughput_for` and the throughput tests).

**Files:**
- Modify: `src/tentpole/throughput.py` — add `effective_throughput_for`, rewire `capacity_for` (lines 42-52)
- Modify: `src/tentpole/checks.py` — import change (line 11); `team_subscription` coarse branch (lines 58-60); `tentpole_runway` call-site (line 122)
- Test: `tests/test_throughput.py`, `tests/test_checks_capacity.py` (append)

**Interfaces:**
- Consumes: `Config.recurring_days` (Task 2), `empirical`/`prior` (existing).
- Produces: `effective_throughput_for(bundle: Bundle, person: str) -> float`. `capacity_for`, `team_subscription`'s plan-bucket capacity, and `tentpole_runway`'s per-person capacity all call it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_throughput.py`:

```python
def test_effective_throughput_prior_based_loses_recurring(make_bundle):
    from tentpole.model import Config
    from tentpole.throughput import effective_throughput_for
    # No past sprints -> prior-based. Recurring burden is subtracted.
    b = make_bundle(config=Config(team=["ada"], recurring_days={"ada": 2.0}))
    assert abs(effective_throughput_for(b, "ada")
               - (prior(b.config) - 2.0)) < 1e-9


def test_effective_throughput_empirical_based_keeps_recurring(make_bundle,
                                                              make_sprints):
    from tentpole.model import Config
    from tentpole.throughput import effective_throughput_for
    # THE double-count regression test (spec §4, §11): a person whose
    # throughput is empirical already has the recurring burden baked into
    # the measurement, so it must NOT be subtracted again.
    past = make_sprints(start=date(2026, 5, 1), n=3, first_id=101)
    issues = [_done("T-1", "ada", 6.0, date(2026, 5, 5)),
              _done("T-2", "ada", 4.0, date(2026, 5, 15)),
              _done("T-3", "ada", 5.0, date(2026, 5, 25))]
    b = make_bundle(sprints=past + make_sprints(), issues=issues,
                    config=Config(team=["ada"], recurring_days={"ada": 2.0}))
    assert empirical(b, "ada") == 5.0
    assert effective_throughput_for(b, "ada") == 5.0   # NOT 3.0


def test_effective_throughput_not_clamped(make_bundle):
    from tentpole.model import Config
    from tentpole.throughput import effective_throughput_for
    # Recurring burden > prior -> non-positive, deliberately unclamped.
    b = make_bundle(config=Config(team=["ada"], recurring_days={"ada": 999.0}))
    assert effective_throughput_for(b, "ada") < 0


def test_capacity_for_uses_effective_throughput(make_bundle):
    from tentpole.model import Config
    b = make_bundle(config=Config(team=["ada"], recurring_days={"ada": 2.0}))
    bks = buckets_for(b)
    sprint1 = next(bk for bk in bks if bk.id == "sprint:1")
    # prior-based, recurring 2.0, no overhead/exceptions on the sprint.
    assert abs(capacity_for(b, "ada", sprint1, [])
               - (prior(b.config) - 2.0)) < 1e-9
```

Append to `tests/test_checks_capacity.py`:

```python
def test_team_subscription_coarse_capacity_loses_recurring(make_bundle):
    from tentpole.model import Config
    from tentpole.buckets import buckets_for
    from tentpole.checks import team_subscription
    from tentpole.demand import compile_demand
    # A ghost sized to fit under 6*prior but NOT under 6*(prior-3) for a
    # two-person team, so recurring burden flips plan+1 to over-subscribed.
    base = 2 * prior(Config()) * 6            # ~91.8
    reduced = 2 * (prior(Config()) - 3.0) * 6  # ~55.8
    size = (base + reduced) / 2               # between the two
    b = make_bundle(
        config=Config(team=["ada", "grace"],
                      recurring_days={"ada": 3.0, "grace": 3.0}),
        ghosts=[Ghost(title="G", estimate_days=size, target="plan+1")])
    bks = buckets_for(b)
    over = team_subscription(b, bks, compile_demand(b, bks))
    assert [f.bucket_id for f in over] == ["plan+1"]


def test_tentpole_runway_uses_effective_throughput(make_bundle):
    from datetime import date
    from tentpole.buckets import buckets_for
    from tentpole.checks import tentpole_runway
    from tentpole.demand import compile_demand
    from tentpole.model import Config, FixVersion, Issue
    # runway is a pace projection (team-lead ruling): a prior-based person
    # with recurring burden moves slower there too. Raw prior (~7.65d over
    # one sprint of runway) covers the epic's 6.0d -> safe; a 3d recurring
    # burden drops ada's effective throughput to ~4.65d -> AT RISK. 6.0 sits
    # between the two, pinning the boundary.
    epic = Issue(key="E-1", summary="Big epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v1"])
    t1 = Issue(key="T-1", summary="t", issue_type="Task",
               status_category="todo", assignee="ada", epic_key="E-1",
               remaining_estimate_days=6.0)
    fv = FixVersion("v1", release_date=date(2026, 7, 22))   # end of sprint 1
    safe = make_bundle(issues=[epic, t1], fix_versions=[fv],
                       config=Config(team=["ada"]))
    at_risk = make_bundle(issues=[epic, t1], fix_versions=[fv],
                          config=Config(team=["ada"],
                                        recurring_days={"ada": 3.0}))
    for b, expect in ((safe, False), (at_risk, True)):
        bks = buckets_for(b)
        fired = any(f.check == "tentpole_runway" and f.subject == "E-1"
                    for f in tentpole_runway(b, bks, compile_demand(b, bks)))
        assert fired is expect
```

(`prior` and `Config`/`Ghost` are already imported at the top of each file: `test_throughput.py` imports `prior`, `empirical`, `throughput_for`, `capacity_for`, `Config`; `test_checks_capacity.py` imports `Config`, `Ghost`. `date` and `_done`/`make_sprints` exist in `test_throughput.py`. The runway test imports what it needs locally.)

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_throughput.py tests/test_checks_capacity.py -k "effective or coarse_capacity_loses" -q
```
Expected: FAIL — `cannot import name 'effective_throughput_for'` / capacity assertions off.

- [ ] **Step 3: Add `effective_throughput_for` and rewire `capacity_for`**

In `src/tentpole/throughput.py`, add after `throughput_for` (line 39):

```python
def effective_throughput_for(bundle: Bundle, person: str) -> float:
    # Spec §4 (the double-count rule -- do NOT "simplify" this into always
    # subtracting recurring_days; that reintroduces the bug). empirical()
    # measures real delivery, so a person carrying recurring ops ALREADY
    # shows reduced empirical throughput. Recurring burden therefore
    # reduces capacity only while throughput comes from the prior. The
    # result is deliberately not clamped: a burden exceeding the prior
    # yields non-positive capacity, firing every capacity check -- correct
    # for someone fully allocated to non-Jira work.
    measured = empirical(bundle, person)
    if measured is not None:
        return measured
    return prior(bundle.config) - bundle.config.recurring_days.get(person, 0.0)
```

In `capacity_for`, change the first line of the body from:

```python
    cap = throughput_for(bundle, person)
```

to:

```python
    cap = effective_throughput_for(bundle, person)
```

- [ ] **Step 4: Rewire `team_subscription`'s coarse branch and `tentpole_runway`**

In `src/tentpole/checks.py`, update the import at line 11 from:

```python
from tentpole.throughput import capacity_for, throughput_for
```

to (drop `throughput_for` — no consumer in `checks.py` uses it after this task):

```python
from tentpole.throughput import capacity_for, effective_throughput_for
```

In `team_subscription` (the `else` branch, lines 58-60), change:

```python
            cap = sum(throughput_for(bundle, p)
                      * bundle.config.sprints_per_plan
                      for p in bundle.config.team)
```

to:

```python
            cap = sum(effective_throughput_for(bundle, p)
                      * bundle.config.sprints_per_plan
                      for p in bundle.config.team)
```

In `tentpole_runway` (the per-person loop, line 122), change:

```python
            cap = throughput_for(bundle, person) * runway
```

to:

```python
            cap = effective_throughput_for(bundle, person) * runway
```

(`throughput_for` remains defined in `throughput.py` — `effective_throughput_for` and the throughput tests still use it — it is just no longer imported into `checks.py`.)

- [ ] **Step 5: Run to verify pass**

```bash
python -m pytest tests/test_throughput.py tests/test_checks_capacity.py -q
```
Expected: PASS (existing + 6 new: 4 in `test_throughput.py`, 2 in `test_checks_capacity.py`).

- [ ] **Step 6: Full suite**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: `238 passed` (232 + 6).

- [ ] **Step 7: Commit**

```bash
git add src/tentpole/throughput.py src/tentpole/checks.py tests/test_throughput.py tests/test_checks_capacity.py
git commit -m "feat: effective_throughput_for for capacity, subscription, runway (spec §4)"
```

**Running total: 238.**

---

## Task 4: The `people` schema replaces `team` and `exceptions` (spec §3, §9)

Register the human-owned `people` schema (`Item` primary TEXT, `Sprint` NUMBER, `Days` NUMBER, `Notes` TEXT) and remove the `team` and `exceptions` schemas. This is an atomic registry change; the parser (Task 5) and sync wiring (Task 6) follow. The old `team_from_sheet`/`exceptions_from_sheet` parsers still exist and are still called by `cli.py` after this task — that keeps the suite green until Task 6 swaps them; the schema removal only affects `schema show`, `bootstrap`, `pull_state` validation, and the registry tests.

**Files:**
- Modify: `src/tentpole/schema.py` — `SCHEMAS` (lines 93-104: remove `exceptions` and `team`; add `people`)
- Test (SANCTIONED EDIT): `tests/test_schema.py`

**Interfaces:**
- Produces: `SCHEMAS["people"]`, a human-owned schema with columns `Item` (primary), `Sprint` (NUMBER), `Days` (NUMBER), `Notes` (TEXT). `SCHEMAS` no longer contains `team` or `exceptions`.

- [ ] **Step 1: Edit the registry tests first (SANCTIONED EDIT)**

In `tests/test_schema.py`, replace `test_registry_has_all_sheets_with_ownership` (lines 4-10) with:

```python
def test_registry_has_all_sheets_with_ownership():
    assert set(SCHEMAS) == {"issues", "epics", "fixversions", "dependencies",
                            "capacity", "accuracy", "future_work", "people"}
    assert SCHEMAS["issues"].owned == "machine"
    assert SCHEMAS["future_work"].owned == "human"
    assert SCHEMAS["people"].owned == "human"
    assert "team" not in SCHEMAS          # replaced by people (spec §3)
    assert "exceptions" not in SCHEMAS
```

And replace `test_human_sheets_have_no_synced_columns` (lines 20-24) with:

```python
def test_human_sheets_have_no_synced_columns():
    assert SCHEMAS["future_work"].synced_names() == []
    assert SCHEMAS["people"].synced_names() == []
    assert "Key" in SCHEMAS["issues"].synced_names()
```

(`epics` is still present in 5a; Plan 5b removes it. `test_every_schema_has_exactly_one_primary` and `test_render_schemas_lists_every_sheet_and_column` iterate `SCHEMAS.values()` and adapt automatically.)

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_schema.py -q
```
Expected: FAIL — `people` not in `SCHEMAS`, and `team`/`exceptions` still present.

- [ ] **Step 3: Edit the registry**

In `src/tentpole/schema.py`, delete the `"exceptions"` entry (lines 93-98) and the `"team"` entry (lines 99-103), and add the `people` schema in their place:

```python
    "people": _human(
        "people",
        ColumnDef("Item", primary=True),
        ColumnDef("Sprint", "NUMBER"),
        ColumnDef("Days", "NUMBER"),
        ColumnDef("Notes"),
    ),
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_schema.py -q
```
Expected: PASS.

- [ ] **Step 5: Full suite**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: `238 passed` (unchanged count — SANCTIONED EDITs replaced two tests in place; no net add). Existing `test_humansheets.py` (`team_from_sheet`, `exceptions_from_sheet`) and `test_cli_sync.py` (`team.json`/`exceptions.json`) still pass because those exercise the parsers/cli by literal name, not via `SCHEMAS`.

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/schema.py tests/test_schema.py
git commit -m "feat: register people schema, retire team+exceptions schemas (spec §3)"
```

**Running total: 238.**

---

## Task 5: The people-sheet parser (spec §3)

Parse the pulled people state into a roster, recurring burden, and one-off exceptions, with all §3 fail-loud rules. The 0.3.0 team-sheet semantics (order-preserving roster, blank-row skip, duplicate-person raise, present-but-empty authoritative) are **preserved** here — ported from the old `team_from_sheet` tests, not deleted. The old `team_from_sheet` and `exceptions_from_sheet` functions and their tests are removed (they are superseded by this parser).

Note on where each rule fires: **duplicate person** (duplicate root) and **duplicate (person, item)** (duplicate child) already raise at *pull* time (Task 1's parent-qualified duplicate-key raise), so their §11 tests live in `test_smartsheet_pull.py` (Task 1). This parser enforces the rest: **Days on a root**, **grandchild**, **missing/non-numeric Days on a child**, **fractional Sprint**. It also enforces duplicate-root defensively for callers that build the dict by hand.

**Files:**
- Modify: `src/tentpole/humansheets.py` — remove `team_from_sheet` (lines 86-101) and `exceptions_from_sheet` (lines 70-83); add `PeopleSheet` dataclass + `people_from_sheet` + helpers
- Test (SANCTIONED EDIT): `tests/test_humansheets.py` — remove the `exceptions_from_sheet` and `team_from_sheet` test functions; add people-parser tests

**Interfaces:**
- Consumes: pulled people state `dict[str, dict]` (qualified keys, `_parent` = parent's bare primary), `ExceptionRow` (unchanged).
- Produces:
  ```python
  @dataclass
  class PeopleSheet:
      team: list[str]                    # roster, in sheet order
      recurring_days: dict[str, float]   # person -> summed recurring days/sprint
      exceptions: list[ExceptionRow]     # one-off burdens (Sprint set)

  def people_from_sheet(rows: dict[str, dict]) -> PeopleSheet: ...
  ```

- [ ] **Step 1: Edit the tests first (SANCTIONED EDIT)**

In `tests/test_humansheets.py`:

1. Change the imports at the top (lines 1-4) from:

```python
import pytest

from tentpole.humansheets import exceptions_from_sheet, ghosts_from_sheet
from tentpole.model import ExceptionRow, Ghost
```

to:

```python
import pytest

from tentpole.humansheets import (ghosts_from_sheet, people_from_sheet)
from tentpole.model import ExceptionRow, Ghost
```

2. **Delete** `test_exceptions_from_sheet` (lines 24-31), `test_exceptions_from_sheet_bad_day_cost_raises_actionable_error` (lines 46-55), `test_team_from_sheet_orders_and_skips_blanks` (lines 91-99), and `test_team_from_sheet_rejects_duplicates` (lines 102-108). Keep every `ghosts_from_sheet` / `_target` test untouched.

3. **Append** the ported + new people-parser tests:

```python
def test_people_roster_recurring_and_oneoff_happy_path():
    ps = people_from_sheet({
        "ada": {"Item": "ada", "_parent": None},
        "ada|team lead": {"Item": "team lead", "Days": 2, "_parent": "ada"},
        "ada|PTO": {"Item": "PTO", "Sprint": 3, "Days": 4, "_parent": "ada"},
        "grace": {"Item": "grace", "_parent": None},
        "grace|ops rotation": {"Item": "ops rotation", "Days": 0.5,
                               "_parent": "grace"},
    })
    assert ps.team == ["ada", "grace"]
    assert ps.recurring_days == {"ada": 2.0, "grace": 0.5}
    assert ps.exceptions == [ExceptionRow(person="ada", sprint_id=3,
                                          day_cost=4.0)]


def test_people_roster_orders_and_skips_blanks_ported():
    # Ported from the retired team_from_sheet test: order preserved, blank
    # rows skipped (0.3.0 team-sheet semantics on the people sheet now).
    ps = people_from_sheet({
        "Ada Lovelace": {"Item": "Ada Lovelace", "_parent": None},
        "blank": {"Item": "  ", "_parent": None},
        "Grace Hopper": {"Item": "Grace Hopper", "Notes": "on loan",
                         "_parent": None},
    })
    assert ps.team == ["Ada Lovelace", "Grace Hopper"]


def test_people_present_but_empty_is_authoritative_empty_roster():
    # Ported semantics: a present-but-empty sheet is an authoritative empty
    # team, not a fallback (the cli wiring in Task 6 relies on this).
    assert people_from_sheet({}).team == []


def test_people_duplicate_root_raises_ported():
    # Ported from team_from_sheet's duplicate test. (Live pulls already
    # raise this at Task 1; the parser guards direct callers too.)
    with pytest.raises(ValueError, match="Ada"):
        people_from_sheet({
            "Ada": {"Item": "Ada", "_parent": None},
            "Ada ": {"Item": "Ada", "_parent": None},   # distinct dict key
        })


def test_people_days_on_root_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({"ada": {"Item": "ada", "Days": 3, "_parent": None}})
    assert "ada" in str(exc.value) and "Days" in str(exc.value)


def test_people_grandchild_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|ops": {"Item": "ops", "Days": 2, "_parent": "ada"},
            "ops|deep": {"Item": "deep", "Days": 1, "_parent": "ops"},
        })
    assert "ops" in str(exc.value) and "grandchild" in str(exc.value)


def test_people_child_missing_days_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|ops": {"Item": "ops", "_parent": "ada"}})
    assert "ops" in str(exc.value) and "Days" in str(exc.value)


def test_people_child_nonnumeric_days_raises():
    with pytest.raises(ValueError, match="lots"):
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|ops": {"Item": "ops", "Days": "lots", "_parent": "ada"}})


def test_people_fractional_sprint_raises():
    with pytest.raises(ValueError) as exc:
        people_from_sheet({
            "ada": {"Item": "ada", "_parent": None},
            "ada|PTO": {"Item": "PTO", "Sprint": 3.5, "Days": 4,
                        "_parent": "ada"}})
    assert "Sprint" in str(exc.value) and "3.5" in str(exc.value)


def test_people_multiple_recurring_children_sum():
    ps = people_from_sheet({
        "ada": {"Item": "ada", "_parent": None},
        "ada|ops": {"Item": "ops", "Days": 1.5, "_parent": "ada"},
        "ada|lead": {"Item": "lead", "Days": 0.5, "_parent": "ada"},
    })
    assert ps.recurring_days == {"ada": 2.0}
```

(Ten new people-parser tests; four `team_from_sheet`/`exceptions_from_sheet` tests removed above → net +6 for Task 5.)

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_humansheets.py -q
```
Expected: FAIL — `cannot import name 'people_from_sheet'`.

- [ ] **Step 3: Rewrite `humansheets.py`**

In `src/tentpole/humansheets.py`: update the module docstring's first line and imports (lines 1-8) to:

```python
"""Parse human-owned sheet state (Future Work, People) back into bundle
inputs (spec section 7: the sync reads these, never writes them)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from tentpole.model import ExceptionRow, Ghost
```

Delete `exceptions_from_sheet` (lines 70-83) and `team_from_sheet` (lines 86-101). At the end of the file, add:

```python
@dataclass
class PeopleSheet:
    team: list[str]
    recurring_days: dict[str, float]
    exceptions: list[ExceptionRow]


def _people_days(cells: dict, person: str, item: str) -> float:
    value = cells.get("Days")
    if value is None or str(value).strip() == "":
        raise ValueError(
            f"people sheet: burden {item!r} under {person!r} has no Days "
            f"value -- every burden needs a whole- or fractional-day cost "
            f"in the Days column")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"people sheet: burden {item!r} under {person!r}: Days must be "
            f"a number, got {value!r}") from None


def _people_sprint(value, person: str, item: str) -> int:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"people sheet: burden {item!r} under {person!r}: Sprint must "
            f"be a whole sprint id, got {value!r}") from None
    if num != int(num):
        # A sprint id is a whole number; a fractional value is a typo, not a
        # half-sprint. (Days, by contrast, is fractional-friendly.)
        raise ValueError(
            f"people sheet: burden {item!r} under {person!r}: Sprint must "
            f"be a whole sprint id, got {value!r}")
    return int(num)


def people_from_sheet(rows: dict[str, dict]) -> PeopleSheet:
    """Roster from root rows; recurring/one-off burden from child rows.
    Present sheet is authoritative (including present-but-empty -> empty
    team). Person names must match the Jira display name exactly --
    team_drift flags mismatches. (Duplicate persons and duplicate
    (person, item) pairs already raise at pull time, spec §8; the checks
    here guard direct callers and enforce the remaining §3 rules.)"""
    roster: list[str] = []
    root_set: set[str] = set()
    children: list[tuple[str, str, dict]] = []
    for cells in rows.values():
        item = _text(cells, "Item")
        if not item:
            continue
        parent = cells.get("_parent")
        if parent is None:
            if _text(cells, "Days") is not None:
                raise ValueError(
                    f"people sheet: person row {item!r} has a Days value -- "
                    f"a person row is a name, not a burden; put the burden "
                    f"on a child row indented under {item!r}")
            if item in root_set:
                raise ValueError(
                    f"people sheet lists person {item!r} more than once")
            root_set.add(item)
            roster.append(item)
        else:
            children.append((parent, item, cells))
    recurring: dict[str, float] = {}
    exceptions: list[ExceptionRow] = []
    for parent, item, cells in children:
        if parent not in root_set:
            raise ValueError(
                f"people sheet: burden {item!r} is nested under {parent!r}, "
                f"which is not a person row -- burdens go directly under a "
                f"person (no grandchildren)")
        days = _people_days(cells, parent, item)
        sprint_raw = cells.get("Sprint")
        if sprint_raw is None or str(sprint_raw).strip() == "":
            recurring[parent] = recurring.get(parent, 0.0) + days
        else:
            exceptions.append(ExceptionRow(
                person=parent,
                sprint_id=_people_sprint(sprint_raw, parent, item),
                day_cost=days))
    return PeopleSheet(team=roster, recurring_days=recurring,
                       exceptions=exceptions)
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_humansheets.py -q
```
Expected: FAIL — `cli.py` still imports `exceptions_from_sheet`/`team_from_sheet`, so collection of other test modules that import `cli` breaks. That is expected; this task's own file passes its `people_from_sheet` tests, but the suite is red until Task 6 rewires `cli.py`. Confirm just this file:

```bash
python -m pytest tests/test_humansheets.py -q 2>&1 | tail -1
```
Expected: all `test_humansheets.py` tests PASS. Do **not** run the full suite green here — Task 6 completes the swap. Commit this partial step so the pair (5 + 6) is bisectable, or (recommended) proceed straight into Task 6 and commit them together. This plan commits them together; skip the standalone commit and go to Task 6.

**Running total after Tasks 5+6: see Task 6.**

---

## Task 6: Sync wiring for the people sheet (spec §3) + unmatched-one-off finding

Rewire `cli.py`'s `sync` command to read a single `people.json` state file instead of `team.json` + `exceptions.json`, applying roster, recurring burden, and one-off exceptions from it. Add the §3 yellow finding for a one-off whose sprint matches no known sprint (reported, not dropped). Port the three affected `test_cli_sync.py` tests.

**Files:**
- Modify: `src/tentpole/cli.py` — imports (lines 13-14), sync state wiring (lines 111-132, through the `run_sync` call)
- Modify: `src/tentpole/checks.py` — add `unmatched_exception`
- Modify: `src/tentpole/diagnostics.py` — wire `unmatched_exception` into `assemble`
- Modify: `src/tentpole/cli.py` — `_SECTION_ORDER` (add `unmatched_exception`)
- Test (SANCTIONED EDIT): `tests/test_cli_sync.py` — port 3 tests
- Test: `tests/test_checks_capacity.py` (append, for `unmatched_exception`)

**Interfaces:**
- Consumes: `people_from_sheet`/`PeopleSheet` (Task 5), `Config.recurring_days` (Task 2).
- Produces: `unmatched_exception(bundle, buckets) -> list[Finding]`. The sync applies `people.json` present-authoritatively to `bundle.config.team`, `bundle.config.recurring_days`, and `bundle.exceptions`.

- [ ] **Step 1: Write the failing `unmatched_exception` test**

Append to `tests/test_checks_capacity.py`:

```python
def test_unmatched_exception_yields_yellow_not_silence(make_bundle):
    from tentpole.buckets import buckets_for
    from tentpole.checks import unmatched_exception
    from tentpole.model import ExceptionRow
    # Sprint 999 is not in the bundle's sprints (ids 1..6). The one-off must
    # surface as a yellow finding, never be silently dropped (spec §3).
    b = make_bundle(exceptions=[ExceptionRow("ada", 999, 2.0)])
    bks = buckets_for(b)
    findings = unmatched_exception(b, bks)
    assert len(findings) == 1
    f = findings[0]
    assert (f.check, f.severity, f.subject) == (
        "unmatched_exception", "yellow", "ada")
    assert "999" in f.message


def test_unmatched_exception_quiet_when_sprint_known(make_bundle):
    from tentpole.buckets import buckets_for
    from tentpole.checks import unmatched_exception
    from tentpole.model import ExceptionRow
    b = make_bundle(exceptions=[ExceptionRow("ada", 1, 2.0)])
    assert unmatched_exception(b, buckets_for(b)) == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_checks_capacity.py -k unmatched -q
```
Expected: FAIL — `cannot import name 'unmatched_exception'`.

- [ ] **Step 3: Add `unmatched_exception` to `checks.py`**

Append to `src/tentpole/checks.py`:

```python
def unmatched_exception(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    # Spec §3: a one-off burden whose Sprint matches no known sprint is not
    # a parse-time error (future sprints may not exist in the bundle yet),
    # but it must never be silently dropped -- report it so the human fixes
    # the Sprint cell or accepts the burden is ignored.
    sprint_ids = {s.id for s in bundle.sprints}
    findings = []
    for e in bundle.exceptions:
        if e.sprint_id not in sprint_ids:
            findings.append(Finding(
                "unmatched_exception", "yellow", e.person, None,
                f"{e.person}: one-off burden of {e.day_cost:.1f}d targets "
                f"sprint {e.sprint_id}, which is not in the current plan -- "
                f"fix the Sprint cell on the people sheet or the burden is "
                f"ignored"))
    return findings
```

- [ ] **Step 4: Wire it into `diagnostics.assemble`**

In `src/tentpole/diagnostics.py`, update the import (lines 9-12) to add `unmatched_exception`:

```python
from tentpole.checks import (
    deadline_risk, dependency_readiness, ghost_claims, sprint_overload,
    team_drift, team_subscription, tentpole_runway, unmatched_exception,
)
```

In `assemble`, add to the `findings` sum (after `team_drift(bundle, buckets, demand)`, line 29):

```python
        + unmatched_exception(bundle, buckets)
```

- [ ] **Step 5: Rewire `cli.py` sync to the people sheet**

In `src/tentpole/cli.py`, change the import (lines 13-14) from:

```python
from tentpole.humansheets import (exceptions_from_sheet, ghosts_from_sheet,
                                  team_from_sheet)
```

to:

```python
from tentpole.humansheets import ghosts_from_sheet, people_from_sheet
```

Add `unmatched_exception` to `_SECTION_ORDER` (lines 22-26) so it renders — change to:

```python
_SECTION_ORDER = [
    "sprint_overload", "deadline_risk", "tentpole_runway",
    "dependency_readiness", "ghost_claims", "team_subscription",
    "team_drift", "unmatched_exception",
]
```

Replace the state-reading block (lines 111-132) — from `future_work = _state("future_work")` through the `result = run_sync(bundle, rules, current)` call — with:

```python
        future_work = _state("future_work")
        if future_work is not None:
            bundle = replace(bundle, ghosts=ghosts_from_sheet(future_work))
        people = _state("people")
        if people is not None:
            # Present is authoritative, including present-but-empty (an empty
            # roster is a deliberate human act, spec §3). Absent falls back
            # to the bundle's core: team: / recurring_days and no exceptions.
            parsed = people_from_sheet(people)
            bundle = replace(
                bundle,
                exceptions=parsed.exceptions,
                config=replace(bundle.config, team=parsed.team,
                               recurring_days=parsed.recurring_days))
        # run_sync expects a dict (never None) per machine sheet, even when
        # its state file is absent.
        current = {name: _state(name) or {}
                   for name, schema in SCHEMAS.items()
                   if schema.owned == "machine"}
        result = run_sync(bundle, rules, current)
```

- [ ] **Step 6: Port the affected `test_cli_sync.py` tests (SANCTIONED EDIT)**

In `tests/test_cli_sync.py`:

Replace `test_sync_team_sheet_overrides_bundle_config` (lines 116-126) with:

```python
def test_sync_people_sheet_overrides_bundle_config(dirs):
    bundle, state, out = dirs
    (state / "people.json").write_text(json.dumps({
        "grace": {"Item": "grace", "_row_id": 1, "_parent": None}}))
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    cap = json.loads((out / "plans" / "capacity.json").read_text())
    keys = {c["key"] for c in cap}
    assert any(k.startswith("grace|") for k in keys)
    assert not any(k.startswith("ada|") for k in keys)
```

Replace `test_sync_emptied_team_sheet_drops_stale_bundle_roster` (lines 129-146) with:

```python
def test_sync_emptied_people_sheet_drops_stale_bundle_roster(dirs):
    # Present-but-empty people.json ({}) is authoritative: the bundle's
    # core: team: roster must not survive it (spec §3, ported from the
    # 0.3.0 team-sheet semantics test).
    bundle, state, out = dirs
    (state / "people.json").write_text("{}")
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    cap = json.loads((out / "plans" / "capacity.json").read_text())
    assert cap == []
```

Replace `test_sync_emptied_exceptions_sheet_drops_stale_bundle_exception` (lines 95-113) with a people-sourced equivalent:

```python
def test_sync_people_sheet_supplies_exceptions(dirs):
    # One-off exceptions now come from people-sheet child rows with Sprint
    # set (spec §3). ada carries 6d of sprint-1 work; a 3d one-off in
    # sprint 1 pushes her over prior capacity -> red sprint_overload.
    bundle, state, out = dirs
    issues = json.loads((bundle / "issues.json").read_text())
    issues[0]["remaining_estimate_days"] = 6.0
    (bundle / "issues.json").write_text(json.dumps(issues))
    (state / "people.json").write_text(json.dumps({
        "ada": {"Item": "ada", "_row_id": 1, "_parent": None},
        "ada|PTO": {"Item": "PTO", "Sprint": 1, "Days": 3, "_row_id": 2,
                    "_parent": "ada"}}))
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert rc == 0                                   # sync reports, returns 0
    assert "sprint_overload" in report["findings"]
```

Note: the `sync` command always returns 0 on success and reports findings (it is the `check` command that returns 1 on a red finding; see `cli.py`). Keep `rc == 0` here.

- [ ] **Step 7: Run the ported file and the full suite**

```bash
python -m pytest tests/test_cli_sync.py tests/test_humansheets.py tests/test_checks_capacity.py -q
python -m pytest -q 2>&1 | tail -1
```
Expected: all green. Count: 238 (start) − 4 removed humansheets tests (Task 5) + 10 new people-parser tests (Task 5) + 2 new `unmatched_exception` tests (this task) = **246**. The three `test_cli_sync.py` ports are in-place replacements (net 0). Confirm:

```bash
python -m pytest -q 2>&1 | tail -1
# Expected: 246 passed
```

- [ ] **Step 8: Commit Tasks 5 + 6 together**

```bash
git add src/tentpole/humansheets.py src/tentpole/cli.py src/tentpole/checks.py src/tentpole/diagnostics.py tests/test_humansheets.py tests/test_cli_sync.py tests/test_checks_capacity.py
git commit -m "feat: people-sheet parser + sync wiring; unmatched one-off finding (spec §3)"
```

**Running total: 246.**

---

## Task 7: Sheet selection and name resolution (spec §2)

The biggest change. A sheet syncs because it exists: resolve each schema by name inside the workspace, with an explicit id always winning. Every push/pull run report enumerates **all** known schemas with their resolution (SYNCED / OFF), so a renamed or deleted sheet flips to OFF in the next run — it can never fail silently. The old SKIPPED+exit-1 behavior for unconfigured machine sheets is **removed**; that strictness role moves to an opt-in `expect:` list.

**Shape caveat:** the workspace-listing response (`GET /workspaces/{id}` → `{"sheets": [{"id", "name"}, ...]}`) is unverified. Design it behind the injectable `http` seam with a documented-shape fixture, and the README task (Task 9) marks it smoke-before-trust.

**Files:**
- Modify: `src/tentpole/adapters/config.py` — `SmartsheetConfig` (add `expect`), `load_config` (lines 152-160)
- Modify: `src/tentpole/adapters/smartsheet_load.py` — add `_workspace_sheets`, `resolve_sheets` (with the preserved unknown-key guard); rewrite `push_plans` (lines 237-285) and `pull_state` (the Task 1 version → returns a per-schema resolution report)
- Modify: `src/tentpole/adapters/cli.py` — `_push` (lines 124-150), `_pull` (lines 115-121) — both enumerate every schema
- Test: `tests/test_adapter_config.py` (append), `tests/test_smartsheet_push.py` (append + SANCTIONED EDIT of the 2 SKIPPED tests and the stubbed-`push_plans` return), `tests/test_smartsheet_pull.py` (append + SANCTIONED EDIT of `test_pull_state_writes_files`)

**Interfaces:**
- Produces:
  - `SmartsheetConfig.expect: tuple[str, ...] = ()`.
  - `_workspace_sheets(cfg, http=request) -> dict[str, list[int]]` — sheet name → ids present in the workspace (list detects duplicate names). `{}` when `workspace_id` is None.
  - `resolve_sheets(cfg, http=request) -> dict[str, int | None]` — for every name in `SCHEMAS`: explicit id if in `cfg.sheets`, else the workspace match, else `None` (OFF). Two workspace sheets with one name → `ValueError`; an unknown `cfg.sheets` key → `ValueError` (the preserved unknown-key guard).
  - `push_plans(...)` returns, per schema name, `{"state": "SYNCED"|"OFF", "sheet_id": int|None, "added","updated","removed","failed"}`.
  - `pull_state(...)` returns, per schema name, `{"state": "SYNCED"|"OFF", "sheet_id": int|None, "owned": "machine"|"human"}` (was a `list[str]`) so `_pull` can enumerate every schema — SYNCED with its id, or OFF with the human-sheet fallback note.

- [ ] **Step 1: Add `expect` to config (test first)**

Append to `tests/test_adapter_config.py`:

```python
def test_smartsheet_expect_parsed(tmp_path, monkeypatch):
    from tentpole.adapters.config import load_config
    monkeypatch.setenv("S", "tok")
    (tmp_path / "c.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  workspace_id: 999\n"
        "  expect: [issues, capacity]\n")
    cfg = load_config(tmp_path / "c.yaml")
    assert cfg.smartsheet.expect == ("issues", "capacity")
    assert cfg.smartsheet.workspace_id == 999


def test_smartsheet_expect_defaults_empty(tmp_path, monkeypatch):
    from tentpole.adapters.config import load_config
    monkeypatch.setenv("S", "tok")
    (tmp_path / "c.yaml").write_text("smartsheet:\n  token_env_var: S\n")
    cfg = load_config(tmp_path / "c.yaml")
    assert cfg.smartsheet.expect == ()
```

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_adapter_config.py -k expect -q
```
Expected: FAIL — `SmartsheetConfig` has no `expect`.

- [ ] **Step 3: Add the field and parse it**

In `src/tentpole/adapters/config.py`, in `SmartsheetConfig` (lines 94-103), add a field after `workspace_id`:

```python
    expect: tuple[str, ...] = ()
```

In `load_config` (lines 152-160), change the `SmartsheetConfig(...)` construction to pass `expect`:

```python
        smartsheet = SmartsheetConfig(
            base_url=s.get("base_url",
                           "https://api.smartsheet.com/2.0").rstrip("/"),
            token=_token(s, env),
            sheets={k: int(v) for k, v in s.get("sheets", {}).items()},
            workspace_id=s.get("workspace_id"),
            expect=tuple(s.get("expect", [])),
        )
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_adapter_config.py -q
```
Expected: PASS.

- [ ] **Step 5: Write resolver tests (documented-shape fixture)**

Append to `tests/test_smartsheet_push.py`:

```python
# Documented (unverified) shape of GET /workspaces/{id}. The gantt/predecessor
# and this listing shape get a SmartsheetGov smoke before the README drops the
# experimental label (spec §2, §11).
WORKSPACE = {"id": 999, "name": "Planning", "sheets": [
    {"id": 1234, "name": "issues"},
    {"id": 5678, "name": "capacity"},
    {"id": 4321, "name": "dashboard"},        # not a schema name -> ignored
]}


def test_resolve_explicit_id_beats_discovery(fake_http):
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111}, workspace_id=999)
    fake_http.add("GET", "/workspaces/999", WORKSPACE)
    resolved = resolve_sheets(cfg, http=fake_http)
    assert resolved["issues"] == 111          # explicit id wins over 1234
    assert resolved["capacity"] == 5678       # discovered by name
    assert resolved["fixversions"] is None    # OFF


def test_resolve_no_workspace_no_sheets_all_off(fake_http):
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    resolved = resolve_sheets(cfg, http=fake_http)     # no HTTP call at all
    assert set(resolved) == set(SCHEMAS)
    assert all(v is None for v in resolved.values())
    assert fake_http.calls == []


def test_resolve_ambiguous_duplicate_name_raises(fake_http):
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=999)
    ws = {"sheets": [{"id": 1, "name": "issues"},
                     {"id": 2, "name": "issues"}]}
    fake_http.add("GET", "/workspaces/999", ws)
    with pytest.raises(ValueError, match="issues"):
        resolve_sheets(cfg, http=fake_http)


def test_resolve_sheets_rejects_unknown_explicit_key(fake_http):
    # The unknown-explicit-key guard (preserved from pull_state, spec §2/§8):
    # a typo'd key under smartsheet.sheets must raise before any HTTP.
    from tentpole.adapters.smartsheet_load import resolve_sheets
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"mystery": 5})
    with pytest.raises(ValueError, match="mystery"):
        resolve_sheets(cfg, http=fake_http)
    assert fake_http.calls == []          # raised before touching the network
```

- [ ] **Step 6: Run to verify fail**

```bash
python -m pytest tests/test_smartsheet_push.py -k resolve -q
```
Expected: FAIL — `cannot import name 'resolve_sheets'`.

- [ ] **Step 7: Add `_workspace_sheets` and `resolve_sheets`**

In `src/tentpole/adapters/smartsheet_load.py`, after `_headers`/`_call` (line 22), add:

```python
def _workspace_sheets(cfg, http=request) -> dict[str, list[int]]:
    # GET /workspaces/{id} -> {"sheets": [{"id", "name"}, ...]}. Shape is
    # UNVERIFIED against SmartsheetGov; smoke before trusting (spec §2, §11).
    if cfg.workspace_id is None:
        return {}
    data = _call(cfg, "GET", f"/workspaces/{cfg.workspace_id}", http=http)
    out: dict[str, list[int]] = {}
    for sh in data.get("sheets", []):
        out.setdefault(sh["name"], []).append(sh["id"])
    return out


def resolve_sheets(cfg, http=request) -> dict[str, int | None]:
    # Spec §2 resolution order, per schema name: explicit id wins; else a
    # workspace sheet whose name equals the schema name exactly; else OFF.
    # Preserve the unknown-explicit-key guard here (moved out of pull_state)
    # so both push and pull inherit it: a typo'd key under smartsheet.sheets
    # (a sheet id pointing nowhere) must fail loud, not silently do nothing.
    unknown = [name for name in cfg.sheets if name not in SCHEMAS]
    if unknown:
        raise ValueError(
            f"unknown sheet name(s) {sorted(unknown)} under "
            f"smartsheet.sheets (known schemas: {sorted(SCHEMAS)}) -- a "
            f"typo'd explicit id would otherwise resolve to nothing silently")
    ws = _workspace_sheets(cfg, http=http)
    resolved: dict[str, int | None] = {}
    for name in SCHEMAS:
        if name in cfg.sheets:
            resolved[name] = cfg.sheets[name]
            continue
        ids = ws.get(name, [])
        if len(ids) > 1:
            raise ValueError(
                f"workspace {cfg.workspace_id} has {len(ids)} sheets named "
                f"{name!r} (ids {sorted(ids)}); exact-name matching cannot "
                f"choose -- rename all but one, or pin the id under "
                f"smartsheet.sheets.{name}")
        resolved[name] = ids[0] if ids else None
    return resolved
```

- [ ] **Step 8: Run resolver tests**

```bash
python -m pytest tests/test_smartsheet_push.py -k resolve -q
```
Expected: PASS.

- [ ] **Step 9: Rewrite `push_plans` for resolution + expect + enumeration**

Replace `push_plans` (lines 237-285) with:

```python
def push_plans(cfg, plans_dir: Path, state_dir: Path,
               http=request) -> dict[str, dict]:
    plans_dir, state_dir = Path(plans_dir), Path(state_dir)
    resolved = resolve_sheets(cfg, http=http)

    # Expect (spec §2): any expected schema that resolved OFF is a hard
    # error, and the message names the sheets actually present so a
    # rename/typo is diagnosable from the message alone.
    missing = [name for name in cfg.expect if resolved.get(name) is None]
    if missing:
        present = sorted(_workspace_sheets(cfg, http=http))
        raise ValueError(
            f"expected sheet(s) {missing} did not resolve (no explicit id and "
            f"no exact-name match in workspace {cfg.workspace_id}). Sheets "
            f"present in the workspace: {present or '(none)'}. Fix the name or "
            f"drop it from smartsheet.expect.")

    report: dict[str, dict] = {}
    targets = []
    for name, schema in SCHEMAS.items():
        if schema.owned != "machine":
            continue
        plan_path = plans_dir / f"{name}.json"
        sheet_id = resolved.get(name)
        if sheet_id is None:
            # OFF is a normal state (spec §2): printed every run, exit 0.
            report[name] = {"state": "OFF", "sheet_id": None,
                            "added": 0, "updated": 0, "removed": 0,
                            "failed": []}
            continue
        if not plan_path.exists():
            # Resolved but sync produced no plan (rare); nothing to do.
            report[name] = {"state": "SYNCED", "sheet_id": sheet_id,
                            "added": 0, "updated": 0, "removed": 0,
                            "failed": []}
            continue
        targets.append((name, schema, plan_path, sheet_id))

    # Pre-flight EVERY target sheet's columns before the first write (a
    # mid-loop mismatch would leave earlier sheets written and the report
    # discarded).
    col_ids_by_name = {}
    problems = []
    for name, schema, _plan, sheet_id in targets:
        col_ids = _column_ids(cfg, sheet_id, http=http)
        problem = _validate_columns(schema, sheet_id, col_ids)
        if problem:
            problems.append(problem)
        col_ids_by_name[name] = col_ids
    if problems:
        raise ValueError("\n".join(problems))

    for name, schema, plan_path, sheet_id in targets:
        changes = json.loads(plan_path.read_text())
        state_path = state_dir / f"{name}.json"
        state = (json.loads(state_path.read_text())
                 if state_path.exists() else {})
        r = push_plan(cfg, sheet_id, changes, state, schema, http=http,
                      col_ids=col_ids_by_name[name])
        r["state"] = "SYNCED"
        r["sheet_id"] = sheet_id
        report[name] = r
    return report
```

- [ ] **Step 10: Rewrite `pull_state` for resolution + human fallback + enumeration report**

`pull` must enumerate every schema too (spec §2: the never-silent report covers push **and** pull — a human sheet going OFF silently switches behavior to the yaml fallback, which is exactly what must be surfaced). So `pull_state` now returns a per-schema resolution report (not a `list[str]`), and `_pull` prints one line per schema. Replace `pull_state` (the Task 1 version) with:

```python
def pull_state(cfg, state_dir: Path, http=request) -> dict[str, dict]:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    resolved = resolve_sheets(cfg, http=http)   # inherits the unknown-key guard
    report: dict[str, dict] = {}
    for name in sorted(SCHEMAS):
        owned = SCHEMAS[name].owned
        sheet_id = resolved.get(name)
        if sheet_id is None:
            # OFF human sheet falls back exactly as an absent state file:
            # people -> yaml, future_work -> none (spec §2). We simply do not
            # write a state file, so cli's _state(name) returns None.
            report[name] = {"state": "OFF", "sheet_id": None, "owned": owned}
            continue
        state = pull_sheet(cfg, sheet_id, http=http, sheet_name=name,
                           human=owned == "human")
        (state_dir / f"{name}.json").write_text(json.dumps(state, indent=2))
        report[name] = {"state": "SYNCED", "sheet_id": sheet_id,
                        "owned": owned}
    return report
```

The Task 1 per-name `unknown sheet` guard is not dropped — it moved into `resolve_sheets` (Step 7), which `pull_state` calls first, so `test_pull_state_rejects_unknown_sheet_name` (`sheets={"mystery": 5}`) still raises `ValueError` matching `"mystery"` **unchanged**.

SANCTIONED EDIT — `tests/test_smartsheet_pull.py::test_pull_state_writes_files` asserted the old `list[str]` return. Update it to the report shape (the on-disk assertion is unchanged):

```python
def test_pull_state_writes_files(tmp_path, fake_http):
    fake_http.add("GET", "/sheets/111", SHEET)
    report = pull_state(CFG, tmp_path, http=fake_http)
    assert report["issues"]["state"] == "SYNCED"
    assert report["issues"]["sheet_id"] == 111
    on_disk = json.loads((tmp_path / "issues.json").read_text())
    assert on_disk["T-1"]["_parent"] == "E-1"
```

(`CFG` pins `sheets={"issues": 111}` with no `workspace_id`, so `resolve_sheets` makes no workspace call — only the `GET /sheets/111` is queued — and every other schema resolves OFF.)

- [ ] **Step 11: Rewrite `_push` enumeration and `_pull` in `adapters/cli.py`**

In `src/tentpole/adapters/cli.py`, replace `_push` (lines 124-150) with:

```python
def _push(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    try:
        report = smartsheet_load.push_plans(cfg.smartsheet, args.plans,
                                            args.state)
    except ValueError as err:
        # A missing column, an ambiguous workspace name, or an unmet
        # expect: -- print it and drive a nonzero exit (spec §8: a
        # silently failing sync must be impossible).
        print(f"ERROR: {err}")
        return 1
    failed = 0
    # Enumerate EVERY known schema and its resolution every run (spec §2):
    # a renamed/deleted sheet flips to OFF here, never fails silently.
    for name in sorted(report):
        r = report[name]
        if r["state"] == "OFF":
            print(f"{name}: OFF (no explicit id, no sheet named {name!r} "
                  f"in the workspace)")
            continue
        line = (f"{name}: SYNCED sheet {r['sheet_id']}  "
                f"+{r['added']} ~{r['updated']} -{r['removed']}")
        if r["failed"]:
            line += f"  FAILED {len(r['failed'])}"
        print(line)
        for f in r["failed"]:
            print(f"  {f['op']} {f['key']}: {f['error']}")
        failed += len(r["failed"])
    return 1 if failed else 0
```

Replace `_pull` (lines 115-121) so it enumerates every schema's resolution (spec §2: pull is never-silent too — a human sheet going OFF flips to the yaml/none fallback and must be surfaced):

```python
def _pull(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    try:
        report = smartsheet_load.pull_state(cfg.smartsheet, args.state)
    except ValueError as err:
        # An ambiguous workspace name or an unknown smartsheet.sheets key
        # (spec §2/§8) -- print it and drive a nonzero exit.
        print(f"ERROR: {err}")
        return 1
    for name in sorted(report):
        r = report[name]
        if r["state"] == "SYNCED":
            print(f"{name}: SYNCED sheet {r['sheet_id']}")
        elif r["owned"] == "human":
            fallback = ("roster falls back to yaml" if name == "people"
                        else "treated as absent" if name == "future_work"
                        else "falls back to config")
            print(f"{name}: OFF -- no sheet in workspace; {fallback}")
        else:
            print(f"{name}: OFF -- no sheet in workspace")
    return 0
```

- [ ] **Step 12: Port the two affected push tests (SANCTIONED EDIT)**

In `tests/test_smartsheet_push.py`:

Replace `test_push_plans_skips_sheet_without_configured_id` (lines 388-409) with a test of the new OFF behavior:

```python
def test_push_plans_reports_off_for_unresolved_sheet(tmp_path, fake_http):
    # A machine schema with no explicit id and no workspace match resolves
    # OFF -- a normal state printed every run (spec §2), not a failure.
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           sheets={"issues": 111})   # no workspace, no fixversions
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    (plans_dir / "fixversions.json").write_text(json.dumps([
        {"op": "add", "key": "v1", "cells": {"Version": "v1"},
         "parent_key": None}]))
    fake_http.add("GET", "/sheets/111", COLS)
    report = push_plans(cfg, plans_dir, state_dir, http=fake_http)
    assert report["issues"]["state"] == "SYNCED"
    assert report["fixversions"]["state"] == "OFF"
    assert report["fixversions"]["failed"] == []
```

Replace `test_cli_push_missing_sheet_id_exits_nonzero` (lines 412-436) with an exit-0 OFF test:

```python
def test_cli_push_off_sheet_exits_zero_and_enumerates(tmp_path, monkeypatch,
                                                      capsys):
    # OFF is exit 0 (spec §2): the old SKIPPED+exit-1 behavior is removed.
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  sheets:\n    issues: 1\n")
    monkeypatch.setenv("S", "tok")
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    (plans_dir / "fixversions.json").write_text("[]")
    routes = [("GET", "/sheets/1", COLS)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "fixversions: OFF" in out
    assert "issues: SYNCED" in out
```

Also update the three still-valid push tests whose assertions read the report line format — `test_cli_push_exits_nonzero_on_failures` (lines 142-159) stubs `push_plans` returning a dict **without** a `"state"` key, so `_push` now KeyErrors on `r["state"]`. **SANCTIONED EDIT** (fixture correction): update that stub's return to include the new keys:

```python
    def fake_push_plans(cfg, plans, state):
        return {"issues": {"state": "SYNCED", "sheet_id": 1,
                           "added": 0, "updated": 1, "removed": 0,
                           "failed": [{"op": "add", "key": "A-1",
                                       "error": "boom"}]}}
```

(Add this to the sanctioned-edit list for the task. `test_preflight_validates_every_sheet_before_first_write` uses `sheets={"issues": 111, "epics": 222}` with both explicitly pinned — explicit ids still resolve, so it is unaffected and stays as-is.)

- [ ] **Step 13: Add an expect-miss CLI test**

Append to `tests/test_smartsheet_push.py`:

```python
def test_cli_push_expect_miss_exits_nonzero_with_present_names(
        tmp_path, monkeypatch, capsys):
    (tmp_path / "tentpole.yaml").write_text(
        "smartsheet:\n  token_env_var: S\n  workspace_id: 999\n"
        "  expect: [capacity]\n")
    monkeypatch.setenv("S", "tok")
    plans_dir = tmp_path / "plans"
    state_dir = tmp_path / "state"
    plans_dir.mkdir()
    state_dir.mkdir()
    (plans_dir / "issues.json").write_text("[]")
    # Workspace has issues but NOT capacity -> expect miss.
    ws = {"sheets": [{"id": 1234, "name": "issues"}]}
    routes = [("GET", "/workspaces/999", ws)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    code = main(["push", "--config", str(tmp_path / "tentpole.yaml"),
                 "--plans", str(plans_dir), "--state", str(state_dir)])
    out = capsys.readouterr().out
    assert code == 1
    assert "ERROR:" in out
    assert "capacity" in out
    assert "issues" in out          # names the sheets actually present
```

- [ ] **Step 14: Add a pull-fallback test and a pull-enumeration CLI test**

Append to `tests/test_smartsheet_pull.py`:

```python
def test_pull_state_discovers_by_name_and_skips_off(tmp_path, fake_http):
    from tentpole.adapters.smartsheet_load import pull_state
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t",
                           workspace_id=999)
    ws = {"sheets": [{"id": 111, "name": "issues"}]}   # only issues present
    fake_http.add("GET", "/workspaces/999", ws)
    fake_http.add("GET", "/sheets/111", SHEET)
    report = pull_state(cfg, tmp_path, http=fake_http)
    assert report["issues"]["state"] == "SYNCED"
    assert report["people"]["state"] == "OFF"          # discovered nothing
    assert (tmp_path / "issues.json").exists()
    # OFF human sheets (people, future_work) wrote no state file -> cli
    # falls back to yaml / none.
    assert not (tmp_path / "people.json").exists()


def test_cli_pull_enumerates_off_schemas(tmp_path, monkeypatch, capsys):
    # Spec §2: `pull` prints one line per known schema. A human sheet that
    # goes OFF must say so (it silently switches to the yaml fallback).
    monkeypatch.setenv("SS_TOKEN", "secret-token")
    config_path = tmp_path / "tentpole.yaml"
    config_path.write_text(
        "smartsheet:\n"
        "  base_url: https://api.smartsheetgov.com/2.0\n"
        "  token_env_var: SS_TOKEN\n"
        "  workspace_id: 999\n")
    ws = {"sheets": [{"id": 111, "name": "issues"}]}   # only issues present
    routes = [("GET", "/workspaces/999", ws), ("GET", "/sheets/111", SHEET)]
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(routes))
    exit_code = main(["pull", "--config", str(config_path),
                      "--state", str(tmp_path / "state")])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "issues: SYNCED sheet 111" in out
    assert "people: OFF" in out
    assert "falls back to yaml" in out                 # human fallback note
```

- [ ] **Step 15: Run everything**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: green. New tests: config +2; resolver +4 (explicit-beats, no-workspace-all-off, ambiguous, unknown-explicit-key); expect-miss +1; pull-fallback +1; pull-enumeration CLI +1 = **+9**. Two push tests replaced in place, the stubbed-`push_plans` dict and `test_pull_state_writes_files` edited in place (all net 0). **246 + 9 = 255.**

- [ ] **Step 16: Commit**

```bash
git add src/tentpole/adapters/config.py src/tentpole/adapters/smartsheet_load.py src/tentpole/adapters/cli.py tests/test_adapter_config.py tests/test_smartsheet_push.py tests/test_smartsheet_pull.py
git commit -m "feat: sheet name resolution, expect:, OFF enumeration; remove SKIPPED (spec §2)"
```

**Running total: 255.**

---

## Task 8: `bootstrap --sheets a,b,c` (spec §2)

`bootstrap` gains an optional `--sheets` subset (default remains all known schemas). Still experimental until smoked on SmartsheetGov.

**Files:**
- Modify: `src/tentpole/adapters/smartsheet_load.py` — `bootstrap` (lines 292-312)
- Modify: `src/tentpole/adapters/cli.py` — `add_parsers` bootstrap (lines 48-50), `_bootstrap` (lines 203-216)
- Test: `tests/test_bootstrap.py` (append)

**Interfaces:**
- Produces: `bootstrap(cfg, http=request, names=None) -> dict[str, int]`. `names=None` → all `SCHEMAS`; a list → that subset (each validated against `SCHEMAS`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bootstrap.py`:

```python
def test_bootstrap_subset_creates_only_named(fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    for i, name in enumerate(["issues", "capacity"]):
        fake_http.add("POST", "/sheets",
                      {"result": {"id": 2000 + i, "name": f"tentpole {name}"}})
    created = bootstrap(cfg, http=fake_http, names=["issues", "capacity"])
    assert set(created) == {"issues", "capacity"}
    assert len(fake_http.calls) == 2


def test_bootstrap_subset_rejects_unknown_name(fake_http):
    cfg = SmartsheetConfig(base_url="https://x/2.0", token="t")
    with pytest.raises(ValueError, match="mystery"):
        bootstrap(cfg, http=fake_http, names=["issues", "mystery"])
```

Add `import pytest` at the top of `tests/test_bootstrap.py` if not present (it is not — add it).

- [ ] **Step 2: Run to verify fail**

```bash
python -m pytest tests/test_bootstrap.py -k subset -q
```
Expected: FAIL — `bootstrap()` has no `names` argument.

- [ ] **Step 3: Extend `bootstrap`**

In `src/tentpole/adapters/smartsheet_load.py`, change the `bootstrap` signature and add the subset guard. Replace the first lines of `bootstrap` (through the `created = {}` line) with:

```python
def bootstrap(cfg, http=request, names=None) -> dict[str, int]:
    """Create sheets from SCHEMAS (all, or the --sheets subset). Lowest-
    priority path (spec §7): NOT integration-tested against SmartsheetGov;
    the supported v1 path is manual creation from `tentpole schema show`."""
    if names is None:
        names = list(SCHEMAS)
    unknown = [n for n in names if n not in SCHEMAS]
    if unknown:
        raise ValueError(
            f"unknown sheet name(s) {unknown} for --sheets "
            f"(known: {sorted(SCHEMAS)})")
    path = (f"/workspaces/{cfg.workspace_id}/sheets"
            if cfg.workspace_id else "/sheets")
    created = {}
```

Then change the loop header from `for name, schema in SCHEMAS.items():` to iterate the chosen subset:

```python
    for name in names:
        schema = SCHEMAS[name]
```

(The loop body — building `columns` and POSTing — is unchanged.)

- [ ] **Step 4: Wire `--sheets` into the CLI**

In `src/tentpole/adapters/cli.py`, in `add_parsers`, change the bootstrap parser block (lines 48-50) to:

```python
    boot_cmd = sub.add_parser(
        "bootstrap", help="create sheets from schemas (experimental)")
    boot_cmd.add_argument("--config", required=True, type=Path)
    boot_cmd.add_argument(
        "--sheets", default=None,
        help="comma-separated subset to create (default: all known schemas)")
```

In `_bootstrap` (lines 203-216), change the `created = ...` line from:

```python
    created = smartsheet_load.bootstrap(cfg.smartsheet)
```

to:

```python
    names = ([s.strip() for s in args.sheets.split(",") if s.strip()]
             if args.sheets else None)
    created = smartsheet_load.bootstrap(cfg.smartsheet, names=names)
```

Note: `test_cli_bootstrap_prints_config_snippet` monkeypatches `bootstrap` with `lambda cfg: {...}` — a one-arg lambda. Because `_bootstrap` now calls `bootstrap(cfg.smartsheet, names=names)`, that stub breaks. **SANCTIONED EDIT** (fixture correction) in `tests/test_bootstrap.py`: change the monkeypatch lambda (line 44-45) to accept the keyword:

```python
    monkeypatch.setattr(edge_cli.smartsheet_load, "bootstrap",
                        lambda cfg, names=None: {"issues": 1000, "epics": 1001})
```

- [ ] **Step 5: Run to verify pass**

```bash
python -m pytest tests/test_bootstrap.py -q
```
Expected: PASS.

- [ ] **Step 6: Full suite**

```bash
python -m pytest -q 2>&1 | tail -1
```
Expected: `257 passed` (255 + 2).

- [ ] **Step 7: Commit**

```bash
git add src/tentpole/adapters/smartsheet_load.py src/tentpole/adapters/cli.py tests/test_bootstrap.py
git commit -m "feat: bootstrap --sheets subset (spec §2)"
```

**Running total: 257.**

---

## Task 9: README updates (no version bump)

Document the new setup story: name resolution and existence-as-config, the people sheet, `expect:`, the capacity double-count rule, the migration note from `team`/`exceptions`, and the smoke-before-trust caveats for workspace discovery and `bootstrap --sheets`. **No version bump** (0.5.0 ships after Plan 5b).

**Files:**
- Modify: `README.md`

There are no code tests for docs; the check is that the README no longer instructs mandatory six-sheet config and describes the people sheet.

- [ ] **Step 1: Replace the Quickstart `smartsheet:` block and `core:` block**

In `README.md`, replace the `smartsheet:` example (lines 48-64) with:

```yaml
   smartsheet:
     # Gov deployments: https://api.smartsheetgov.com/2.0
     base_url: https://api.smartsheet.com/2.0
     token_env_var: SMARTSHEET_TOKEN
     workspace_id: 999             # enables discovery: a sheet syncs
                                   # because it exists, named for its schema
     sheets:                       # optional; an explicit id always wins
       issues: 111                 # over discovery. Pin only what you must.
     expect: [issues]              # optional strictness: any expected schema
                                   # that resolves OFF is an error + exit 1
   core:
     team:                         # list form = roster only, OR map form:
       ada: {}                     #   roster + recurring non-Jira burden
       grace: {ops rotation: 2}    #   (days/sprint; labels are documentation)
     sprints_per_plan: 6           # how many sprints a plan+N bucket spans
                                   # AND is priced at (default 6)
   ```
```

- [ ] **Step 2: Rewrite step 2 (sheet creation) and the discovery paragraph**

Replace the current step 2 (lines 66-68) with:

```markdown
2. Create at least an `issues` sheet: print `tentpole schema show` and
   build it by hand in your workspace (supported path), or try the
   experimental `tentpole bootstrap --config tentpole.yaml` (optionally
   `--sheets issues,capacity` for a subset). Minimum viable setup is one
   `workspace_id` plus one `issues` sheet — every other machine sheet is
   opt-in and simply OFF until it exists.

   **Sheets resolve by name.** For each schema (`issues`, `capacity`,
   `fixversions`, `dependencies`, `accuracy`, `people`, `future_work`),
   tentpole uses the explicit id under `smartsheet.sheets` if present,
   otherwise a sheet in `workspace_id` whose name matches the schema name
   exactly, otherwise the schema is OFF. Every `push` and `pull` prints one
   line per schema — SYNCED or OFF — so a renamed or deleted sheet flips to
   OFF in the very next run instead of failing silently. `expect:` turns an
   unwanted OFF into a hard error. Two sheets sharing a schema name is a
   config error naming both ids.

   **Smoke discovery before you trust it.** Workspace listing and
   `bootstrap --sheets` are shape-sensitive against the live API. Run one
   real `tentpole pull` (or `bootstrap`) against your instance and confirm
   the resolution lines before wiring into a scheduled sync.
```

- [ ] **Step 2b: Replace the "The Team sheet" section with "The people sheet"**

Replace the entire `### The Team sheet` section (lines 115-128) with:

```markdown
### The people sheet

The roster and recurring non-Jira burden live in one human-owned `people`
sheet (it replaces the 0.4.x `team` and `exceptions` sheets). It is
optional: without it, `core: team:` in `tentpole.yaml` is the roster and
the map form supplies recurring burden.

Rows are hierarchical:

- **Root rows are the roster** — one row per person; `Item` must match the
  Jira display name exactly. A present sheet is authoritative (including
  present-but-empty → empty team); an absent sheet falls back to
  `core: team:`. `team_drift` flags mismatches in both directions.
- **Child rows are burdens.** `Sprint` blank → recurring, every sprint
  (fed into capacity). `Sprint` set → a one-off in that sprint. `Days` is
  fractional-friendly (`0.5` for a half-day rotation); `Sprint` must be a
  whole sprint id.

Columns: `Item` (primary), `Sprint`, `Days`, `Notes`. Fail-loud rules
(each an actionable error naming the sheet and row): `Days` on a person
row, a burden nested under a burden (no grandchildren), a child with no
`Days`, a fractional `Sprint`, and duplicate person or duplicate
(person, item) rows. A one-off whose sprint is not in the current plan is
reported as a yellow `unmatched_exception` finding, never silently dropped.

**Capacity and recurring burden are never double-counted.** Recurring
burden reduces a person's capacity only while their throughput comes from
the prior; once there is enough history for an empirical throughput, the
burden is already baked into the measurement (spec §4). A recurring burden
larger than the prior yields non-positive capacity on purpose — it fires
every capacity check for someone fully allocated to non-Jira work.

Keep `core: team:` in `tentpole.yaml` even once the people sheet exists:
`tentpole check` reads only the bundle and has no access to sheet state
(only `sync` reads state), so removing `core: team:` makes `check` treat
the roster as empty.
```

- [ ] **Step 3: Add a migration note near the top of Quickstart**

After the Quickstart heading paragraph (before step 1, ~line 34), add:

```markdown
> **Upgrading from 0.4.x.** The `team` and `exceptions` sheets are no
> longer recognized — rename/rebuild them into one `people` sheet (roster
> as root rows, exceptions as child rows with `Sprint` set). `push` no
> longer exits 1 on an unconfigured machine sheet; that strictness now
> lives in `expect:`. See "The people sheet" below.
```

- [ ] **Step 4: Sanity-check the README renders and mentions the new concepts**

```bash
grep -n "people sheet\|resolve by name\|expect:\|double-count\|OFF" README.md | head
```
Expected: matches present. No `team: 777` / "All six machine-owned sheets must be configured" text remains:

```bash
grep -n "All six machine-owned\|team: 777" README.md
```
Expected: no output.

- [ ] **Step 5: Full suite (unchanged) and commit**

```bash
python -m pytest -q 2>&1 | tail -1   # Expected: 257 passed
git add README.md
git commit -m "docs: name resolution, people sheet, expect:, double-count rule (spec §2-§4)"
```

**Running total: 257. Plan 5a complete.**

---

## 5a Self-Review

Run after all tasks. This is a checklist, not a subagent dispatch.

1. **Spec coverage (§2, §3, §4, §8, §9, §10):**
   - §8 pull keying → Task 1 ✓ (with the §8/§11 tension flagged).
   - §2 resolution order / OFF enumeration on push **and** pull / expect / remove SKIPPED / bootstrap --sheets / pull fallback / preserved unknown-key guard (moved to `resolve_sheets`) → Tasks 7, 8 ✓.
   - §3 people sheet (schema, parser, fail-loud rules, yaml map form + list back-compat, team/exceptions removed, sync wiring) → Tasks 2, 4, 5, 6 ✓.
   - §4 capacity rule (`recurring_days`, `effective_throughput_for` wired into all three consumers — `capacity_for`, `team_subscription`, `tentpole_runway` — one-off unchanged, no clamp, spec comment in code) → Tasks 2, 3 ✓.
   - README for all of it, no version bump → Task 9 ✓.
2. **Placeholder scan:** every code step shows complete code; every test step shows the assertion; every command has an expected result. No TBD/TODO.
3. **Type consistency:** `effective_throughput_for(bundle, person)`; `people_from_sheet(rows) -> PeopleSheet(team, recurring_days, exceptions)`; `resolve_sheets(cfg, http) -> dict[str, int|None]`; `_workspace_sheets(cfg, http) -> dict[str, list[int]]`; `push_plans`/`pull_state` report entries carry `state`/`sheet_id` (pull adds `owned`); `_push` and `_pull` both read those keys. Names used in later tasks (Task 6 imports `people_from_sheet`; Task 7 `resolve_sheets`) match their definitions.
4. **Tasks 7 & 8 re-review (post-verifier fixes):** unknown-key guard verified preserved — `test_pull_state_rejects_unknown_sheet_name` (`sheets={"mystery":5}`) still raises via `resolve_sheets`, unchanged; pull enumeration reaches `_pull` output (new `test_cli_pull_enumerates_off_schemas`); the `pull_state` return-shape change is the only added sanctioned edit and `_push`/`_pull` both consume the new keys; `bootstrap(cfg, http, names=None)` and its CLI monkeypatch stub agree.

---
