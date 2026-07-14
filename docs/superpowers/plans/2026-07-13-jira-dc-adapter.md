# 0.4.0 — Jira Data Center / Server Extract Adapter + Configurable Plan Length Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-07-13-jira-data-center-adapter.md`. Every
requirement that binds an implementer is restated inline below — you do not need
to open the spec to execute any task.

**Requires 0.3.0 merged.** This plan is written against the codebase *after* the
0.3.0 release (team roster sheet, `team_drift` check, `token_env:` →
`token_env_var:` rename). Do not start until 0.3.0 is on `master` and
`.venv/bin/pytest -q` reports **168 passed**. Every YAML example here uses
`token_env_var:`; `checks.py` already has `team_drift`; `cli.py`'s
`_SECTION_ORDER` already ends with `"team_drift"`.

**Goal:** Ship a second Jira extract adapter for Jira Data Center / Server that
emits the *identical* bundle the Cloud adapter emits, and replace the hardcoded
six-sprint planning horizon with a configurable `sprints_per_plan`.

**Architecture:** Everything that is not deployment-specific — issue parsing,
changelog cycle dates, sprint-id normalization, external-issue stubbing, and the
fetch loops themselves — moves into a new `adapters/jira_common.py`. Each adapter
supplies only what actually differs: its auth header, its search-pagination
primitive (Cloud's `nextPageToken` cursor vs Data Center's
`startAt`/`maxResults`/`total` offsets), its API version, and where the epic key
lives (Cloud: `fields.parent`; Data Center: a configured `epic_link_field` custom
field). The fetch loops are shared *including* `fetch_hygiene`, so hygiene JQL
evaluation works on Data Center without a second fork. The write path
(`jira_write.py`, driven by `tentpole fix apply`) follows the same rule: its auth
already comes free from the shared header builder, its endpoint paths become
version-aware, and its one deployment-specific payload — `set_parent` — mirrors
the read side exactly, writing the epic key back into the same custom field the
Data Center adapter reads it from. Separately,
`sprints_per_plan` becomes one number in the core `Config` from which both the
coarse-bucket date spans (`buckets.py`) and the coarse-bucket capacity scale
(`checks.py`) are derived, so the two can never disagree.

**Tech Stack:** Python ≥3.12, stdlib + pyyaml, pytest. No new dependencies.

## Global Constraints

- **Pure core.** No I/O and no clock anywhere under `src/tentpole/` EXCEPT
  `model.load_bundle`, `hygiene.load_rules`, `cli.py`, and `adapters/`.
  `date.today()` appears only in adapters. The new `jira_common.py` lives under
  `adapters/` and is the only new module allowed to touch the network.
- **Fail loud but actionable.** A silently failing sync must be impossible. Any
  unknown shape raises `ValueError`/`KeyError` whose message names the offending
  value *and* the fix. The house style is `_status_category` in
  `adapters/jira_extract.py`: it re-raises `KeyError` with
  `f"unknown Jira statusCategory key {key!r}; known keys are {sorted(_CATEGORY)} -- update tentpole's _CATEGORY map"`.
  Never return `None` to paper over an unrecognized non-empty value.
- **Tokens are env-var-indirect.** Config files name an environment variable
  (`token_env_var:`) and never hold a token. Tokens live in the `Secret` wrapper
  from `adapters/config.py`; `.reveal()` is called only at header-construction
  sites.
- **stdlib only.** `urllib` stays behind the injectable `request`/`transport`
  seam in `adapters/http.py`. Runtime dependencies stay exactly
  `["pyyaml>=6"]`.
- **TDD, bite-sized steps, frequent commits.** Write the failing test, watch it
  fail, write the minimal code, watch it pass, commit.
- **Existing tests are append-only.** Appending new tests (and the constants they
  need) to an existing test file is always fine. Beyond that, the only sanctioned
  edits to existing test files are the *import-line additions* named in Task 1
  and the new `make_http` *fixture* added to `tests/conftest.py` in Task 6. No
  existing test body or assertion may be changed: if an existing test breaks, the
  new code is wrong — fix the code, not the test.
- **Suite counts per task: 173 / 178 / 178 / 182 / 197 / 199 / 205 / 205** (from
  the 168 baseline). If a count diverges, investigate — do not paper over it.
- Run everything from the repo root with the project venv: `.venv/bin/pytest`,
  `.venv/bin/python`.

## File Structure

```
src/tentpole/model.py                    MODIFY  Task 1 (Config.sprints_per_plan)
src/tentpole/buckets.py                  MODIFY  Task 1 (coarse spans derived)
src/tentpole/checks.py                   MODIFY  Task 1 (drop PLAN_SCALE)
src/tentpole/adapters/config.py          MODIFY  Task 2 (deployment, epic_link_field, optional email)
src/tentpole/adapters/jira_common.py     CREATE  Task 3 (shared helpers + fetch loops), Task 4 (_sprint_id)
src/tentpole/adapters/jira_extract.py    MODIFY  Task 3 (Cloud becomes a thin adapter)
src/tentpole/adapters/jira_extract_dc.py CREATE  Task 5 (Data Center adapter)
src/tentpole/adapters/cli.py             MODIFY  Task 6 (pick adapter by deployment)
src/tentpole/adapters/jira_write.py      MODIFY  Task 7 (version-aware write paths)
README.md                                MODIFY  Task 8
pyproject.toml                           MODIFY  Task 8 (version 0.4.0)

tests/test_buckets.py                    MODIFY  Task 1 (+3, import line)
tests/test_checks_capacity.py            MODIFY  Task 1 (+2, import lines)
tests/test_adapter_config.py             MODIFY  Task 2 (+5)
tests/test_jira_common.py                CREATE  Task 4 (+4)
tests/test_jira_extract_dc.py            CREATE  Task 5 (+15)
tests/conftest.py                        MODIFY  Task 6 (make_http fixture)
tests/test_jira_extract_dc_bundle.py     CREATE  Task 6 (+2)
tests/test_fix_apply.py                  MODIFY  Task 7 (+6)
```

**Decisions locked in (do not revisit mid-implementation):**

- `deployment: cloud | datacenter` is an explicit config key defaulting to
  `cloud`. There is no probing and no separate `auth_scheme` knob: deployment
  implies auth (`cloud` → `Basic base64(email:token)` + `/rest/api/3`;
  `datacenter` → `Bearer <PAT>` + `/rest/api/2`).
- `tentpole fix apply` (`adapters/jira_write.py`) **works on both deployments** in
  0.4.0 (Task 7). Its auth already comes free from the shared header builder; its
  two hardcoded `/rest/api/3/...` paths become version-aware, and `set_parent`
  writes the epic key into `cfg.epic_link_field` on Data Center (the exact mirror
  of the read side) while keeping `fields.parent` on Cloud. The
  set-fixVersion and add-link payloads are byte-identical across deployments —
  only their paths move.
- The load adapter (Smartsheet) is untouched; it already accepts an alternate
  `base_url`.

---

### Task 1: `sprints_per_plan` — one number, two consumers

The six-sprint plan horizon is hardcoded in two places that must move together:
`checks.PLAN_SCALE = {"plan+1": 6.0, "plan+2": 6.0}` (sprints of team capacity
priced into each coarse bucket by `team_subscription`) and `buckets.buckets_for`
(the coarse buckets' *date spans*: `plan+1` ends `anchor + 60 days`, `plan+2`
ends `anchor + 120 days` — 6 × the default 10-day sprint). Scaling only the
capacity would make the checks disagree: at 4 sprints per plan,
`team_subscription` would price a plan bucket at 4 sprints of capacity while the
bucket still spanned an unchanged 60 days of calendar, which is what
`deadline_risk` (via bucket end dates) and `tentpole_runway` (via
`sprint_equivalents_until`) actually read.

Add `sprints_per_plan: int = 6` to the core `Config` and derive both consumers
from it. The default of 6 with the default `sprint_length_days = 10.0`
reproduces today's 60/120-day spans and 6.0 capacity scale exactly, so every
existing fixture stays green — that is the regression guard.

**Files:**
- Modify: `src/tentpole/model.py` (`Config`)
- Modify: `src/tentpole/buckets.py` (`buckets_for`)
- Modify: `src/tentpole/checks.py` (delete `PLAN_SCALE`, `team_subscription`)
- Test: `tests/test_buckets.py` (+3), `tests/test_checks_capacity.py` (+2)

**Interfaces:**
- Produces: `Config.sprints_per_plan: int = 6`, read by `buckets.buckets_for`
  (`plan_days = round(sprints_per_plan * sprint_length_days)`) and by
  `checks.team_subscription` (coarse capacity `= throughput_for(...) *
  sprints_per_plan`). `buckets_for(bundle)` already receives the bundle — no
  signature changes anywhere.
- Consumes: nothing from other tasks. This task is independent of the adapter
  work and lands first.

- [ ] **Step 1: Write the failing bucket tests**

`tests/test_buckets.py` currently imports `from tentpole.model import FixVersion,
Issue`. Change that one import line to add `Config`:

```python
from tentpole.model import Config, FixVersion, Issue
```

Then append these three tests to the end of the file:

```python
def test_default_sprints_per_plan_reproduces_60_120_day_spans(make_bundle):
    """Regression guard: 6 sprints x the default 10-day sprint is exactly
    today's 60/120-day coarse horizon, so existing configs and fixtures
    are unaffected by the new knob."""
    b = make_bundle()
    assert b.config.sprints_per_plan == 6
    bks = buckets_for(b)
    plan1 = next(bk for bk in bks if bk.id == "plan+1")
    plan2 = next(bk for bk in bks if bk.id == "plan+2")
    anchor = date(2026, 9, 10)          # last of the six default sprints
    assert (plan1.end - anchor).days == 60
    assert (plan2.end - anchor).days == 120


def test_sprints_per_plan_scales_coarse_bucket_spans(make_bundle):
    b = make_bundle(config=Config(team=["ada", "grace"], sprints_per_plan=4))
    bks = buckets_for(b)
    plan1 = next(bk for bk in bks if bk.id == "plan+1")
    plan2 = next(bk for bk in bks if bk.id == "plan+2")
    # last sprint ends 2026-09-10; 4 sprints x 10 days = a 40-day bucket
    assert plan1.start == date(2026, 9, 11)
    assert plan1.end == date(2026, 10, 20)
    assert plan2.start == date(2026, 10, 21)
    assert plan2.end == date(2026, 11, 29)


def test_sprint_equivalents_at_plan_boundary_equals_sprints_per_plan(
        make_bundle):
    """tentpole_runway converts coarse-bucket days into sprint equivalents
    with sprint_equivalents_until. Because the spans are now derived from
    sprints_per_plan, the end of plan+1 is exactly (near sprints +
    sprints_per_plan) sprints of runway. With the spans hardcoded at 60
    days, a sprints_per_plan of 4 would still have counted ~6 here."""
    b = make_bundle(config=Config(team=["ada"], sprints_per_plan=4))
    bks = buckets_for(b)
    plan1_end = next(bk for bk in bks if bk.id == "plan+1").end
    got = sprint_equivalents_until(plan1_end, bks,
                                   b.config.sprint_length_days)
    assert got == 10.0          # 6 near sprints + 4 plan sprints
```

- [ ] **Step 2: Write the failing check tests**

`tests/test_checks_capacity.py` needs three import-line edits (these are the
sanctioned edits; do not touch anything else in the file):

1. Add a datetime import as the first line of the file:
   ```python
   from datetime import date
   ```
2. Extend the checks import (post-0.3.0 it reads
   `from tentpole.checks import sprint_overload, team_drift, team_subscription`)
   to:
   ```python
   from tentpole.checks import (deadline_risk, sprint_overload, team_drift,
                                team_subscription)
   ```
3. Extend the model import (`from tentpole.model import Config, Ghost, Issue`)
   to:
   ```python
   from tentpole.model import Config, FixVersion, Ghost, Issue
   ```

Then append these two tests. (The file already defines
`_task(key, person, est, sprint_id=None, **kw)` — `person` and `est` are
POSITIONAL, and `**kw` forwards to `Issue`, so `fix_versions=[...]` works.)

```python
def test_team_subscription_prices_plan_buckets_at_sprints_per_plan(
        make_bundle):
    """Coarse-bucket capacity is throughput x sprints_per_plan. Prior
    throughput is ~7.65d/sprint, so a team of two is ~91.8d of plan+1
    capacity at 6 sprints and ~61.2d at 4 -- a 70d ghost fits the first
    and overruns the second."""
    def _bundle(**kw):
        return make_bundle(
            ghosts=[Ghost(title="G", estimate_days=70.0, target="plan+1")],
            **kw)

    six = _bundle()
    four = _bundle(config=Config(team=["ada", "grace"], sprints_per_plan=4))
    six_bks, four_bks = buckets_for(six), buckets_for(four)
    assert team_subscription(six, six_bks, compile_demand(six, six_bks)) == []
    over = team_subscription(four, four_bks, compile_demand(four, four_bks))
    assert [f.bucket_id for f in over] == ["plan+1"]
    assert "61.2d team capacity" in over[0].message


def test_sprints_per_plan_moves_deadline_risk_and_capacity_together(
        make_bundle):
    """The date spans and the capacity scale are one number. At
    sprints_per_plan=4 the plan+1 window closes 20 days earlier, so a
    deadline that sat exactly on plan+1's last day under the default now
    lands in plan+2 and deadline_risk fires -- while team_subscription
    prices that same bucket at 4 sprints instead of 6. The two checks can
    no longer disagree about how long a plan bucket is."""
    def _bundle(**kw):
        return make_bundle(
            issues=[_task("T-1", "ada", 8.0, fix_versions=["R1"])],
            fix_versions=[FixVersion("R1",
                                     release_date=date(2026, 11, 9))],
            ghosts=[Ghost(title="G", estimate_days=70.0, target="plan+1")],
            **kw)

    six = _bundle()
    four = _bundle(config=Config(team=["ada", "grace"], sprints_per_plan=4))
    six_bks, four_bks = buckets_for(six), buckets_for(four)

    # Default: the deadline is the last day of plan+1 (2026-11-09) and the
    # 78d of demand fits in ~91.8d of capacity. Both checks are quiet.
    assert deadline_risk(six, six_bks) == []
    assert team_subscription(six, six_bks, compile_demand(six, six_bks)) == []

    # sprints_per_plan=4: plan+1 now ends 2026-10-20, so T-1's deadline
    # falls in plan+2 (ends 2026-11-29, past the deadline) and the ghost
    # alone overruns plan+1's 61.2d.
    late = deadline_risk(four, four_bks)
    assert [f.subject for f in late] == ["R1"]
    assert "past the 2026-11-09 deadline" in late[0].message
    over = team_subscription(four, four_bks, compile_demand(four, four_bks))
    assert [f.bucket_id for f in over] == ["plan+1"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_buckets.py tests/test_checks_capacity.py -v`
Expected: the five new tests FAIL — four with
`TypeError: Config.__init__() got an unexpected keyword argument
'sprints_per_plan'` (`test_sprints_per_plan_scales_coarse_bucket_spans`,
`test_sprint_equivalents_at_plan_boundary_equals_sprints_per_plan`,
`test_team_subscription_prices_plan_buckets_at_sprints_per_plan`,
`test_sprints_per_plan_moves_deadline_risk_and_capacity_together`), and
`test_default_sprints_per_plan_reproduces_60_120_day_spans`
with `AttributeError: 'Config' object has no attribute 'sprints_per_plan'`. Every
pre-existing test still passes.

- [ ] **Step 4: Add the config field**

In `src/tentpole/model.py`, in the `Config` dataclass, add `sprints_per_plan`
directly after `sprint_length_days`:

```python
@dataclass
class Config:
    annual_working_days: float = 230.0
    annual_vacation_days: float = 24.0
    annual_overhead_days: float = 30.0
    sprint_length_days: float = 10.0
    sprints_per_plan: int = 6      # coarse-bucket horizon: sets BOTH the
                                   # plan+N date spans (buckets.buckets_for)
                                   # and their capacity scale
                                   # (checks.team_subscription)
    min_sprints_for_empirical: int = 3
    overhead_label: str = "overhead"
    overhead_summary_patterns: tuple[str, ...] = (
        "on-call", "on call", "console", "vacation",
    )
    team: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Derive the coarse bucket spans**

In `src/tentpole/buckets.py`, replace the body of `buckets_for` with:

```python
def buckets_for(bundle: Bundle) -> list[Bucket]:
    active = sorted(
        (s for s in bundle.sprints if s.end >= bundle.as_of),
        key=lambda s: s.start)
    out = [Bucket(f"sprint:{s.id}", s.start, s.end) for s in active]
    anchor = active[-1].end if active else bundle.as_of
    # One derivation: the same sprints_per_plan that prices a plan
    # bucket's capacity in checks.team_subscription also sets how many
    # days it spans, so the two can never disagree about the horizon.
    plan_days = round(bundle.config.sprints_per_plan
                      * bundle.config.sprint_length_days)
    p1_start = anchor + timedelta(days=1)
    p1_end = anchor + timedelta(days=plan_days)
    p2_end = anchor + timedelta(days=2 * plan_days)
    out.append(Bucket("plan+1", p1_start, p1_end))
    out.append(Bucket("plan+2", p1_end + timedelta(days=1), p2_end))
    out.append(Bucket("beyond", p2_end + timedelta(days=1), None))
    out.append(Bucket(UNSCHEDULED, None, None))
    return out
```

- [ ] **Step 6: Derive the coarse bucket capacity**

In `src/tentpole/checks.py`, delete the module-level constant line:

```python
PLAN_SCALE = {"plan+1": 6.0, "plan+2": 6.0}  # sprints per coarse bucket
```

and in `team_subscription`, replace the `else` branch that used it:

```python
        if bucket.id.startswith("sprint:"):
            cap = sum(capacity_for(bundle, p, bucket, demand)
                      for p in bundle.config.team)
        else:
            cap = sum(throughput_for(bundle, p)
                      * bundle.config.sprints_per_plan
                      for p in bundle.config.team)
```

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **173 passed** (168 + 5). Every pre-existing bucket, check,
diagnostics, and CLI fixture stays green because the default of 6 reproduces the
old numbers exactly. If an existing test fails, the derivation is wrong — do not
edit the test.

- [ ] **Step 8: Commit**

```bash
git add src/tentpole/model.py src/tentpole/buckets.py src/tentpole/checks.py tests/test_buckets.py tests/test_checks_capacity.py
git commit -m "feat: configurable sprints_per_plan drives coarse bucket spans and capacity"
```

---

### Task 2: Jira config gains `deployment` and `epic_link_field`

`deployment: cloud | datacenter` is the one switch: it implies the auth scheme
and the REST surface. `cloud` (the default, so every existing config keeps
working) needs `email` — Jira Cloud authenticates with
`Basic base64(email:token)`. `datacenter` needs no email (it authenticates with
`Bearer <PAT>`) but does need `epic_link_field`, because Data Center has no
`parent` for epics and the epic key lives in an instance-specific custom field.
All three failure modes raise `ValueError` at config-load time with a message
that names the fix.

**Files:**
- Modify: `src/tentpole/adapters/config.py` (`JiraConfig`, `load_config`)
- Test: `tests/test_adapter_config.py` (+5, append only)

**Interfaces:**
- Produces: `JiraConfig.deployment: str = "cloud"` (validated against
  `DEPLOYMENTS = ("cloud", "datacenter")`), `JiraConfig.epic_link_field: str |
  None = None`, and `JiraConfig.email: str | None` (still a required *positional*
  dataclass field — pass `email=None` explicitly for datacenter). Tasks 3, 5 and
  6 read all three.

- [ ] **Step 1: Write the failing tests** — append to
      `tests/test_adapter_config.py` (the file already defines
      `_write(tmp_path, text)` and imports `pytest`, `load_config`,
      `JiraConfig`):

```python
DC_YAML = """
jira:
  base_url: https://jira.internal.example.com
  deployment: datacenter
  token_env_var: JIRA_PAT
  epic_link_field: customfield_10014
  scope_jql: project = ABC
  projects: [ABC]
  board_id: 7
"""


def test_deployment_defaults_to_cloud(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  token_env_var: T\n  scope_jql: project = A\n")
    cfg = load_config(_write(tmp_path, text), env={"T": "tok"})
    assert cfg.jira.deployment == "cloud"
    assert cfg.jira.epic_link_field is None


def test_datacenter_config_needs_no_email(tmp_path):
    cfg = load_config(_write(tmp_path, DC_YAML), env={"JIRA_PAT": "pat"})
    assert cfg.jira.deployment == "datacenter"
    assert cfg.jira.email is None
    assert cfg.jira.epic_link_field == "customfield_10014"
    assert cfg.jira.token == "pat"


def test_cloud_without_email_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  token_env_var: T\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="email"):
        load_config(_write(tmp_path, text), env={"T": "tok"})


def test_datacenter_without_epic_link_field_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n"
            "  deployment: datacenter\n  token_env_var: T\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="epic_link_field"):
        load_config(_write(tmp_path, text), env={"T": "tok"})


def test_unknown_deployment_is_actionable(tmp_path):
    text = ("jira:\n  base_url: https://x.net\n  email: a@b.c\n"
            "  deployment: onprem\n  token_env_var: T\n"
            "  scope_jql: project = A\n")
    with pytest.raises(ValueError, match="onprem"):
        load_config(_write(tmp_path, text), env={"T": "tok"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_adapter_config.py -v`
Expected: the five new tests FAIL — `test_deployment_defaults_to_cloud` with
`AttributeError: 'JiraConfig' object has no attribute 'deployment'`, the
datacenter ones with `KeyError: 'email'` (today `load_config` does `j["email"]`),
and `test_unknown_deployment_is_actionable` with `Failed: DID NOT RAISE`.

- [ ] **Step 3: Implement** — in `src/tentpole/adapters/config.py`, add the
      module-level constant just below the `import yaml` line:

```python
DEPLOYMENTS = ("cloud", "datacenter")
```

Replace the whole `JiraConfig` dataclass with:

```python
@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str | None
    token: Secret | str = field(repr=False)
    scope_jql: str
    projects: tuple[str, ...] = ()
    board_id: int | None = None
    sprint_field: str = "customfield_10020"
    hours_per_day: float = 8.0
    programs_file: str | None = None
    deployment: str = "cloud"
    epic_link_field: str | None = None

    def __post_init__(self):
        if not isinstance(self.token, Secret):
            object.__setattr__(self, "token", Secret(self.token))
        if self.deployment not in DEPLOYMENTS:
            raise ValueError(
                f"unknown jira deployment {self.deployment!r}: use "
                f"'cloud' (Jira Cloud: Basic email:token auth, "
                f"/rest/api/3) or 'datacenter' (Jira Data Center or "
                f"Server: Bearer PAT auth, /rest/api/2)")
        if self.deployment == "cloud" and not self.email:
            raise ValueError(
                "jira.email is required when deployment: cloud -- Jira "
                "Cloud authenticates with Basic base64(email:token). If "
                "this is a self-hosted instance, set "
                "deployment: datacenter (Bearer PAT, no email)")
        if self.deployment == "datacenter" and not self.epic_link_field:
            raise ValueError(
                "jira.epic_link_field is required when deployment: "
                "datacenter -- Data Center has no `parent` for epics, so "
                "the epic key lives in an instance-specific custom "
                "field. Find its id with GET /rest/api/2/field on your "
                "instance (look for 'Epic Link'), e.g. "
                "epic_link_field: customfield_10014")
```

And in `load_config`, replace the `JiraConfig(...)` construction with:

```python
        jira = JiraConfig(
            base_url=j["base_url"].rstrip("/"),
            email=j.get("email"),
            token=_token(j, env),
            scope_jql=j["scope_jql"],
            projects=tuple(j.get("projects", [])),
            board_id=j.get("board_id"),
            sprint_field=j.get("sprint_field", "customfield_10020"),
            hours_per_day=float(j.get("hours_per_day", 8.0)),
            programs_file=j.get("programs_file"),
            deployment=j.get("deployment", "cloud"),
            epic_link_field=j.get("epic_link_field"),
        )
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **178 passed** (173 + 5).

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/adapters/config.py tests/test_adapter_config.py
git commit -m "feat: jira deployment and epic_link_field config keys"
```

---

### Task 3: Extract `jira_common` — shared helpers *and* fetch loops

Only *fetching* differs between deployments: auth header, search pagination,
endpoint version, and where the epic key lives. Everything else is identical, so
it moves into `adapters/jira_common.py` and both adapters call it — a bug fixed
once is fixed for both. Critically, the *fetch loops* move too (not just the pure
helpers): `fetch_issues` and `fetch_hygiene` both consume the search-pagination
primitive, so each adapter passes in its own `search_pages` and hygiene JQL
evaluation works on Data Center without a second fork.

This task is a pure refactor: **no wire-level behavior changes and no new
tests.** The 178 existing tests are the safety net. `jira_extract.py` keeps
every public name it has today (`parse_issue`, `fetch_issues`,
`fetch_status_categories`, `fetch_sprints`, `fetch_versions`, `fetch_hygiene`,
`write_bundle`) plus `_headers`, which `adapters/jira_write.py` and
`tests/test_adapter_config.py` import from it. One knowing exception:
`jira_extract.BASE_FIELDS` becomes a re-export of `jira_common.BASE_FIELDS`,
which no longer contains `"parent"` — the new `_fields(cfg)` helper appends
`"parent"` (Cloud) or the epic-link field (DC) instead, so the fields actually
requested over the wire are unchanged. No test pins `BASE_FIELDS`' contents
(verified by grep), so nothing breaks; this note exists so the change is
deliberate, not accidental.

**Files:**
- Create: `src/tentpole/adapters/jira_common.py`
- Modify: `src/tentpole/adapters/jira_extract.py` (becomes a thin Cloud adapter)

**Interfaces:**
- Produces (all consumed by Tasks 4, 5 and 6):
  - `BASE_FIELDS: list[str]` — the deployment-independent field list (no
    `parent`, no sprint field; each adapter appends its own).
  - `headers(cfg) -> dict` — `Bearer <token>` for datacenter, `Basic
    base64(email:token)` for cloud.
  - `api_version(cfg) -> str` — `"2"` for datacenter, `"3"` for cloud.
  - `call(cfg, method, path, *, params=None, body=None, http=request)`.
  - `parse_issue(raw, cfg, categories, programs, *, epic_key, external=False) ->
    dict` — `epic_key` is keyword-only and resolved by the caller.
  - `fetch_issues(cfg, categories, programs, *, search_pages, fields,
    epic_key_of, http=request) -> list[dict]`, where `search_pages(cfg, jql,
    fields, *, expand=None, http=request)` is a generator of raw issues and
    `epic_key_of(fields: dict) -> str | None`.
  - `fetch_hygiene(cfg, rules, *, search_pages, http=request) -> dict[str,
    list[str]]`.
  - `fetch_status_categories(cfg, http=request)`, `fetch_sprints(cfg,
    http=request)`, `fetch_versions(cfg, http=request)`, `write_bundle(...)` —
    fully shared; each adapter re-exports them.
  - `_status_category`, `_days`, `_sprint_id`, `_cycle_dates`, `_stub_external`.

- [ ] **Step 1: Create the shared module**

Create `src/tentpole/adapters/jira_common.py` with exactly this content:

```python
"""Deployment-independent Jira extract logic, shared by the Cloud
adapter (jira_extract) and the Data Center / Server adapter
(jira_extract_dc).

Only *fetching* differs between deployments: the auth header, the search
pagination primitive, the REST API version, and where an issue's epic key
lives. Everything else -- parsing an issue into the bundle contract, the
changelog cycle dates, the external-issue stubbing, and the fetch loops
themselves -- is identical and lives here, so both adapters emit the same
bundle and a bug fixed once is fixed for both.

The pagination seam is part of that boundary: fetch_issues AND
fetch_hygiene both drive search, so each adapter passes in its own
`search_pages` generator rather than forking the loops."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import quote

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError, request

# Deployment-independent fields. Each adapter appends its sprint field and
# its epic-key field (Cloud: "parent"; Data Center: cfg.epic_link_field).
BASE_FIELDS = ["summary", "issuetype", "status", "assignee",
               "timetracking", "fixVersions", "labels", "issuelinks"]

_CATEGORY = {"new": "todo", "indeterminate": "in_progress",
             "done": "done", "undefined": "todo"}


def _status_category(key: str) -> str:
    try:
        return _CATEGORY[key]
    except KeyError:
        # Fail loudly but actionably: a genuinely unknown statusCategory
        # key must still stop the extract (silently guessing would hide a
        # broken sync), but name the offending key rather than let a bare
        # KeyError surface.
        raise KeyError(
            f"unknown Jira statusCategory key {key!r}; known keys are "
            f"{sorted(_CATEGORY)} -- update tentpole's _CATEGORY map"
        ) from None


def headers(cfg: JiraConfig) -> dict:
    # Deployment implies auth: Data Center / Server takes a Bearer
    # personal access token (no email); Cloud takes Basic email:token.
    # .reveal() is called here and nowhere else.
    if cfg.deployment == "datacenter":
        return {"Authorization": f"Bearer {cfg.token.reveal()}"}
    cred = base64.b64encode(
        f"{cfg.email}:{cfg.token.reveal()}".encode()).decode()
    return {"Authorization": f"Basic {cred}"}


def api_version(cfg: JiraConfig) -> str:
    return "2" if cfg.deployment == "datacenter" else "3"


def call(cfg, method, path, *, params=None, body=None, http=request):
    return http(method, cfg.base_url + path, headers(cfg),
                params=params, body=body)


def fetch_status_categories(cfg, http=request) -> dict[str, str]:
    statuses = call(cfg, "GET", f"/rest/api/{api_version(cfg)}/status",
                    http=http)
    return {s["name"]: _status_category(s["statusCategory"]["key"])
            for s in statuses}


def _days(seconds, hours_per_day):
    if seconds is None:
        return None
    return round(seconds / 3600.0 / hours_per_day, 2)


def _sprint_id(value):
    # The sprint custom field is a list of sprint objects; the last is
    # the issue's current placement.
    if not value:
        return None
    last = value[-1]
    return last.get("id") if isinstance(last, dict) else None


def _cycle_dates(changelog, categories):
    first_in_progress, done_at = None, None
    histories = sorted((changelog or {}).get("histories", []),
                       key=lambda h: h.get("created", ""))
    for h in histories:
        when = h.get("created", "")[:10]
        for item in h.get("items", []):
            if item.get("field") != "status":
                continue
            cat = categories.get(item.get("toString"))
            if cat == "in_progress" and first_in_progress is None:
                first_in_progress = when
            if cat == "done":
                done_at = when
            elif cat is not None:
                done_at = None   # moved back out of done: date is stale
    return first_in_progress, done_at


def parse_issue(raw: dict, cfg: JiraConfig, categories: dict[str, str],
                programs: dict[str, str], *, epic_key: str | None,
                external: bool = False) -> dict:
    """The bundle contract. `epic_key` is resolved by the caller because
    it is the one field whose location is deployment-specific."""
    f = raw["fields"]
    status_category = _status_category(f["status"]["statusCategory"]["key"])
    tt = f.get("timetracking") or {}
    links = []
    for link in f.get("issuelinks", []):
        if "outwardIssue" in link:
            links.append({"type": link["type"]["name"],
                          "direction": "outward",
                          "other_key": link["outwardIssue"]["key"]})
        elif "inwardIssue" in link:
            links.append({"type": link["type"]["name"],
                          "direction": "inward",
                          "other_key": link["inwardIssue"]["key"]})
    first_in_progress, done_at = _cycle_dates(raw.get("changelog"),
                                              categories)
    if status_category != "done":
        done_at = None   # reopened issues must not keep a done date
    assignee = f.get("assignee") or {}
    return {
        "key": raw["key"],
        "summary": f.get("summary") or "",
        "issue_type": f["issuetype"]["name"],
        "status_category": status_category,
        "assignee": assignee.get("displayName"),
        "original_estimate_days": _days(
            tt.get("originalEstimateSeconds"), cfg.hours_per_day),
        "remaining_estimate_days": _days(
            tt.get("remainingEstimateSeconds"), cfg.hours_per_day),
        "epic_key": epic_key,
        "fix_versions": [v["name"] for v in f.get("fixVersions", [])],
        "sprint_id": _sprint_id(f.get(cfg.sprint_field)),
        "labels": f.get("labels", []),
        "links": links,
        "program": programs.get(raw["key"]) or programs.get(epic_key),
        "first_in_progress": first_in_progress,
        "done_at": done_at,
        "external": external,
    }


def _stub_external(key: str) -> dict:
    return {"key": key, "summary": "", "issue_type": "Unknown",
            "status_category": "todo", "assignee": None,
            "original_estimate_days": None,
            "remaining_estimate_days": None, "epic_key": None,
            "fix_versions": [], "sprint_id": None, "labels": [],
            "links": [], "program": None, "first_in_progress": None,
            "done_at": None, "external": True}


def fetch_issues(cfg, categories, programs, *, search_pages, fields,
                 epic_key_of, http=request) -> list[dict]:
    issues = [parse_issue(r, cfg, categories, programs,
                          epic_key=epic_key_of(r["fields"]))
              for r in search_pages(cfg, cfg.scope_jql, fields,
                                    expand="changelog", http=http)]
    known = {i["key"] for i in issues}
    linked = sorted({link["other_key"] for i in issues
                     for link in i["links"]} - known)
    if not linked:
        return issues
    jql = "key in (" + ",".join(linked) + ")"
    try:
        external = [parse_issue(r, cfg, categories, programs,
                                epic_key=epic_key_of(r["fields"]),
                                external=True)
                    for r in search_pages(cfg, jql, fields, http=http)]
    except HttpError as err:
        if err.status not in (403, 404):
            # Anything other than "not visible" (403) or "not found"
            # (404) is a real infrastructure failure -- an expired
            # token (401), an exhausted-retries 5xx, etc. Silently
            # stubbing those would hide a broken sync, so let it
            # propagate and fail the extract loudly.
            raise
        # No read access to (some of) the linked projects, or they no
        # longer exist: keep the dependency edges visible with
        # status-unknown stubs rather than failing the whole extract.
        external = [_stub_external(k) for k in linked]
    return issues + external


def fetch_sprints(cfg, http=request) -> list[dict]:
    # Agile REST 1.0 is identical on Cloud and Data Center / Server.
    if cfg.board_id is None:
        return []
    out, start = [], 0
    while True:
        page = call(cfg, "GET",
                    f"/rest/agile/1.0/board/{cfg.board_id}/sprint",
                    params={"startAt": start,
                            "state": "active,future"},
                    http=http)
        values = page.get("values", [])
        for s in values:
            if s.get("startDate") and s.get("endDate"):
                out.append({"id": s["id"], "name": s["name"],
                            "start": s["startDate"][:10],
                            "end": s["endDate"][:10]})
        if page.get("isLast", True):
            return out
        start += len(values)


def fetch_versions(cfg, http=request) -> list[dict]:
    out = []
    for project in cfg.projects:
        for v in call(cfg, "GET",
                      f"/rest/api/{api_version(cfg)}/project/"
                      f"{quote(project, safe='')}/versions",
                      http=http):
            out.append({"name": v["name"],
                        "release_date": v.get("releaseDate"),
                        "released": v.get("released", False)})
    return out


def fetch_hygiene(cfg, rules, *, search_pages,
                  http=request) -> dict[str, list[str]]:
    # Jira itself evaluates each rule's JQL at extract time, scoped to
    # the in-scope set; the core only joins membership. This rides the
    # adapter's own search pagination, which is why search_pages is a
    # parameter rather than a Cloud-only import.
    out = {}
    for rule in rules:
        if rule.jql is None:
            continue
        jql = f"({cfg.scope_jql}) AND ({rule.jql})"
        out[rule.name] = [r["key"]
                          for r in search_pages(cfg, jql, ["id"], http=http)]
    return out


def write_bundle(out_dir: Path, *, as_of: str, issues, sprints,
                 versions, hygiene, config=None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "meta.json").write_text(json.dumps({"as_of": as_of}))
    (out_dir / "issues.json").write_text(json.dumps(issues, indent=2))
    (out_dir / "sprints.json").write_text(json.dumps(sprints, indent=2))
    (out_dir / "fix_versions.json").write_text(
        json.dumps(versions, indent=2))
    (out_dir / "hygiene.json").write_text(json.dumps(hygiene, indent=2))
    if config is not None:
        (out_dir / "config.json").write_text(json.dumps(config, indent=2))
```

- [ ] **Step 2: Rewrite the Cloud adapter on top of it**

Replace the *entire* contents of `src/tentpole/adapters/jira_extract.py` with:

```python
"""Jira Cloud extract adapter (spec sections 3 and 8; open question 2).
Fetch and dump -- no analysis lives here. Cloud-specific surface: POST
/rest/api/3/search/jql with a nextPageToken cursor, Basic email:token
auth, and the epic relationship via `parent` (Epic Link is retired on
Cloud). Everything else -- parsing, the fetch loops, the bundle writer --
is shared with the Data Center adapter via jira_common."""
from __future__ import annotations

from tentpole.adapters import jira_common
from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import request
from tentpole.adapters.jira_common import (      # noqa: F401  (re-exported)
    BASE_FIELDS, call, fetch_sprints, fetch_status_categories,
    fetch_versions, headers, write_bundle,
)

# Re-exported under its historical name: adapters/jira_write.py and the
# test suite import `_headers` from this module.
_headers = headers


def _fields(cfg: JiraConfig) -> list[str]:
    return BASE_FIELDS + ["parent", cfg.sprint_field]


def _epic_key(fields: dict) -> str | None:
    # Cloud: the epic IS the parent (Epic Link is retired).
    parent = fields.get("parent")
    return parent["key"] if parent else None


def search_pages(cfg, jql, fields, *, expand=None, http=request):
    """Cloud search pagination: an opaque nextPageToken cursor."""
    token = None
    while True:
        body = {"jql": jql, "maxResults": 100, "fields": fields}
        if expand:
            body["expand"] = expand
        if token:
            body["nextPageToken"] = token
        page = call(cfg, "POST", "/rest/api/3/search/jql", body=body,
                    http=http)
        yield from page.get("issues", [])
        token = page.get("nextPageToken")
        if not token:
            return


def parse_issue(raw: dict, cfg: JiraConfig, categories: dict[str, str],
                programs: dict[str, str],
                external: bool = False) -> dict:
    return jira_common.parse_issue(
        raw, cfg, categories, programs,
        epic_key=_epic_key(raw["fields"]), external=external)


def fetch_issues(cfg, categories, programs, http=request) -> list[dict]:
    return jira_common.fetch_issues(
        cfg, categories, programs, search_pages=search_pages,
        fields=_fields(cfg), epic_key_of=_epic_key, http=http)


def fetch_hygiene(cfg, rules, http=request) -> dict[str, list[str]]:
    return jira_common.fetch_hygiene(cfg, rules,
                                     search_pages=search_pages, http=http)
```

- [ ] **Step 3: Run the full suite — the refactor must be invisible**

Run: `.venv/bin/pytest -q`
Expected: **178 passed** (unchanged — this task adds no tests). Every Cloud
adapter test, the `_headers` test in `tests/test_adapter_config.py`, the
`jira_write` tests, and the end-to-end `tentpole extract` test still pass
against the rewritten module. If any fail, the refactor changed behavior — fix
the code, not the test.

- [ ] **Step 4: Commit**

```bash
git add src/tentpole/adapters/jira_common.py src/tentpole/adapters/jira_extract.py
git commit -m "refactor: extract jira_common shared parse helpers and fetch loops"
```

---

### Task 4: `_sprint_id` must never silently drop a sprint

Modern Jira serializes the sprint custom field as a list of objects. Older
Server / Data Center instances serialize each entry as a string of the form
`com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c[id=123,rapidViewId=7,state=ACTIVE,name=S5]`.
Today's `_sprint_id` returns `None` for any non-dict entry, so on such an
instance *every issue silently loses its sprint* — the sync looks healthy while
all sprint placement evaporates. That is exactly the failure mode the project
forbids. Handle the dict form, parse the legacy string form, and raise an
actionable `ValueError` for anything else. An empty or absent field still yields
`None` — that genuinely means "not in a sprint".

**Files:**
- Modify: `src/tentpole/adapters/jira_common.py` (`_sprint_id`)
- Test: `tests/test_jira_common.py` (create, +4)

**Interfaces:**
- Produces: `_sprint_id(value) -> int | None`, raising `ValueError` on an
  unrecognized non-empty entry. Task 5 and Task 6 rely on the legacy-string
  parse.

- [ ] **Step 1: Write the failing tests** — create `tests/test_jira_common.py`:

```python
import pytest

from tentpole.adapters.jira_common import _sprint_id

LEGACY = ("com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c["
          "rapidViewId=7,state=ACTIVE,name=S5,startDate=2026-07-13,"
          "id=123,goal=]")


def test_sprint_id_from_dict_entries():
    # The last entry is the issue's current placement.
    assert _sprint_id([{"id": 4, "name": "S4"},
                       {"id": 5, "name": "S5"}]) == 5


def test_sprint_id_parses_legacy_sprint_string():
    """Older Server/DC serializes the sprint field as a toString() dump.
    The id must be recovered from it -- not silently dropped."""
    assert _sprint_id([LEGACY]) == 123


def test_sprint_id_empty_or_absent_is_none():
    assert _sprint_id(None) is None
    assert _sprint_id([]) is None


def test_sprint_id_unrecognized_shape_raises_actionable_error():
    """Returning None here would silently strip the sprint from every
    issue on the instance and make a broken sync look healthy."""
    with pytest.raises(ValueError,
                       match="unrecognized sprint custom-field value"):
        _sprint_id([12345])
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_jira_common.py -v`
Expected: `test_sprint_id_parses_legacy_sprint_string` FAILS
(`assert None == 123`) and
`test_sprint_id_unrecognized_shape_raises_actionable_error` FAILS
(`Failed: DID NOT RAISE`). The dict and empty tests already pass.

- [ ] **Step 3: Implement** — in `src/tentpole/adapters/jira_common.py`, add
      `import re` to the imports (after `import json`), add the module-level
      pattern next to `_CATEGORY`:

```python
# Legacy Server/DC serialization:
# com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c[id=123,...]
# Field order varies across versions, so search for the id key itself.
# Case-sensitive on purpose: it must not match `rapidViewId=7`.
_LEGACY_SPRINT_ID = re.compile(r"\bid=(\d+)")
```

and replace `_sprint_id` with:

```python
def _sprint_id(value):
    """The sprint custom field is a list; the last entry is the issue's
    current placement. Modern Jira serializes each entry as an object;
    older Server/DC serializes it as a
    `...Sprint@1a2b3c[id=123,...]` toString() dump. Anything else
    raises: returning None for an unrecognized non-empty value would
    silently drop the sprint from every issue on the instance and make a
    broken sync look healthy."""
    if not value:
        return None
    last = value[-1]
    if isinstance(last, dict):
        return last.get("id")
    if isinstance(last, str):
        match = _LEGACY_SPRINT_ID.search(last)
        if match:
            return int(match.group(1))
    raise ValueError(
        f"unrecognized sprint custom-field value {last!r}: expected a "
        f"sprint object with an 'id', or the legacy "
        f"'...Sprint@...[id=123,...]' string form -- check that "
        f"sprint_field names this instance's sprint custom field "
        f"(GET /rest/api/2/field)")
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **182 passed** (178 + 4). The Cloud adapter's dict-form sprint tests
still pass — the dict branch is unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/adapters/jira_common.py tests/test_jira_common.py
git commit -m "fix: parse legacy sprint strings and fail loudly on unknown shapes"
```

---

### Task 5: The Data Center adapter

The whole adapter is: Bearer auth (already in `jira_common.headers`), offset
search pagination, `/rest/api/2` for status and versions (already in
`jira_common.api_version`), and an epic key read from `cfg.epic_link_field`
instead of `fields.parent`. Everything else is a re-export.

Offset pagination has one trap worth naming: the loop must stop when
`startAt + len(issues) >= total`, which means a *full* final page (total is an
exact multiple of the page size) must not trigger one more request. It must also
stop on an empty page, so a server reporting a stale `total` cannot spin the
loop forever.

**Files:**
- Create: `src/tentpole/adapters/jira_extract_dc.py`
- Test: `tests/test_jira_extract_dc.py` (create, +15)

**Interfaces:**
- Consumes: `jira_common`'s `BASE_FIELDS`, `call`, `headers`,
  `fetch_status_categories`, `fetch_sprints`, `fetch_versions`, `write_bundle`,
  `parse_issue`, `fetch_issues`, `fetch_hygiene` (Task 3); `JiraConfig.deployment`
  and `JiraConfig.epic_link_field` (Task 2).
- Produces: the module `tentpole.adapters.jira_extract_dc` exposing the same six
  names `adapters/cli.py` calls on the Cloud adapter —
  `fetch_status_categories(cfg, http=request)`,
  `fetch_issues(cfg, categories, programs, http=request)`,
  `fetch_sprints(cfg, http=request)`, `fetch_versions(cfg, http=request)`,
  `fetch_hygiene(cfg, rules, http=request)`,
  `write_bundle(out_dir, *, as_of, issues, sprints, versions, hygiene,
  config=None)` — plus
  `parse_issue(raw, cfg, categories, programs, external=False)` and
  `search_pages(cfg, jql, fields, *, expand=None, http=request)`. Task 6 imports
  the module.

- [ ] **Step 1: Write the failing tests** — create
      `tests/test_jira_extract_dc.py`:

```python
import base64

import pytest

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError
from tentpole.adapters.jira_common import headers
from tentpole.adapters.jira_extract_dc import (fetch_hygiene, fetch_issues,
                                               fetch_sprints,
                                               fetch_status_categories,
                                               fetch_versions, parse_issue)
from tentpole.hygiene import Rule

DC = JiraConfig(base_url="https://jira.internal", email=None, token="pat",
                scope_jql="project = ABC", projects=("ABC",), board_id=7,
                deployment="datacenter",
                epic_link_field="customfield_10014")
CLOUD = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                   scope_jql="project = ABC")
CATS = {"To Do": "todo", "In Progress": "in_progress", "Done": "done"}


def _raw(key, status="To Do", **fields):
    base = {"summary": "s", "issuetype": {"name": "Task"},
            "status": {"statusCategory": {"key": {
                "To Do": "new", "In Progress": "indeterminate",
                "Done": "done"}[status]}}}
    base.update(fields)
    return {"key": key, "fields": base}


def _page(issues, start, total):
    return {"issues": issues, "startAt": start, "maxResults": 2,
            "total": total}


def test_headers_datacenter_uses_bearer_pat_without_email():
    assert headers(DC) == {"Authorization": "Bearer pat"}


def test_headers_cloud_uses_basic_email_and_token():
    cred = base64.b64encode(b"a@b.c:t").decode()
    assert headers(CLOUD) == {"Authorization": f"Basic {cred}"}


def test_fetch_status_categories_uses_api_2(fake_http):
    fake_http.add("GET", "/rest/api/2/status", [
        {"name": "To Do", "statusCategory": {"key": "new"}},
        {"name": "Done", "statusCategory": {"key": "done"}},
    ])
    assert fetch_status_categories(DC, http=fake_http) == {
        "To Do": "todo", "Done": "done"}


def test_offset_pagination_pages_until_total(fake_http):
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-1"), _raw("A-2")], 0, 3))
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-3")], 2, 3))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1", "A-2", "A-3"]
    assert fake_http.calls[0]["body"]["startAt"] == 0
    assert fake_http.calls[1]["body"]["startAt"] == 2
    assert len(fake_http.calls) == 2


def test_offset_pagination_stops_on_exact_full_final_page(fake_http):
    """The boundary: total is an exact multiple of the page size, so the
    final page is full. startAt + len == total must terminate -- asking
    for a startAt == total page would be a wasted request, and on a
    server whose total lags it would loop."""
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-1"), _raw("A-2")], 0, 4))
    fake_http.add("POST", "/rest/api/2/search",
                  _page([_raw("A-3"), _raw("A-4")], 2, 4))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1", "A-2", "A-3", "A-4"]
    assert len(fake_http.calls) == 2


def test_offset_pagination_terminates_on_empty_page(fake_http):
    """A stale/oversized `total` must not spin the loop: an empty page
    ends it."""
    fake_http.add("POST", "/rest/api/2/search", _page([_raw("A-1")], 0, 9))
    fake_http.add("POST", "/rest/api/2/search", _page([], 1, 9))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    assert [i["key"] for i in issues] == ["A-1"]
    assert len(fake_http.calls) == 2


def test_fetch_issues_requests_epic_and_sprint_fields(fake_http):
    fake_http.add("POST", "/rest/api/2/search", _page([], 0, 0))
    fetch_issues(DC, CATS, {}, http=fake_http)
    body = fake_http.calls[0]["body"]
    assert "customfield_10014" in body["fields"]     # epic_link_field
    assert "customfield_10020" in body["fields"]     # sprint_field
    assert "parent" not in body["fields"]            # no parent on DC
    assert body["expand"] == ["changelog"]
    assert body["jql"] == "project = ABC"


def test_epic_key_read_from_configured_field():
    out = parse_issue(_raw("A-1", customfield_10014="E-7"), DC, CATS,
                      {"E-7": "prog-a"})
    assert out["epic_key"] == "E-7"
    assert out["program"] == "prog-a"     # inherited via the epic key


def test_epic_key_missing_field_is_none():
    assert parse_issue(_raw("A-1"), DC, CATS, {})["epic_key"] is None


def test_epic_key_unrecognized_shape_raises():
    with pytest.raises(ValueError, match="epic_link_field"):
        parse_issue(_raw("A-1", customfield_10014=[{"key": "E-7"}]),
                    DC, CATS, {})


def test_fetch_versions_uses_api_2(fake_http):
    fake_http.add("GET", "/rest/api/2/project/ABC/versions", [
        {"name": "R1", "releaseDate": "2026-09-01", "released": False},
    ])
    assert fetch_versions(DC, http=fake_http) == [
        {"name": "R1", "release_date": "2026-09-01", "released": False}]


def test_fetch_sprints_uses_agile_1_0(fake_http):
    fake_http.add("GET", "/rest/agile/1.0/board/7/sprint", {
        "values": [{"id": 1, "name": "S1",
                    "startDate": "2026-07-13T00:00:00.000Z",
                    "endDate": "2026-07-24T00:00:00.000Z"}],
        "isLast": True})
    assert fetch_sprints(DC, http=fake_http) == [
        {"id": 1, "name": "S1", "start": "2026-07-13",
         "end": "2026-07-24"}]


def test_fetch_hygiene_scopes_rule_jql_over_dc_search(fake_http):
    rules = [Rule(name="unanchored", severity="red", message="m",
                  jql="fixVersion is EMPTY")]
    fake_http.add("POST", "/rest/api/2/search",
                  _page([{"key": "A-1"}], 0, 1))
    assert fetch_hygiene(DC, rules, http=fake_http) == {
        "unanchored": ["A-1"]}
    assert fake_http.calls[0]["body"]["jql"] == (
        "(project = ABC) AND (fixVersion is EMPTY)")


def test_external_linked_issues_stubbed_on_403(fake_http):
    linked = _raw("A-7", issuelinks=[
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "Z-1"}}])
    fake_http.add("POST", "/rest/api/2/search", _page([linked], 0, 1))
    fake_http.add("POST", "/rest/api/2/search",
                  HttpError(403, "https://jira.internal", "forbidden"))
    issues = fetch_issues(DC, CATS, {}, http=fake_http)
    ext = [i for i in issues if i["external"]]
    assert [i["key"] for i in ext] == ["Z-1"]
    assert ext[0]["status_category"] == "todo"
    assert fake_http.calls[1]["body"]["jql"] == "key in (Z-1)"


def test_external_linked_issues_propagate_on_500(fake_http):
    """Only 403/404 may become a status-unknown stub. A 500 that already
    exhausted its retries is a real infrastructure failure -- silently
    stubbing it would make a broken sync look benign."""
    linked = _raw("A-9", issuelinks=[
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "Z-2"}}])
    fake_http.add("POST", "/rest/api/2/search", _page([linked], 0, 1))
    fake_http.add("POST", "/rest/api/2/search",
                  HttpError(500, "https://jira.internal", "boom"))
    with pytest.raises(HttpError):
        fetch_issues(DC, CATS, {}, http=fake_http)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_jira_extract_dc.py -v`
Expected: collection FAILS with
`ModuleNotFoundError: No module named 'tentpole.adapters.jira_extract_dc'` (the
two `headers` tests would pass, but the import error takes the whole file down —
that is the expected red).

- [ ] **Step 3: Implement** — create
      `src/tentpole/adapters/jira_extract_dc.py`:

```python
"""Jira Data Center / Server extract adapter.

Emits the identical bundle the Cloud adapter emits -- the core cannot
tell which adapter produced it. Only the fetch surface differs:

  auth        Bearer <PAT> (no email)         [jira_common.headers]
  search      POST /rest/api/2/search, offset paging via
              startAt / maxResults / total (there is no nextPageToken
              cursor here)
  epic key    an instance-specific custom field (cfg.epic_link_field);
              Data Center has no `parent` for epics
  status      GET /rest/api/2/status          [jira_common]
  versions    GET /rest/api/2/project/{k}/versions   [jira_common]
  sprints     GET /rest/agile/1.0/board/{id}/sprint  [same as Cloud]

Everything else is jira_common."""
from __future__ import annotations

from tentpole.adapters import jira_common
from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import request
from tentpole.adapters.jira_common import (     # noqa: F401  (re-exported)
    BASE_FIELDS, call, fetch_sprints, fetch_status_categories,
    fetch_versions, headers, write_bundle,
)


def _fields(cfg: JiraConfig) -> list[str]:
    return BASE_FIELDS + [cfg.epic_link_field, cfg.sprint_field]


def _epic_key_of(cfg: JiraConfig):
    """Data Center reads the epic key from a configured custom field.
    The id is instance-specific, so it is required config and never
    hardcoded."""
    def _epic_key(fields: dict) -> str | None:
        value = fields.get(cfg.epic_link_field)
        if not value:
            return None                  # genuinely not in an epic
        if isinstance(value, str):
            return value                 # the usual Epic Link shape
        if isinstance(value, dict) and "key" in value:
            return value["key"]
        raise ValueError(
            f"epic_link_field {cfg.epic_link_field!r} holds {value!r}, "
            f"which is neither an issue-key string nor an object with a "
            f"'key' -- check that epic_link_field names this instance's "
            f"Epic Link field (GET /rest/api/2/field)")
    return _epic_key


def search_pages(cfg, jql, fields, *, expand=None, http=request):
    """Data Center search pagination: startAt / maxResults / total
    offsets. Stop once we have seen `total` issues -- including when the
    final page is exactly full -- and stop on an empty page so a stale
    `total` cannot spin this loop forever."""
    start = 0
    while True:
        body = {"jql": jql, "startAt": start, "maxResults": 100,
                "fields": fields}
        if expand:
            body["expand"] = [expand]      # v2 search takes a list
        page = call(cfg, "POST", "/rest/api/2/search", body=body, http=http)
        issues = page.get("issues", [])
        yield from issues
        start += len(issues)
        if not issues or start >= page.get("total", 0):
            return


def parse_issue(raw: dict, cfg: JiraConfig, categories: dict[str, str],
                programs: dict[str, str],
                external: bool = False) -> dict:
    return jira_common.parse_issue(
        raw, cfg, categories, programs,
        epic_key=_epic_key_of(cfg)(raw["fields"]), external=external)


def fetch_issues(cfg, categories, programs, http=request) -> list[dict]:
    return jira_common.fetch_issues(
        cfg, categories, programs, search_pages=search_pages,
        fields=_fields(cfg), epic_key_of=_epic_key_of(cfg), http=http)


def fetch_hygiene(cfg, rules, http=request) -> dict[str, list[str]]:
    return jira_common.fetch_hygiene(cfg, rules,
                                     search_pages=search_pages, http=http)
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **197 passed** (182 + 15).

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/adapters/jira_extract_dc.py tests/test_jira_extract_dc.py
git commit -m "feat: Jira Data Center extract adapter with offset pagination"
```

---

### Task 6: Wire `tentpole extract` to the deployment, and prove the bundles match

`_extract` picks the adapter from `cfg.jira.deployment` and calls the same six
functions on it. Then the load-bearing test: run *both* adapters over equivalent
recorded fixtures (a search page, a changelog expand, an agile sprint page,
project versions, a status list, a 403 on the linked-issue backfill) and assert
the two bundles are byte-for-byte identical. If the Data Center adapter ever
drifts from the bundle contract, this is the test that catches it.

**Files:**
- Modify: `src/tentpole/adapters/cli.py` (`_extract`)
- Modify: `tests/conftest.py` (one new fixture)
- Test: `tests/test_jira_extract_dc_bundle.py` (create, +2)

**Interfaces:**
- Consumes: `tentpole.adapters.jira_extract_dc` (Task 5) and
  `JiraConfig.deployment` (Task 2).
- Produces: `_adapter(jira_cfg)` in `adapters/cli.py`, returning the module to
  extract with; a `make_http` fixture in `tests/conftest.py` returning the
  `FakeHttp` *class*, for tests that need two independent fake transports (the
  existing `fake_http` fixture hands back a single instance).

- [ ] **Step 1: Add the `make_http` fixture** — append to `tests/conftest.py`
      (the `FakeHttp` class and the `fake_http` fixture already live there;
      leave both alone):

```python
@pytest.fixture
def make_http():
    """The FakeHttp class itself, for tests driving two adapters (and so
    two independent response queues) in one test."""
    return FakeHttp
```

- [ ] **Step 2: Write the failing tests** — create
      `tests/test_jira_extract_dc_bundle.py`:

```python
import json
import urllib.request

from tentpole.adapters import jira_extract, jira_extract_dc
from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import HttpError
from tentpole.cli import main
from tentpole.hygiene import Rule
from tentpole.model import load_bundle

CLOUD = JiraConfig(base_url="https://x.net", email="a@b.c", token="t",
                   scope_jql="project = ABC", projects=("ABC",),
                   board_id=7)
DC = JiraConfig(base_url="https://jira.internal", email=None, token="pat",
                scope_jql="project = ABC", projects=("ABC",), board_id=7,
                deployment="datacenter",
                epic_link_field="customfield_10014")

STATUSES = [{"name": "To Do", "statusCategory": {"key": "new"}},
            {"name": "In Progress",
             "statusCategory": {"key": "indeterminate"}},
            {"name": "Done", "statusCategory": {"key": "done"}}]
SPRINT_PAGE = {"values": [{"id": 4, "name": "S4",
                           "startDate": "2026-07-13T00:00:00.000Z",
                           "endDate": "2026-07-24T00:00:00.000Z"}],
               "isLast": True}
VERSIONS = [{"name": "R1", "releaseDate": "2026-09-01",
             "released": False}]
CHANGELOG = {"histories": [
    {"created": "2026-07-02T10:00:00.000+0000",
     "items": [{"field": "status", "toString": "In Progress"}]}]}
RULES = [Rule(name="unanchored", severity="red", message="m",
              jql="fixVersion is EMPTY")]
LEGACY_SPRINT = ("com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c["
                 "rapidViewId=7,state=ACTIVE,name=S4,id=4]")


def _shared_fields():
    return {
        "summary": "Do the thing",
        "issuetype": {"name": "Task"},
        "status": {"statusCategory": {"key": "indeterminate"}},
        "assignee": {"displayName": "ada"},
        "timetracking": {"originalEstimateSeconds": 8 * 3600 * 2,
                         "remainingEstimateSeconds": 8 * 3600},
        "fixVersions": [{"name": "R1"}],
        "labels": ["backend"],
        "issuelinks": [{"type": {"name": "Blocks"},
                        "inwardIssue": {"key": "ZZ-1"}}],
    }


CLOUD_ISSUE = {"key": "ABC-1",
               "fields": {**_shared_fields(),
                          "parent": {"key": "ABC-9"},
                          "customfield_10020": [{"id": 4, "name": "S4"}]},
               "changelog": CHANGELOG}
DC_ISSUE = {"key": "ABC-1",
            "fields": {**_shared_fields(),
                       "customfield_10014": "ABC-9",
                       "customfield_10020": [LEGACY_SPRINT]},
            "changelog": CHANGELOG}


def _extract_to(adapter, cfg, http, out_dir):
    categories = adapter.fetch_status_categories(cfg, http=http)
    adapter.write_bundle(
        out_dir,
        as_of="2026-07-12",
        issues=adapter.fetch_issues(cfg, categories, {}, http=http),
        sprints=adapter.fetch_sprints(cfg, http=http),
        versions=adapter.fetch_versions(cfg, http=http),
        hygiene=adapter.fetch_hygiene(cfg, RULES, http=http),
        config={"team": ["ada"]})


def test_dc_and_cloud_emit_identical_bundles(tmp_path, make_http):
    """THE load-bearing test. Both adapters see the same logical issue in
    their own REST dialect -- Cloud's parent + sprint objects and token
    cursor, Data Center's epic custom field + legacy sprint string and
    offset paging -- and must produce byte-identical bundles, including
    the 403 status-unknown stub for the linked issue."""
    cloud_http = make_http()
    cloud_http.add("GET", "/rest/api/3/status", STATUSES)
    cloud_http.add("POST", "/rest/api/3/search/jql",
                   {"issues": [CLOUD_ISSUE]})
    cloud_http.add("POST", "/rest/api/3/search/jql",
                   HttpError(403, "https://x.net", "forbidden"))
    cloud_http.add("GET", "/rest/agile/1.0/board/7/sprint", SPRINT_PAGE)
    cloud_http.add("GET", "/rest/api/3/project/ABC/versions", VERSIONS)
    cloud_http.add("POST", "/rest/api/3/search/jql",
                   {"issues": [{"key": "ABC-1"}]})

    dc_http = make_http()
    dc_http.add("GET", "/rest/api/2/status", STATUSES)
    dc_http.add("POST", "/rest/api/2/search",
                {"issues": [DC_ISSUE], "startAt": 0, "maxResults": 100,
                 "total": 1})
    dc_http.add("POST", "/rest/api/2/search",
                HttpError(403, "https://jira.internal", "forbidden"))
    dc_http.add("GET", "/rest/agile/1.0/board/7/sprint", SPRINT_PAGE)
    dc_http.add("GET", "/rest/api/2/project/ABC/versions", VERSIONS)
    dc_http.add("POST", "/rest/api/2/search",
                {"issues": [{"key": "ABC-1"}], "startAt": 0,
                 "maxResults": 100, "total": 1})

    cloud_dir, dc_dir = tmp_path / "cloud", tmp_path / "dc"
    _extract_to(jira_extract, CLOUD, cloud_http, cloud_dir)
    _extract_to(jira_extract_dc, DC, dc_http, dc_dir)

    for name in ("meta.json", "issues.json", "sprints.json",
                 "fix_versions.json", "hygiene.json", "config.json"):
        assert (cloud_dir / name).read_text() == (dc_dir / name).read_text(), name

    # Guard against a false pass on two empty bundles: the DC issue really
    # did resolve its epic and its legacy sprint string.
    issues = json.loads((dc_dir / "issues.json").read_text())
    assert [i["key"] for i in issues] == ["ABC-1", "ZZ-1"]
    assert issues[0]["epic_key"] == "ABC-9"
    assert issues[0]["sprint_id"] == 4
    assert issues[0]["original_estimate_days"] == 2.0
    assert issues[0]["first_in_progress"] == "2026-07-02"
    assert issues[1]["external"] is True


class _FakeUrlopenResponse:
    """Mimics what urllib.request.urlopen(...) hands urllib_transport."""

    def __init__(self, status, payload):
        self.status = status
        self.headers = {}
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class _Recorder:
    def __init__(self, routes):
        self.routes = routes
        self.seen = []          # (method, url, headers)

    def __call__(self, req, *args, **kwargs):
        method, url = req.get_method(), req.full_url
        self.seen.append((method, url, dict(req.headers)))
        for want_method, want_path, payload in self.routes:
            if want_method == method and want_path in url:
                return _FakeUrlopenResponse(200, payload)
        raise AssertionError(f"unexpected request: {method} {url}")


def test_cli_extract_routes_datacenter_config_to_the_dc_adapter(
        tmp_path, monkeypatch):
    """Drives the real `tentpole extract` entry point with a datacenter
    config: argparse -> adapters/cli._extract -> jira_extract_dc. Proves
    the dispatch, the Bearer header, and the /rest/api/2 surface."""
    monkeypatch.setenv("JIRA_PAT", "dc-pat")
    config_path = tmp_path / "tentpole.yaml"
    config_path.write_text(
        "jira:\n"
        "  base_url: https://jira.internal\n"
        "  deployment: datacenter\n"
        "  token_env_var: JIRA_PAT\n"
        "  epic_link_field: customfield_10014\n"
        "  scope_jql: project = ABC\n"
        "core:\n"
        "  team: [ada]\n")
    routes = [
        ("GET", "/rest/api/2/status", STATUSES),
        ("POST", "/rest/api/2/search",
         {"issues": [{"key": "ABC-1",
                      "fields": {**_shared_fields(),
                                 "issuelinks": [],
                                 "customfield_10014": "ABC-9",
                                 "customfield_10020": [LEGACY_SPRINT]},
                      "changelog": CHANGELOG}],
          "startAt": 0, "maxResults": 100, "total": 1}),
    ]
    recorder = _Recorder(routes)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    out_dir = tmp_path / "bundle"

    assert main(["extract", "--config", str(config_path),
                 "--out", str(out_dir)]) == 0

    bundle = load_bundle(out_dir)
    assert [i.key for i in bundle.issues] == ["ABC-1"]
    assert bundle.issues[0].epic_key == "ABC-9"
    assert bundle.issues[0].sprint_id == 4
    assert bundle.config.team == ["ada"]
    # Bearer PAT on every call, and never a Cloud endpoint.
    assert [h["Authorization"] for _, _, h in recorder.seen] == [
        "Bearer dc-pat", "Bearer dc-pat"]
    assert all("/rest/api/3" not in url for _, url, _ in recorder.seen)
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_jira_extract_dc_bundle.py -v`
Expected: `test_dc_and_cloud_emit_identical_bundles` PASSES already (both
adapters exist as of Task 5), and
`test_cli_extract_routes_datacenter_config_to_the_dc_adapter` FAILS with
`AssertionError: unexpected request: GET https://jira.internal/rest/api/3/status`
— `_extract` still hardcodes the Cloud adapter. That single red is the point of
this task; if the equivalence test is red instead, the Data Center adapter has a
real bundle-contract bug — fix the adapter, not the test.

- [ ] **Step 4: Implement** — in `src/tentpole/adapters/cli.py`:

Change the adapters import line to include the new module:

```python
from tentpole.adapters import (jira_extract, jira_extract_dc, jira_write,
                               smartsheet_load)
```

Add this helper directly above `_extract`:

```python
def _adapter(jira_cfg):
    """Deployment picks the extract adapter. Both emit the same bundle,
    so nothing downstream of here can tell them apart."""
    if jira_cfg.deployment == "datacenter":
        return jira_extract_dc
    return jira_extract
```

And replace the body of `_extract` with:

```python
def _extract(args) -> int:
    cfg = load_config(args.config)
    if cfg.jira is None:
        raise SystemExit("config has no jira: section")
    adapter = _adapter(cfg.jira)
    rules = load_rules(args.rules) if args.rules else []
    programs = {}
    if cfg.jira.programs_file:
        programs = json.loads(Path(cfg.jira.programs_file).read_text())
    categories = adapter.fetch_status_categories(cfg.jira)
    issues = adapter.fetch_issues(cfg.jira, categories, programs)
    adapter.write_bundle(
        args.out,
        as_of=date.today().isoformat(),
        issues=issues,
        sprints=adapter.fetch_sprints(cfg.jira),
        versions=adapter.fetch_versions(cfg.jira),
        hygiene=adapter.fetch_hygiene(cfg.jira, rules),
        config=cfg.core or None,
    )
    print(f"bundle written to {args.out}")
    return 0
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **199 passed** (197 + 2). The existing Cloud end-to-end extract test in
`tests/test_jira_extract_bundle.py` still passes — its config has no
`deployment:` key, so it defaults to `cloud` and routes to `jira_extract`.

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/adapters/cli.py tests/conftest.py tests/test_jira_extract_dc_bundle.py
git commit -m "feat: extract picks the adapter from jira deployment"
```

---

### Task 7: `fix apply` writes on Data Center

`tentpole fix apply` is the one path that writes to Jira (human-invoked, never
called by the scheduled sync). Its allowlist is structural — `set_fix_version`,
`set_parent`, `add_link` are the module's entire surface — and that does not
change. What changes is that two endpoint paths are hardcoded to `/rest/api/3`,
which does not exist on Data Center, and that `set_parent`'s payload is
Cloud-shaped.

Three things make this small:

1. **Auth is already free.** `jira_write._call` builds its headers from the same
   shared builder the extract adapters use, so a `datacenter` config already
   sends `Bearer <PAT>`. Task 7 only switches the import from the historical
   `jira_extract._headers` alias to `jira_common.headers` directly, and picks up
   `jira_common.api_version` while it is there.
2. **Paths become version-aware.** `_issue_path` and the `issueLink` endpoint
   take the API version from the config: `/rest/api/2/...` on datacenter,
   `/rest/api/3/...` on cloud.
3. **Only `set_parent`'s payload differs.** Data Center has no `parent` for
   epics, so the epic key goes back into the same custom field
   `jira_extract_dc` reads it from: `fields: {<cfg.epic_link_field>: "E-2"}`.
   Cloud keeps `fields: {parent: {key: "E-2"}}`. The set-fixVersion and add-link
   bodies are identical across deployments.

**No defensive `None` check for `epic_link_field`.** Task 2's `JiraConfig`
validation raises at config-load time when `deployment: datacenter` has no
`epic_link_field`, so a datacenter config that reaches `set_parent` without one
is unrepresentable. Adding a runtime guard here would be dead code, and dead
code that "handles" an impossible case is exactly how a silent no-op gets
introduced later.

**Files:**
- Modify: `src/tentpole/adapters/jira_write.py`
- Test: `tests/test_fix_apply.py` (+6, append only)

**Interfaces:**
- Consumes: `jira_common.headers(cfg)` and `jira_common.api_version(cfg)`
  (Task 3); `JiraConfig.deployment` and `JiraConfig.epic_link_field` (Task 2).
- Produces: `_issue_path(cfg, key) -> str` (note: this helper gains a leading
  `cfg` parameter — it was `_issue_path(key)`; it is module-private and has no
  callers outside `jira_write.py`). The public signatures of `set_fix_version`,
  `set_parent`, `add_link`, and `apply_action` are unchanged.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_fix_apply.py`.
      The file already imports `JiraConfig`, `add_link`, `apply_action`,
      `set_fix_version`, `set_parent`, and defines the Cloud `CFG`. Add the
      datacenter config constant and the six tests:

```python
DC = JiraConfig(base_url="https://jira.internal", email=None, token="pat",
                scope_jql="project = ABC", deployment="datacenter",
                epic_link_field="customfield_10014")


def test_set_fix_version_uses_api_2_on_datacenter(fake_http):
    fake_http.add("PUT", "/rest/api/2/issue/T-1", {})
    set_fix_version(DC, "T-1", "R1", http=fake_http)
    assert "/rest/api/2/issue/T-1" in fake_http.calls[0]["url"]
    # Identical payload across deployments; only the path moves.
    assert fake_http.calls[0]["body"] == {
        "update": {"fixVersions": [{"add": {"name": "R1"}}]}}


def test_set_parent_writes_epic_link_field_on_datacenter(fake_http):
    """The exact mirror of the read side: Data Center has no `parent`, so
    the epic key goes back into the same custom field jira_extract_dc
    reads it from."""
    fake_http.add("PUT", "/rest/api/2/issue/T-1", {})
    set_parent(DC, "T-1", "E-2", http=fake_http)
    assert "/rest/api/2/issue/T-1" in fake_http.calls[0]["url"]
    assert fake_http.calls[0]["body"] == {
        "fields": {"customfield_10014": "E-2"}}


def test_add_link_uses_api_2_on_datacenter(fake_http):
    fake_http.add("POST", "/rest/api/2/issueLink", {})
    add_link(DC, "T-1", "X-9", http=fake_http)
    assert "/rest/api/2/issueLink" in fake_http.calls[0]["url"]
    assert fake_http.calls[0]["body"] == {
        "type": {"name": "Blocks"},
        "outwardIssue": {"key": "T-1"},
        "inwardIssue": {"key": "X-9"}}


def test_cloud_write_paths_stay_on_api_3(fake_http):
    """Regression guard: making the paths version-aware must not move
    Cloud, and Cloud's set_parent must keep the `parent` payload."""
    fake_http.add("PUT", "/rest/api/3/issue/T-1", {})
    fake_http.add("PUT", "/rest/api/3/issue/T-1", {})
    fake_http.add("POST", "/rest/api/3/issueLink", {})
    set_fix_version(CFG, "T-1", "R1", http=fake_http)
    set_parent(CFG, "T-1", "E-2", http=fake_http)
    add_link(CFG, "T-1", "X-9", http=fake_http)
    assert [c["url"] for c in fake_http.calls] == [
        "https://x.net/rest/api/3/issue/T-1",
        "https://x.net/rest/api/3/issue/T-1",
        "https://x.net/rest/api/3/issueLink"]
    assert fake_http.calls[1]["body"] == {
        "fields": {"parent": {"key": "E-2"}}}


def test_apply_action_routes_all_three_on_datacenter(fake_http):
    fake_http.add("PUT", "/rest/api/2/issue/T-1", {})
    fake_http.add("PUT", "/rest/api/2/issue/T-2", {})
    fake_http.add("POST", "/rest/api/2/issueLink", {})
    apply_action(DC, "set_fix_version", "T-1", "R1", http=fake_http)
    apply_action(DC, "set_parent", "T-2", "E-1", http=fake_http)
    apply_action(DC, "add_link", "T-3", "X-9", http=fake_http)
    assert [c["method"] for c in fake_http.calls] == ["PUT", "PUT", "POST"]
    assert fake_http.calls[1]["body"] == {
        "fields": {"customfield_10014": "E-1"}}


def test_issue_key_is_url_escaped_on_datacenter(fake_http):
    fake_http.add("PUT", "/rest/api/2/issue/A%20B%2F1", {})
    set_parent(DC, "A B/1", "E-2", http=fake_http)
    assert "/rest/api/2/issue/A%20B%2F1" in fake_http.calls[0]["url"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_fix_apply.py -v`
Expected: five of the six new tests FAIL, each with
`AssertionError: unexpected request: PUT https://jira.internal/rest/api/3/issue/T-1`
(or the `POST .../rest/api/3/issueLink` equivalent) — the code still builds v3
paths, so `FakeHttp` finds no queued match. `test_cloud_write_paths_stay_on_api_3`
PASSES already: it pins today's Cloud behavior, and its job is to stay green
through the change.

- [ ] **Step 3: Implement** — replace the *entire* contents of
      `src/tentpole/adapters/jira_write.py` with:

```python
"""Allowlisted Jira writes for the human-invoked `fix apply` command
(spec sections 3 and 5). Never called by the scheduled sync. The
allowlist is structural: these three field edits are the module's
entire surface -- no transition or delete code path exists. Writes run
as, and are attributed to, the invoking human's token.

Deployment-aware like the extract adapters: the auth header and the API
version both come from jira_common, and set_parent mirrors the read
side (Cloud writes `parent`; Data Center writes the epic-link custom
field)."""
from __future__ import annotations

from urllib.parse import quote

from tentpole.adapters.config import JiraConfig
from tentpole.adapters.http import request
from tentpole.adapters.jira_common import api_version, headers

ALLOWED_ACTIONS = ("set_fix_version", "set_parent", "add_link")


def _call(cfg, method, path, *, body, http=request):
    return http(method, cfg.base_url + path, headers(cfg), body=body)


def _issue_path(cfg: JiraConfig, key: str) -> str:
    return f"/rest/api/{api_version(cfg)}/issue/{quote(key, safe='')}"


def set_fix_version(cfg: JiraConfig, key: str, version: str,
                    http=request) -> None:
    _call(cfg, "PUT", _issue_path(cfg, key),
          body={"update": {"fixVersions": [{"add": {"name": version}}]}},
          http=http)


def set_parent(cfg: JiraConfig, key: str, parent_key: str,
               http=request) -> None:
    if cfg.deployment == "datacenter":
        # Data Center has no `parent` for epics, so the epic key goes
        # back into the same custom field jira_extract_dc reads it from.
        # cfg.epic_link_field is guaranteed non-empty here: JiraConfig
        # rejects a datacenter config without it at load time, so there
        # is no None case to defend against.
        fields = {cfg.epic_link_field: parent_key}
    else:
        fields = {"parent": {"key": parent_key}}
    _call(cfg, "PUT", _issue_path(cfg, key), body={"fields": fields},
          http=http)


def add_link(cfg: JiraConfig, key: str, other_key: str,
             link_type: str = "Blocks", http=request) -> None:
    # `key` blocks `other_key` (outward side of the link).
    _call(cfg, "POST", f"/rest/api/{api_version(cfg)}/issueLink",
          body={"type": {"name": link_type},
                "outwardIssue": {"key": key},
                "inwardIssue": {"key": other_key}}, http=http)


def apply_action(cfg: JiraConfig, action: str, issue: str, value: str,
                 http=request) -> None:
    if action == "set_fix_version":
        set_fix_version(cfg, issue, value, http=http)
    elif action == "set_parent":
        set_parent(cfg, issue, value, http=http)
    elif action == "add_link":
        add_link(cfg, issue, value, http=http)
    else:
        raise ValueError(
            f"action {action!r} is not in the fix-apply allowlist "
            f"{ALLOWED_ACTIONS}")
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: **205 passed** (199 + 6). The seven pre-existing `test_fix_apply.py`
tests (`test_set_fix_version_body`, `test_set_parent_body`, `test_add_link_body`,
`test_issue_key_is_url_escaped`, `test_apply_action_rejects_unallowlisted`, and
the two `fix apply` prompt-flow tests) all
still pass unchanged — their Cloud `CFG` has no `deployment:` key, so it defaults
to `cloud` and every path stays on `/rest/api/3`.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/adapters/jira_write.py tests/test_fix_apply.py
git commit -m "feat: fix apply writes to Jira Data Center"
```

---

### Task 8: Docs and version 0.4.0

**Files:**
- Modify: `README.md`, `pyproject.toml`

**Interfaces:** none.

- [ ] **Step 1: Document the new config keys in the Quickstart example**

In `README.md`, in the Quickstart `tentpole.yaml` example, the `jira:` block
currently begins with `base_url` / `email` / `token_env_var`. Add a `deployment:`
line as the first key under `jira:` and a `sprints_per_plan:` line under `core:`,
so the block reads:

```yaml
   jira:
     deployment: cloud              # cloud (default) | datacenter
     base_url: https://yourco.atlassian.net
     email: you@yourco.com
     token_env_var: JIRA_TOKEN      # NAME of the env var holding the
                                    # token; the token itself never
                                    # lives in this file
     scope_jql: project = ABC
     projects: [ABC]
     board_id: 42
```

and

```yaml
   core:
     team: [ada, grace]
     sprints_per_plan: 6            # how many sprints a plan+N bucket
                                    # spans AND is priced at (default 6)
```

- [ ] **Step 2: Add a Data Center section**

In `README.md`, immediately after the Quickstart section (before `## Releasing`),
add:

```markdown
## Jira Data Center / Server

Self-hosted Jira speaks a different REST dialect than Cloud. Set
`deployment: datacenter` and tentpole switches adapters: Bearer personal
access token instead of Basic `email:token`, `/rest/api/2` instead of
`/rest/api/3`, `startAt`/`maxResults` offset paging instead of Cloud's
`nextPageToken` cursor, and the epic key from a custom field instead of
`parent`. The bundle it produces is identical, so everything downstream —
`sync`, `check`, `push` — is unchanged. `tentpole fix apply` writes back to
Data Center too: it uses the same `/rest/api/2` surface, and the epic-link
fix writes the epic key into your `epic_link_field` rather than `parent`.

```yaml
jira:
  deployment: datacenter
  base_url: https://jira.internal.yourco.com
  # email is not needed: Data Center authenticates with a Bearer PAT
  token_env_var: JIRA_PAT
  epic_link_field: customfield_10014   # required on datacenter
  sprint_field: customfield_10104      # instance-specific too
  scope_jql: project = ABC
  projects: [ABC]
  board_id: 42
```

**Custom-field ids are instance-specific.** `epic_link_field` (the Epic
Link) and `sprint_field` differ between Jira instances and must never be
guessed. Find them on your instance with:

```sh
curl -H "Authorization: Bearer $JIRA_PAT" \
     https://jira.internal.yourco.com/rest/api/2/field
```

and look for the fields named "Epic Link" and "Sprint".

**Smoke it before you trust it.** Recorded fixtures can drift from a live
instance's shapes. Run one real `tentpole extract` against your instance and
eyeball `bundle/issues.json` — every issue should carry the `epic_key` and
`sprint_id` you expect — before wiring the adapter into a scheduled sync.

This goes double for writes: `fix apply` prompts per proposal, so apply a
single low-stakes `set_parent` fix by hand first and confirm in the Jira UI
that the epic link actually moved. A wrong `epic_link_field` writes to the
wrong custom field, and unlike a bad read, that one is visible to your team.
```

- [ ] **Step 3: Bump the version**

In `pyproject.toml`, replace `version = "0.3.0"` with `version = "0.4.0"`.

- [ ] **Step 4: Verify the build and the suite**

Run: `rm -rf dist && .venv/bin/python -m build --sdist --wheel 2>&1 | tail -2`
Expected: `Successfully built tentpole-0.4.0.tar.gz and tentpole-0.4.0-py3-none-any.whl`

Run: `.venv/bin/pytest -q`
Expected: **205 passed**.

- [ ] **Step 5: Commit** (do not commit `dist/`)

```bash
git add README.md pyproject.toml
git commit -m "chore: document the Data Center adapter and sprints_per_plan, version 0.4.0"
```

---

## Self-Review Notes

- **Coverage.** Every requirement has a task: identical bundle contract (Task 6's
  byte-equality test), shared pure helpers *and* fetch loops with a per-adapter
  pagination primitive (Task 3), parameterized epic-key resolution (Tasks 3 and
  5), `deployment` implying auth with no `auth_scheme` knob (Task 2), `email`
  optional on datacenter / required on cloud with actionable errors (Task 2),
  `epic_link_field` required on datacenter and added to the requested field list
  (Tasks 2 and 5), `/rest/api/2` search / status / versions and the shared agile
  sprints (Task 5), `_sprint_id` dict + legacy-string + raise (Task 4),
  `sprints_per_plan` as one derivation feeding both bucket spans and coarse
  capacity with `PLAN_SCALE` deleted (Task 1), 403/404 stubbing reused (shared
  code, tested per-adapter in Task 5), offset-pagination exact-full-final-page
  boundary (Task 5), Data Center writes via `fix apply` — version-aware paths on
  all three edit kinds plus the mirrored `set_parent` payload (Task 7) — and the
  live-smoke requirement, now covering writes as well (Task 8's README caveat).
- **Write-path auth needs no work.** `jira_write._call` builds headers from the
  same `jira_common.headers(cfg)` the extract adapters use, which already
  switches to `Bearer <PAT>` on datacenter. Task 5's
  `test_headers_datacenter_uses_bearer_pat_without_email` covers it; Task 7 adds
  no auth test because there is no separate auth code to test.
- **No dead defensive code in `set_parent`.** Task 2's `JiraConfig` validation
  rejects a `datacenter` config without `epic_link_field` at load time, so the
  `None` case is unrepresentable by the time a write runs. Task 7 states this
  rather than guarding for it.
- **Type consistency.** `search_pages(cfg, jql, fields, *, expand=None,
  http=request)` has the same signature in both adapters and is what
  `jira_common.fetch_issues`/`fetch_hygiene` call. `epic_key_of(fields) -> str |
  None` is the same contract in both (Cloud's is a plain function; Data Center's
  is a closure over `cfg`). Both adapters' `parse_issue(raw, cfg, categories,
  programs, external=False)` keep the historical 4-positional Cloud signature, so
  no existing test changes; only `jira_common.parse_issue` takes the keyword-only
  `epic_key`. `Config.sprints_per_plan: int` is read as
  `bundle.config.sprints_per_plan` in both `buckets.py` and `checks.py`.
- **Backward compatibility.** `jira_extract` re-exports `_headers`,
  `BASE_FIELDS`, `fetch_sprints`, `fetch_status_categories`, `fetch_versions`,
  and `write_bundle` from `jira_common`, so `adapters/cli.py` and the existing
  tests import exactly what they did before. (`jira_write.py`'s own import
  switches to `jira_common` in Task 7 — see below; `test_adapter_config.py`'s
  `_headers` import from `jira_extract` is unaffected.)
  `deployment` defaults to `cloud` and `sprints_per_plan` defaults to `6`, so
  every existing config and fixture behaves identically. Task 7 changes the
  module-private `_issue_path(key)` to `_issue_path(cfg, key)`; it has no callers
  outside `jira_write.py` (verified by grep) and no test references it. The Cloud
  `CFG` in `tests/test_fix_apply.py` carries no `deployment:` key, so every
  pre-existing write test stays on `/rest/api/3`.
- **Suite progression:** 168 → 173 → 178 → 178 → 182 → 197 → 199 → 205 → 205.
