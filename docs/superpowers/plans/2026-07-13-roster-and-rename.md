# 0.3.0 — Team Roster Sheet, Drift Check, and token_env_var Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the team roster out of static config into a human-owned Smartsheet Team sheet (with `core: team:` as fallback), add a two-direction roster-drift check, and rename the confusing `token_env:` config key to `token_env_var:` — shipped as tentpole 0.3.0.

**Architecture:** The Team sheet follows the exact pattern Future Work and Exceptions already use: a human-owned schema in `SCHEMAS`, a parser in `humansheets.py`, and read-back in the sync CLI's `_state()` flow (absent file → `core: team:` fallback; present file → authoritative, even when empty). The drift check is a pure core check like the existing six, surfacing in findings/SYNC HEALTH/`plan check` automatically. The rename is a clean pre-1.0 breaking change with an actionable error on the old key.

**Tech Stack:** Python ≥3.12, stdlib + pyyaml, pytest. No new dependencies.

## Global Constraints

- Runtime dependencies stay exactly `["pyyaml>=6"]`; core purity unchanged (no I/O or clock outside `adapters/`, `cli.py`, `model.load_bundle`, `hygiene.load_rules`).
- Fail loudly but actionably (the `humansheets._number` posture) for every new human-input path: duplicate roster entries, old/missing config keys.
- The new `team_drift` check must NOT fire on an empty plan (no sprint demand at all) and must count only **real** demand (`kind == "real"`) for the "working but not in team" direction — ghost owners are hand-typed and overhead is excluded by the kind filter. For the "in team but no work" direction, presence counts real OR ghost sprint demand.
- Existing tests are append-only EXCEPT the exact edits sanctioned by name in Tasks 1 and 2 (YAML fixture key rename; schema-registry set). Nothing else may be touched.
- Suite counts per task: **161 / 163 / 164 / 168 / 168** (from 159). If a count diverges, investigate — do not paper over.
- Run everything from the repo root with the project venv: `.venv/bin/pytest`, `.venv/bin/python`.

## File Structure

```
src/tentpole/adapters/config.py   MODIFY  Task 1 (key rename + actionable errors)
README.md                         MODIFY  Task 1 (config example), Task 5 (team docs)
src/tentpole/schema.py            MODIFY  Task 2 (team schema)
src/tentpole/humansheets.py       MODIFY  Task 2 (team_from_sheet)
src/tentpole/cli.py               MODIFY  Task 3 (sync reads team sheet), Task 4 (_SECTION_ORDER)
src/tentpole/checks.py            MODIFY  Task 4 (team_drift)
src/tentpole/diagnostics.py       MODIFY  Task 4 (assemble wires team_drift)
pyproject.toml                    MODIFY  Task 5 (version 0.3.0)
tests/test_adapter_config.py      MODIFY  Task 1 (+2; fixture key rename)
tests/test_fix_apply.py           MODIFY  Task 1 (fixture key rename only)
tests/test_smartsheet_push.py     MODIFY  Task 1 (fixture key rename only)
tests/test_bootstrap.py           MODIFY  Task 1 (fixture key rename only)
tests/test_jira_extract_bundle.py MODIFY  Task 1 (fixture key rename only)
tests/test_schema.py              MODIFY  Task 2 (registry set + one assert)
tests/test_humansheets.py         MODIFY  Task 2 (+2)
tests/test_cli_sync.py            MODIFY  Task 3 (+1)
tests/test_checks_capacity.py     MODIFY  Task 4 (+4)
```

---

### Task 1: Rename `token_env:` → `token_env_var:`

`token_env: JIRA_TOKEN` reads as if the token IS "JIRA_TOKEN". The new key reads naturally: "the token env var is JIRA_TOKEN". Pre-1.0, this is a clean break: the old key produces an actionable rename error, a missing key produces an actionable what-goes-here error. All YAML fixtures across the test suite are updated in the same commit (sanctioned modification — it is a pure key rename inside fixture strings; no assertion changes except the one noted).

**Files:**
- Modify: `src/tentpole/adapters/config.py` (`_token`)
- Modify: `README.md` (Quickstart config example)
- Test: `tests/test_adapter_config.py` (+2, plus fixture renames); fixture-string renames only in `tests/test_fix_apply.py`, `tests/test_smartsheet_push.py`, `tests/test_bootstrap.py`, `tests/test_jira_extract_bundle.py`

**Interfaces:**
- Config file key `token_env_var:` replaces `token_env:` in both `jira:` and `smartsheet:` sections. `load_config` signature unchanged.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_adapter_config.py`:

```python
def test_old_token_env_key_gets_actionable_rename_error(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env: T\n  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="token_env_var"):
        load_config(_write(tmp_path, text), env={"T": "tok"})


def test_missing_token_env_var_key_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="token_env_var"):
        load_config(_write(tmp_path, text), env={})
```

- [ ] **Step 2: Rename the key in every test fixture** (YAML strings only — this is the sanctioned modification):

Run: `grep -rl 'token_env:' tests/ | xargs sed -i '' 's/token_env:/token_env_var:/g'`
Then verify: `grep -rn 'token_env:' tests/` → no output, and `grep -rn 'token_env_var:' tests/ | wc -l` → matches the previous count.

(Note for `test_missing_token_env_raises` in test_adapter_config.py: after the fixture rename it exercises the unset-env-var path via `token_env_var: NOPE` and its `match="NOPE"` assertion still holds — do not otherwise edit it.)

- [ ] **Step 3: Run to verify failures**

Run: `.venv/bin/pytest tests/test_adapter_config.py -v`
Expected: the two new tests FAIL (old key currently works; missing key currently raises KeyError, not ValueError). The renamed fixtures also FAIL against current code (`token_env_var` unknown) — that is expected and confirms the rename is load-bearing.

- [ ] **Step 4: Implement** — in `src/tentpole/adapters/config.py`, replace `_token` with:

```python
def _token(section: dict, env: dict) -> str:
    if "token_env" in section:
        raise ValueError(
            "config key 'token_env' was renamed to 'token_env_var' "
            "(it holds the NAME of the environment variable containing "
            "the token, never the token itself)")
    if "token_env_var" not in section:
        raise ValueError(
            "missing 'token_env_var': the name of the environment "
            "variable holding the API token (the token itself never "
            "goes in this file)")
    var = section["token_env_var"]
    if var not in env:
        raise ValueError(
            f"environment variable {var!r} (named by token_env_var) is "
            f"not set")
    return env[var]
```

In `README.md`, update the Quickstart config example — replace both token lines:

```yaml
     token_env: JIRA_TOKEN          # token read from this env var
```
becomes
```yaml
     token_env_var: JIRA_TOKEN      # NAME of the env var holding the
                                    # token; the token itself never
                                    # lives in this file
```
and
```yaml
     token_env: SMARTSHEET_TOKEN
```
becomes
```yaml
     token_env_var: SMARTSHEET_TOKEN
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **161 passed** (159 + 2).

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/adapters/config.py README.md tests/
git commit -m "feat!: rename token_env config key to token_env_var"
```

---

### Task 2: Team sheet schema and parser

A human-owned `team` sheet — one row per person, Person column matching Jira display names exactly — following the Future Work / Exceptions pattern. Duplicate entries fail loudly (a duplicate is always a human error, and silent dedupe would hide a typo'd near-duplicate).

**Files:**
- Modify: `src/tentpole/schema.py` (add `team` to SCHEMAS)
- Modify: `src/tentpole/humansheets.py` (add `team_from_sheet`)
- Test: `tests/test_schema.py` (sanctioned edits), `tests/test_humansheets.py` (+2)

**Interfaces:**
- Produces: `SCHEMAS["team"]` — human-owned, columns `Person` (primary) and `Notes`; `team_from_sheet(rows: dict[str, dict]) -> list[str]` returning roster in sheet order, blank rows skipped, `ValueError` on duplicates. Consumed by Task 3's CLI wiring.
- Side effects that need no code: `tentpole pull` accepts `team:` in config `sheets:` (validated against SCHEMAS); `tentpole push` ignores it (machine sheets only); `bootstrap` now creates it; `schema show` now prints it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_humansheets.py`:

```python
from tentpole.humansheets import team_from_sheet


def test_team_from_sheet_orders_and_skips_blanks():
    rows = {
        "1": {"Person": "Ada Lovelace", "_row_id": 1},
        "2": {"Person": "  "},
        "3": {"Person": "Grace Hopper", "Notes": "on loan until Q4"},
    }
    assert team_from_sheet(rows) == ["Ada Lovelace", "Grace Hopper"]


def test_team_from_sheet_rejects_duplicates():
    rows = {"1": {"Person": "Ada Lovelace"},
            "2": {"Person": "Ada Lovelace"}}
    with pytest.raises(ValueError, match="Ada Lovelace"):
        team_from_sheet(rows)
```

In `tests/test_schema.py` (sanctioned edits, exactly these two):
1. In `test_registry_has_all_sheets_with_ownership`, add `"team"` to the expected set and append the assertion `assert SCHEMAS["team"].owned == "human"`.
2. In `test_human_sheets_have_no_synced_columns`, append `assert SCHEMAS["team"].synced_names() == []`.

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_humansheets.py tests/test_schema.py -v`
Expected: the two new humansheets tests FAIL with ImportError; the registry test FAILS on the missing `"team"` key.

- [ ] **Step 3: Implement**

In `src/tentpole/schema.py`, append to the `SCHEMAS` dict (after `"exceptions"`):

```python
    "team": _human(
        "team",
        ColumnDef("Person", primary=True),
        ColumnDef("Notes"),
    ),
```

In `src/tentpole/humansheets.py`, append:

```python
def team_from_sheet(rows: dict[str, dict]) -> list[str]:
    """Roster from the human-owned Team sheet, in sheet order. Person
    must match the Jira display name exactly -- the team_drift check
    flags mismatches as roster drift."""
    team: list[str] = []
    for cells in rows.values():
        person = _text(cells, "Person")
        if not person:
            continue
        if person in team:
            # A duplicate is always a human error; silent dedupe would
            # hide a typo'd near-duplicate right next to it.
            raise ValueError(
                f"team sheet lists {person!r} more than once")
        team.append(person)
    return team
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **163 passed** (161 + 2).

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/schema.py src/tentpole/humansheets.py tests/test_schema.py tests/test_humansheets.py
git commit -m "feat: human-owned team roster sheet schema and parser"
```

---

### Task 3: Sync reads the Team sheet (config fallback)

`tentpole sync` consumes `<state>/team.json` exactly like future_work/exceptions: file absent → `core: team:` from the bundle stands (bundles without sheet state keep working); file present → authoritative, INCLUDING present-but-empty (a human who emptied the roster means it — same posture as the Plan 3 H3 fix for future_work). `tentpole check` is unaffected (it reads only the bundle; extract-written bundles carry `core: team:`).

**Files:**
- Modify: `src/tentpole/cli.py` (sync handler)
- Test: `tests/test_cli_sync.py` (+1)

**Interfaces:**
- Consumes: Task 2's `team_from_sheet`; the existing `_state()` helper (returns `None` for absent, `{}` for present-empty) and `replace` import in cli.py.

- [ ] **Step 1: Write the failing test** — append to `tests/test_cli_sync.py` (uses the file's existing `dirs` fixture, whose bundle config has `team: ["ada"]` and one T-1 task assigned to ada):

```python
def test_sync_team_sheet_overrides_bundle_config(dirs):
    bundle, state, out = dirs
    (state / "team.json").write_text(json.dumps({
        "r1": {"Person": "grace", "_row_id": 1, "_parent": None}}))
    rc = main(["sync", "--bundle", str(bundle), "--state", str(state),
               "--out", str(out)])
    assert rc == 0
    cap = json.loads((out / "plans" / "capacity.json").read_text())
    keys = {c["key"] for c in cap}
    assert any(k.startswith("grace|") for k in keys)
    assert not any(k.startswith("ada|") for k in keys)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_cli_sync.py::test_sync_team_sheet_overrides_bundle_config -v`
Expected: FAIL — capacity rows are still built for ada (config roster), none for grace.

- [ ] **Step 3: Implement** — in `src/tentpole/cli.py`:

Add `team_from_sheet` to the existing humansheets import:

```python
from tentpole.humansheets import (exceptions_from_sheet, ghosts_from_sheet,
                                  team_from_sheet)
```

In the sync handler, immediately after the `exceptions` block (`bundle = replace(bundle, exceptions=...)`), add:

```python
        team_sheet = _state("team")
        if team_sheet is not None:
            # Present is authoritative, including present-but-empty --
            # same posture as future_work above. Absent keeps the
            # bundle's core: team: fallback.
            bundle = replace(
                bundle,
                config=replace(bundle.config,
                               team=team_from_sheet(team_sheet)))
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **164 passed** (163 + 1).

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/cli.py tests/test_cli_sync.py
git commit -m "feat: sync derives team roster from the team sheet when present"
```

---

### Task 4: `team_drift` check

Two directions, both yellow, both subject = the person (so `plan check --me` picks them up automatically):
- **Working but not in team:** someone with real sprint demand who isn't on the roster — roster drift or a Jira display-name mismatch. Counts `kind == "real"` only (overhead is a different kind and is excluded; ghost owners are hand-typed).
- **In team but no work:** a roster member with no real or ghost sprint demand — but ONLY when the plan has any demand at all, so an empty pre-planning bundle stays quiet (this guard is also what keeps every existing test fixture green).

The findings flow into SYNC HEALTH's per-check counts and the `check` CLI without any report-schema change.

**Files:**
- Modify: `src/tentpole/checks.py` (new check)
- Modify: `src/tentpole/diagnostics.py` (wire into `assemble`)
- Modify: `src/tentpole/cli.py` (`_SECTION_ORDER`)
- Test: `tests/test_checks_capacity.py` (+4)

**Interfaces:**
- Produces: `team_drift(bundle, buckets, demand) -> list[Finding]`, same shape as the existing six checks; check name string `"team_drift"`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_checks_capacity.py`. The file already imports `buckets_for`, `compile_demand`, `Ghost`, and defines `_task(key, person, est, sprint_id=None, **kw)` (person and estimate are POSITIONAL). The only import change needed: extend the existing checks import line to

```python
from tentpole.checks import sprint_overload, team_drift, team_subscription
```

then append:

```python
def _drift_findings(bundle):
    buckets = buckets_for(bundle)
    return team_drift(bundle, buckets, compile_demand(bundle, buckets))


def test_team_drift_flags_both_directions(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", "ada", 3.0, sprint_id=1),
        _task("T-2", "hopper", 4.0, sprint_id=1),
    ])   # team is ["ada", "grace"]
    findings = _drift_findings(b)
    by_subject = {f.subject: f for f in findings}
    assert set(by_subject) == {"hopper", "grace"}
    assert all(f.check == "team_drift" and f.severity == "yellow"
               for f in findings)
    assert "4.0d" in by_subject["hopper"].message
    assert "not in team" in by_subject["hopper"].message
    assert "no work" in by_subject["grace"].message


def test_team_drift_quiet_when_roster_matches_work(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", "ada", 3.0, sprint_id=1),
        _task("T-2", "grace", 1.0, sprint_id=1),
    ])
    assert _drift_findings(b) == []


def test_team_drift_quiet_on_empty_plan(make_bundle):
    assert _drift_findings(make_bundle()) == []


def test_team_drift_ghost_counts_as_presence(make_bundle):
    b = make_bundle(
        issues=[_task("T-1", "ada", 3.0, sprint_id=1)],
        ghosts=[Ghost(title="future thing", estimate_days=5.0,
                      target="sprint:2", owner="grace")])
    assert _drift_findings(b) == []
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_checks_capacity.py -v`
Expected: the four new tests FAIL with ImportError on `team_drift`; existing tests pass.

- [ ] **Step 3: Implement**

Append to `src/tentpole/checks.py`:

```python
def team_drift(bundle: Bundle, buckets: list[Bucket],
               demand: list[DemandItem]) -> list[Finding]:
    findings = []
    sprint_ids = {bk.id for bk in buckets if bk.id.startswith("sprint:")}
    real_days: dict[str, float] = {}
    for d in demand:
        if d.who and d.bucket_id in sprint_ids and d.kind == "real":
            real_days[d.who] = real_days.get(d.who, 0.0) + d.estimate_days
    present = set(real_days) | {
        d.who for d in demand
        if d.who and d.bucket_id in sprint_ids and d.kind == "ghost"}
    team = set(bundle.config.team)
    for person in sorted(set(real_days) - team):
        findings.append(Finding(
            "team_drift", "yellow", person, None,
            f"{person} has {real_days[person]:.1f}d of sprint work but is "
            f"not in team — roster drift or a display-name mismatch"))
    if present:   # an empty plan (pre-planning week) should not flag anyone
        for person in sorted(team - present):
            findings.append(Finding(
                "team_drift", "yellow", person, None,
                f"{person} is in team but has no work in the current plan"))
    return findings
```

In `src/tentpole/diagnostics.py`: add `team_drift` to the `tentpole.checks` import list, and extend the findings chain in `assemble` with a final line:

```python
        + team_drift(bundle, buckets, demand)
```

In `src/tentpole/cli.py`, append `"team_drift"` to `_SECTION_ORDER`:

```python
_SECTION_ORDER = [
    "sprint_overload", "deadline_risk", "tentpole_runway",
    "dependency_readiness", "ghost_claims", "team_subscription",
    "team_drift",
]
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **168 passed** (164 + 4), with zero existing-test failures — the empty-plan guard and real-demand filter are what keep the existing diagnostics/CLI fixtures quiet; if any existing test breaks, the guards are implemented wrong (do NOT edit the existing test).

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/checks.py src/tentpole/diagnostics.py src/tentpole/cli.py tests/test_checks_capacity.py
git commit -m "feat: team_drift check flags roster/work mismatches in both directions"
```

---

### Task 5: Docs and version 0.3.0

**Files:**
- Modify: `README.md`, `pyproject.toml`

**Interfaces:** none.

- [ ] **Step 1: Update `README.md`**

In the Quickstart config example's `sheets:` map, add a `team:` line after the machine sheets (keep the existing comment style):

```yaml
       team: 777                    # human-owned roster sheet (optional)
```

After the Quickstart step that creates the sheets, add a short subsection:

```markdown
### The Team sheet

The team roster lives in a human-owned `team` sheet (one row per
person; `Person` must match the Jira display name exactly). `tentpole
pull` reads it back and `sync` uses it as the roster; if the sheet is
absent, the `core: team:` list in `tentpole.yaml` is the fallback. The
`team_drift` check flags mismatches in both directions — someone with
sprint work who is not on the roster (drift, or a display-name typo),
and a roster member with no work in the current plan.
```

- [ ] **Step 2: Bump the version** — in `pyproject.toml`, replace `version = "0.2.1"` with `version = "0.3.0"`.

- [ ] **Step 3: Verify build and suite**

Run: `rm -rf dist && .venv/bin/python -m build --sdist --wheel 2>&1 | tail -2`
Expected: `Successfully built tentpole-0.3.0.tar.gz and tentpole-0.3.0-py3-none-any.whl`

Run: `.venv/bin/pytest -q`
Expected: **168 passed**.

- [ ] **Step 4: Commit** (do not commit `dist/`):

```bash
git add README.md pyproject.toml
git commit -m "chore: document the team sheet, version 0.3.0"
```

---

## Self-Review Notes

- Scope: both Juno-decided items (rename with actionable errors; roster from Smartsheet with config fallback) plus the drift check she accepted as part of option 2+3. `token_cmd` deliberately out (parked). The 0.2.2-ish residuals from the patch review (Retry-After cap, board_id/workspace_id coercion, `Secret | str` annotation, CHANGELOG) are deliberately out of scope here.
- Breaking changes for 0.3.0 (hence the minor bump, `feat!` commit): `token_env` key rejected with a rename message; new human-owned `team` sheet appears in `schema show` and `bootstrap`.
- Type consistency checked: `team_from_sheet` returns `list[str]` → `replace(bundle.config, team=...)` (Config.team is `list[str]`); `team_drift` matches the six existing check signatures; `_state()` None-vs-{} semantics reused verbatim.
- Existing-test blast radius: verified against the actual fixtures — `test_personal_filters` (exact equality) has both members carrying real sprint demand → drift quiet; the milestone/runway test uses membership assertions → drift findings harmless; CLI exit codes unaffected (drift is yellow). The only sanctioned existing-test edits are enumerated in Tasks 1 and 2.
- Placeholder scan: clean; suite counts 159 → 168.
