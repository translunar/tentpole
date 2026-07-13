# Core Domain (Plan 1 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pure-transformer core: load a Jira data bundle from JSON files, compile it into demand items, compute capacity/deadline/dependency/hygiene diagnostics, and render them via a `tentpole check --me` CLI.

**Architecture:** Pure functions over an in-memory `Bundle` (spec §3–§5). The only I/O in this plan is `load_bundle` (reads a directory of JSON files — the format extract adapters will emit) and the CLI. No network, no Jira, no Smartsheet. Plan 2 adds SheetSpecs/sync; Plan 3 adds real API adapters.

**Tech Stack:** Python ≥3.12, src layout, dataclasses, PyYAML (hygiene rules config), pytest. Package name `tentpole` (rename is a find-replace if Juno prefers something else — flag at review, don't bikeshed mid-task).

## Global Constraints

- Python ≥ 3.12; runtime dependency: `pyyaml>=6` only; dev dependency: `pytest>=8` only.
- src layout: code in `src/tentpole/`, tests in `tests/`.
- The core never performs I/O except `model.load_bundle` and `cli.py` (spec §3). No module reads clocks: "today" is always `bundle.as_of`.
- All dates are `datetime.date`; JSON uses ISO `YYYY-MM-DD` strings.
- Estimates are floats denominated in days (spec: team estimates in days).
- Severities are exactly `"red"` and `"yellow"`. Status categories are exactly `"todo"`, `"in_progress"`, `"done"`.
- Bucket ids are exactly: `"sprint:<id>"`, `"plan+1"`, `"plan+2"`, `"beyond"`, `"unscheduled"`.
- Run tests with `.venv/bin/pytest` from the repo root (`/Users/juno/Projects/jira-smartsheet`).
- Commit after every task; messages in imperative mood, no scope prefixes beyond `feat:`/`test:`/`chore:`.

---

### Task 1: Scaffolding + data model + bundle loader

**Files:**
- Create: `pyproject.toml`
- Modify: `.gitignore`
- Create: `src/tentpole/__init__.py`
- Create: `src/tentpole/model.py`
- Create: `tests/conftest.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: every dataclass in `model.py` (exact fields below), `Bundle.issue(key) -> Issue | None`, `load_bundle(path: Path) -> Bundle`, and the `make_bundle`/`make_sprints` test fixtures used by every later task.

- [ ] **Step 1: Write pyproject and gitignore**

`pyproject.toml`:

```toml
[project]
name = "tentpole"
version = "0.1.0"
description = "One-way Jira -> Smartsheet planning transformer"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
tentpole = "tentpole.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Append to `.gitignore`:

```
__pycache__/
.pytest_cache/
*.egg-info/
dist/
```

Create empty `src/tentpole/__init__.py`.

- [ ] **Step 2: Install editable**

Run: `.venv/bin/pip install -e '.[dev]'`
Expected: `Successfully installed tentpole-0.1.0` (plus pytest/pyyaml if new).

- [ ] **Step 3: Write the failing tests**

`tests/conftest.py`:

```python
from datetime import date, timedelta

import pytest

from tentpole.model import (
    Bundle, Config, ExceptionRow, FixVersion, Ghost, Issue, Link, Sprint,
)


def _make_sprints(start=date(2026, 7, 13), n=6, first_id=1):
    return [
        Sprint(
            id=first_id + i,
            name=f"S{first_id + i}",
            start=start + timedelta(days=10 * i),
            end=start + timedelta(days=10 * i + 9),
        )
        for i in range(n)
    ]


@pytest.fixture
def make_sprints():
    return _make_sprints


@pytest.fixture
def make_bundle():
    def _make(**overrides):
        defaults = dict(
            as_of=date(2026, 7, 12),
            issues=[],
            sprints=_make_sprints(),
            fix_versions=[],
            ghosts=[],
            exceptions=[],
            hygiene_memberships={},
            config=Config(team=["ada", "grace"]),
        )
        defaults.update(overrides)
        return Bundle(**defaults)

    return _make
```

`tests/test_model.py`:

```python
import json
from datetime import date

from tentpole.model import Config, Issue, load_bundle


def test_bundle_issue_lookup(make_bundle):
    b = make_bundle(issues=[Issue(key="T-1", summary="x", issue_type="Task",
                                  status_category="todo")])
    assert b.issue("T-1").summary == "x"
    assert b.issue("NOPE") is None


def test_load_bundle_from_json_dir(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (tmp_path / "issues.json").write_text(json.dumps([{
        "key": "T-1", "summary": "Parse frames", "issue_type": "Task",
        "status_category": "in_progress", "assignee": "ada",
        "original_estimate_days": 3.0, "remaining_estimate_days": 2.0,
        "epic_key": "E-1", "fix_versions": ["v2.3"], "sprint_id": 1,
        "labels": ["overhead"],
        "links": [{"type": "Blocks", "direction": "inward", "other_key": "X-9"}],
        "program": "telemetry", "first_in_progress": "2026-07-10",
        "done_at": None, "external": False,
    }]))
    (tmp_path / "sprints.json").write_text(json.dumps([
        {"id": 1, "name": "S1", "start": "2026-07-13", "end": "2026-07-22"},
    ]))
    (tmp_path / "fix_versions.json").write_text(json.dumps([
        {"name": "v2.3", "release_date": "2026-08-15", "released": False},
    ]))
    (tmp_path / "ghosts.json").write_text(json.dumps([
        {"title": "Cal pipeline", "estimate_days": 8.0, "target": "plan+1",
         "program": "telemetry", "owner": None, "intended_epic": "E-1",
         "jira_key": None},
    ]))
    (tmp_path / "exceptions.json").write_text(json.dumps([
        {"person": "ada", "sprint_id": 1, "day_cost": 5.0},
    ]))
    (tmp_path / "hygiene.json").write_text(json.dumps({"orphan-task": ["T-1"]}))
    (tmp_path / "config.json").write_text(json.dumps({"team": ["ada", "grace"]}))

    b = load_bundle(tmp_path)
    assert b.as_of == date(2026, 7, 12)
    issue = b.issue("T-1")
    assert issue.fix_versions == ["v2.3"]
    assert issue.links[0].other_key == "X-9"
    assert issue.first_in_progress == date(2026, 7, 10)
    assert b.sprints[0].end == date(2026, 7, 22)
    assert b.fix_versions[0].release_date == date(2026, 8, 15)
    assert b.ghosts[0].target == "plan+1"
    assert b.exceptions[0].day_cost == 5.0
    assert b.hygiene_memberships["orphan-task"] == ["T-1"]
    assert b.config.team == ["ada", "grace"]


def test_load_bundle_tolerates_missing_optional_files(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    b = load_bundle(tmp_path)
    assert b.issues == [] and b.ghosts == []
    assert isinstance(b.config, Config)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_model.py -v`
Expected: FAIL / collection error with `ModuleNotFoundError: No module named 'tentpole.model'`.

- [ ] **Step 5: Implement `src/tentpole/model.py`**

```python
"""Bundle data model: the core's only input format (spec section 3)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Link:
    type: str          # e.g. "Blocks"
    direction: str     # "inward" = other_key acts on us; "outward" = we act on it
    other_key: str


@dataclass
class Issue:
    key: str
    summary: str
    issue_type: str            # "Task" | "Bug" | "Epic" | ...
    status_category: str       # "todo" | "in_progress" | "done"
    assignee: str | None = None
    original_estimate_days: float | None = None
    remaining_estimate_days: float | None = None
    epic_key: str | None = None
    fix_versions: list[str] = field(default_factory=list)
    sprint_id: int | None = None
    labels: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    program: str | None = None
    first_in_progress: date | None = None
    done_at: date | None = None
    external: bool = False


@dataclass
class Sprint:
    id: int
    name: str
    start: date
    end: date


@dataclass
class FixVersion:
    name: str
    release_date: date | None = None
    released: bool = False


@dataclass
class Ghost:
    title: str
    estimate_days: float
    target: str                # "sprint:<id>" | "plan+1" | "plan+2" | "fixversion:<name>" | "unscheduled"
    program: str | None = None
    owner: str | None = None
    intended_epic: str | None = None
    jira_key: str | None = None


@dataclass
class ExceptionRow:
    person: str
    sprint_id: int
    day_cost: float


@dataclass
class Config:
    annual_working_days: float = 230.0
    annual_vacation_days: float = 24.0
    annual_overhead_days: float = 30.0
    sprint_length_days: float = 10.0
    min_sprints_for_empirical: int = 3
    overhead_label: str = "overhead"
    overhead_summary_patterns: tuple[str, ...] = (
        "on-call", "on call", "console", "vacation",
    )
    team: list[str] = field(default_factory=list)


@dataclass
class Bundle:
    as_of: date
    issues: list[Issue]
    sprints: list[Sprint]
    fix_versions: list[FixVersion]
    ghosts: list[Ghost]
    exceptions: list[ExceptionRow]
    hygiene_memberships: dict[str, list[str]]
    config: Config

    def __post_init__(self):
        self._by_key = {i.key: i for i in self.issues}

    def issue(self, key: str | None) -> Issue | None:
        return self._by_key.get(key)


def _date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def load_bundle(path: Path) -> Bundle:
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    issues = [
        Issue(
            key=r["key"], summary=r["summary"], issue_type=r["issue_type"],
            status_category=r["status_category"], assignee=r.get("assignee"),
            original_estimate_days=r.get("original_estimate_days"),
            remaining_estimate_days=r.get("remaining_estimate_days"),
            epic_key=r.get("epic_key"),
            fix_versions=r.get("fix_versions", []),
            sprint_id=r.get("sprint_id"), labels=r.get("labels", []),
            links=[Link(**l) for l in r.get("links", [])],
            program=r.get("program"),
            first_in_progress=_date(r.get("first_in_progress")),
            done_at=_date(r.get("done_at")), external=r.get("external", False),
        )
        for r in _load_json(path / "issues.json", [])
    ]
    sprints = [
        Sprint(id=r["id"], name=r["name"], start=_date(r["start"]),
               end=_date(r["end"]))
        for r in _load_json(path / "sprints.json", [])
    ]
    fix_versions = [
        FixVersion(name=r["name"], release_date=_date(r.get("release_date")),
                   released=r.get("released", False))
        for r in _load_json(path / "fix_versions.json", [])
    ]
    ghosts = [Ghost(**r) for r in _load_json(path / "ghosts.json", [])]
    exceptions = [ExceptionRow(**r) for r in _load_json(path / "exceptions.json", [])]
    config_raw = _load_json(path / "config.json", {})
    if "overhead_summary_patterns" in config_raw:
        config_raw["overhead_summary_patterns"] = tuple(
            config_raw["overhead_summary_patterns"])
    return Bundle(
        as_of=date.fromisoformat(meta["as_of"]),
        issues=issues, sprints=sprints, fix_versions=fix_versions,
        ghosts=ghosts, exceptions=exceptions,
        hygiene_memberships=_load_json(path / "hygiene.json", {}),
        config=Config(**config_raw),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_model.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore src/tentpole tests
git commit -m "feat: scaffolding, bundle data model, JSON bundle loader"
```

---

### Task 2: Time buckets

**Files:**
- Create: `src/tentpole/buckets.py`
- Test: `tests/test_buckets.py`

**Interfaces:**
- Consumes: `Bundle`, `Issue`, `Sprint` from Task 1.
- Produces: `Bucket(id: str, start: date | None, end: date | None)` (frozen dataclass); `buckets_for(bundle) -> list[Bucket]`; `bucket_for_date(d: date, buckets: list[Bucket]) -> str`; `effective_deadline(issue: Issue, bundle: Bundle) -> date | None`; `bucket_for_issue(issue: Issue, bundle: Bundle, buckets: list[Bucket]) -> str`; `sprint_equivalents_until(d: date, buckets: list[Bucket], sprint_length_days: float) -> float`. Bucket ids per Global Constraints.

- [ ] **Step 1: Write the failing tests**

`tests/test_buckets.py`:

```python
from datetime import date

from tentpole.buckets import (
    bucket_for_date, bucket_for_issue, buckets_for, effective_deadline,
    sprint_equivalents_until,
)
from tentpole.model import FixVersion, Issue


def test_buckets_for_builds_sprints_then_coarse(make_bundle):
    b = make_bundle()  # six 10-day sprints starting 2026-07-13
    ids = [bk.id for bk in buckets_for(b)]
    assert ids == ["sprint:1", "sprint:2", "sprint:3", "sprint:4", "sprint:5",
                   "sprint:6", "plan+1", "plan+2", "beyond", "unscheduled"]
    plan1 = next(bk for bk in buckets_for(b) if bk.id == "plan+1")
    # last sprint ends 2026-09-10; plan+1 covers the next 60 days
    assert plan1.start == date(2026, 9, 11)
    assert plan1.end == date(2026, 11, 9)


def test_past_sprints_are_excluded(make_bundle, make_sprints):
    old = make_sprints(start=date(2026, 5, 1), n=2, first_id=90)
    b = make_bundle(sprints=old + make_sprints())
    ids = [bk.id for bk in buckets_for(b)]
    assert "sprint:90" not in ids and "sprint:1" in ids


def test_bucket_for_date(make_bundle):
    b = make_bundle()
    bks = buckets_for(b)
    assert bucket_for_date(date(2026, 7, 15), bks) == "sprint:1"
    assert bucket_for_date(date(2026, 10, 1), bks) == "plan+1"
    assert bucket_for_date(date(2027, 6, 1), bks) == "beyond"


def test_effective_deadline_inherits_from_epic(make_bundle):
    epic = Issue(key="E-1", summary="Epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v2.3"])
    child = Issue(key="T-1", summary="t", issue_type="Task",
                  status_category="todo", epic_key="E-1")
    b = make_bundle(
        issues=[epic, child],
        fix_versions=[FixVersion("v2.3", release_date=date(2026, 10, 1))])
    assert effective_deadline(child, b) == date(2026, 10, 1)
    orphan = Issue(key="T-2", summary="t", issue_type="Task",
                   status_category="todo")
    b2 = make_bundle(issues=[orphan])
    assert effective_deadline(orphan, b2) is None


def test_bucket_for_issue_prefers_sprint_then_deadline(make_bundle):
    in_sprint = Issue(key="T-1", summary="t", issue_type="Task",
                      status_category="todo", sprint_id=2)
    dated = Issue(key="T-2", summary="t", issue_type="Task",
                  status_category="todo", fix_versions=["v9"])
    neither = Issue(key="T-3", summary="t", issue_type="Task",
                    status_category="todo")
    b = make_bundle(
        issues=[in_sprint, dated, neither],
        fix_versions=[FixVersion("v9", release_date=date(2026, 10, 1))])
    bks = buckets_for(b)
    assert bucket_for_issue(in_sprint, b, bks) == "sprint:2"
    assert bucket_for_issue(dated, b, bks) == "plan+1"
    assert bucket_for_issue(neither, b, bks) == "unscheduled"


def test_sprint_equivalents_until(make_bundle):
    bks = buckets_for(make_bundle())
    # end of sprint 3 -> exactly 3 sprints of runway
    assert sprint_equivalents_until(date(2026, 8, 11), bks, 10.0) == 3.0
    # 30 days into plan+1 -> 6 sprints + ~3 more
    val = sprint_equivalents_until(date(2026, 10, 11), bks, 10.0)
    assert 8.5 < val < 9.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_buckets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.buckets'`.

- [ ] **Step 3: Implement `src/tentpole/buckets.py`**

```python
"""Time buckets: sprint-resolution near, coarse far (spec section 4)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from tentpole.model import Bundle, Issue

UNSCHEDULED = "unscheduled"


@dataclass(frozen=True)
class Bucket:
    id: str
    start: date | None
    end: date | None


def buckets_for(bundle: Bundle) -> list[Bucket]:
    active = sorted(
        (s for s in bundle.sprints if s.end >= bundle.as_of),
        key=lambda s: s.start)
    out = [Bucket(f"sprint:{s.id}", s.start, s.end) for s in active]
    anchor = active[-1].end if active else bundle.as_of
    p1_start = anchor + timedelta(days=1)
    p1_end = anchor + timedelta(days=60)
    p2_end = anchor + timedelta(days=120)
    out.append(Bucket("plan+1", p1_start, p1_end))
    out.append(Bucket("plan+2", p1_end + timedelta(days=1), p2_end))
    out.append(Bucket("beyond", p2_end + timedelta(days=1), None))
    out.append(Bucket(UNSCHEDULED, None, None))
    return out


def bucket_for_date(d: date, buckets: list[Bucket]) -> str:
    for bk in buckets:
        if bk.start is None:
            continue
        if bk.end is None and d >= bk.start:
            return bk.id
        if bk.end is not None and bk.start <= d <= bk.end:
            return bk.id
    return UNSCHEDULED


def _earliest_release(names: list[str], bundle: Bundle) -> date | None:
    dates = [fv.release_date for fv in bundle.fix_versions
             if fv.name in names and fv.release_date is not None]
    return min(dates) if dates else None


def effective_deadline(issue: Issue, bundle: Bundle) -> date | None:
    own = _earliest_release(issue.fix_versions, bundle)
    if own:
        return own
    epic = bundle.issue(issue.epic_key)
    if epic:
        return _earliest_release(epic.fix_versions, bundle)
    return None


def bucket_for_issue(issue: Issue, bundle: Bundle,
                     buckets: list[Bucket]) -> str:
    sprint_ids = {bk.id for bk in buckets}
    if issue.sprint_id is not None and f"sprint:{issue.sprint_id}" in sprint_ids:
        return f"sprint:{issue.sprint_id}"
    deadline = effective_deadline(issue, bundle)
    if deadline:
        return bucket_for_date(deadline, buckets)
    return UNSCHEDULED


def sprint_equivalents_until(d: date, buckets: list[Bucket],
                             sprint_length_days: float) -> float:
    total = 0.0
    for bk in buckets:
        if bk.start is None:
            continue
        if bk.id.startswith("sprint:"):
            if bk.end is not None and bk.end <= d:
                total += 1.0
        else:
            if d >= bk.start:
                span_end = d if bk.end is None else min(d, bk.end)
                total += ((span_end - bk.start).days + 1) / sprint_length_days
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_buckets.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/buckets.py tests/test_buckets.py
git commit -m "feat: time buckets with sprint resolution near, coarse far"
```

---

### Task 3: Demand compilation

**Files:**
- Create: `src/tentpole/demand.py`
- Test: `tests/test_demand.py`

**Interfaces:**
- Consumes: Task 1 model; Task 2 `buckets_for`, `bucket_for_issue`, `bucket_for_date`, `UNSCHEDULED`.
- Produces: `DemandItem(who: str | None, estimate_days: float, bucket_id: str, epic_key: str | None, fix_versions: tuple[str, ...], program: str | None, kind: str, source: str)` (frozen; `kind` in `"real" | "ghost" | "overhead"`); `is_overhead(issue: Issue, config: Config) -> bool`; `estimate_of(issue: Issue) -> float`; `compile_demand(bundle: Bundle, buckets: list[Bucket]) -> list[DemandItem]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_demand.py`:

```python
from datetime import date

from tentpole.buckets import buckets_for
from tentpole.demand import compile_demand, estimate_of, is_overhead
from tentpole.model import Config, FixVersion, Ghost, Issue


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_is_overhead_by_label_and_summary():
    cfg = Config()
    assert is_overhead(_task("T-1", labels=["overhead"]), cfg)
    assert is_overhead(_task("T-2", summary="On console week 3"), cfg)
    assert not is_overhead(_task("T-3", summary="Parse frames"), cfg)


def test_estimate_prefers_remaining():
    assert estimate_of(_task("T-1", original_estimate_days=5.0,
                             remaining_estimate_days=2.0)) == 2.0
    assert estimate_of(_task("T-2", original_estimate_days=5.0)) == 5.0
    assert estimate_of(_task("T-3")) == 0.0


def test_compile_demand_kinds_and_exclusions(make_bundle):
    issues = [
        _task("T-1", assignee="ada", sprint_id=1, remaining_estimate_days=3.0,
              epic_key="E-1", program="telemetry"),
        _task("T-2", assignee="ada", sprint_id=1, remaining_estimate_days=4.0,
              labels=["overhead"]),
        _task("T-3", assignee="ada", status_category="done",
              remaining_estimate_days=9.0),           # done: excluded
        Issue(key="E-1", summary="Epic", issue_type="Epic",
              status_category="in_progress"),          # epic: excluded
        _task("X-1", assignee="sam", external=True,
              remaining_estimate_days=9.0),            # external: excluded
    ]
    b = make_bundle(issues=issues)
    items = compile_demand(b, buckets_for(b))
    by_source = {i.source: i for i in items}
    assert by_source["T-1"].kind == "real"
    assert by_source["T-1"].bucket_id == "sprint:1"
    assert by_source["T-1"].fix_versions == ()
    assert by_source["T-2"].kind == "overhead"
    assert {"T-3", "E-1", "X-1"}.isdisjoint(by_source)


def test_compile_demand_ghosts(make_bundle):
    ghosts = [
        Ghost(title="Cal pipeline", estimate_days=8.0, target="plan+1",
              owner=None, intended_epic="E-1", program="telemetry"),
        Ghost(title="Already real", estimate_days=5.0, target="plan+1",
              jira_key="T-9"),                          # superseded: excluded
        Ghost(title="Sprint-targeted", estimate_days=2.0, target="sprint:3",
              owner="grace"),
        Ghost(title="Milestone-targeted", estimate_days=2.0,
              target="fixversion:v9"),
    ]
    b = make_bundle(
        ghosts=ghosts,
        fix_versions=[FixVersion("v9", release_date=date(2026, 10, 1))])
    items = {i.source: i for i in compile_demand(b, buckets_for(b))}
    assert items["Cal pipeline"].kind == "ghost"
    assert items["Cal pipeline"].who is None
    assert items["Cal pipeline"].epic_key == "E-1"
    assert "Already real" not in items
    assert items["Sprint-targeted"].bucket_id == "sprint:3"
    assert items["Milestone-targeted"].bucket_id == "plan+1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_demand.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.demand'`.

- [ ] **Step 3: Implement `src/tentpole/demand.py`**

```python
"""Compile issues and ghosts into demand items (spec section 4)."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.buckets import (
    UNSCHEDULED, Bucket, bucket_for_date, bucket_for_issue,
)
from tentpole.model import Bundle, Config, Issue


@dataclass(frozen=True)
class DemandItem:
    who: str | None
    estimate_days: float
    bucket_id: str
    epic_key: str | None
    fix_versions: tuple[str, ...]
    program: str | None
    kind: str          # "real" | "ghost" | "overhead"
    source: str        # issue key or ghost title


def is_overhead(issue: Issue, config: Config) -> bool:
    if config.overhead_label in issue.labels:
        return True
    summary = issue.summary.lower()
    return any(p in summary for p in config.overhead_summary_patterns)


def estimate_of(issue: Issue) -> float:
    if issue.remaining_estimate_days is not None:
        return issue.remaining_estimate_days
    if issue.original_estimate_days is not None:
        return issue.original_estimate_days
    return 0.0


def _ghost_bucket(target: str, bundle: Bundle, buckets: list[Bucket]) -> str:
    ids = {bk.id for bk in buckets}
    if target in ids:
        return target
    if target.startswith("fixversion:"):
        name = target.split(":", 1)[1]
        for fv in bundle.fix_versions:
            if fv.name == name and fv.release_date:
                return bucket_for_date(fv.release_date, buckets)
    return UNSCHEDULED


def compile_demand(bundle: Bundle, buckets: list[Bucket]) -> list[DemandItem]:
    items: list[DemandItem] = []
    for issue in bundle.issues:
        if issue.external or issue.issue_type == "Epic":
            continue
        if issue.status_category == "done":
            continue
        kind = "overhead" if is_overhead(issue, bundle.config) else "real"
        items.append(DemandItem(
            who=issue.assignee,
            estimate_days=estimate_of(issue),
            bucket_id=bucket_for_issue(issue, bundle, buckets),
            epic_key=issue.epic_key,
            fix_versions=tuple(issue.fix_versions),
            program=issue.program,
            kind=kind,
            source=issue.key,
        ))
    for ghost in bundle.ghosts:
        if ghost.jira_key:
            continue  # superseded by a real ticket
        items.append(DemandItem(
            who=ghost.owner,
            estimate_days=ghost.estimate_days,
            bucket_id=_ghost_bucket(ghost.target, bundle, buckets),
            epic_key=ghost.intended_epic,
            fix_versions=(),
            program=ghost.program,
            kind="ghost",
            source=ghost.title,
        ))
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_demand.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/demand.py tests/test_demand.py
git commit -m "feat: compile issues and ghosts into demand items"
```

---

### Task 4: Throughput and capacity

**Files:**
- Create: `src/tentpole/throughput.py`
- Test: `tests/test_throughput.py`

**Interfaces:**
- Consumes: Task 1 model; Task 2 `Bucket`; Task 3 `DemandItem`, `is_overhead`, `estimate_of`.
- Produces: `prior(config: Config) -> float`; `empirical(bundle: Bundle, person: str) -> float | None`; `throughput_for(bundle: Bundle, person: str) -> float`; `capacity_for(bundle: Bundle, person: str, bucket: Bucket, demand: list[DemandItem]) -> float`.

- [ ] **Step 1: Write the failing tests**

`tests/test_throughput.py`:

```python
from datetime import date

from tentpole.buckets import buckets_for
from tentpole.demand import DemandItem, compile_demand
from tentpole.model import Config, ExceptionRow, Issue
from tentpole.throughput import capacity_for, empirical, prior, throughput_for


def _done(key, person, est, done_at, **kw):
    return Issue(key=key, summary=kw.pop("summary", "t"), issue_type="Task",
                 status_category="done", assignee=person,
                 original_estimate_days=est, done_at=done_at, **kw)


def test_prior_from_annual_figures():
    cfg = Config(annual_working_days=230.0, annual_vacation_days=24.0,
                 annual_overhead_days=30.0, sprint_length_days=10.0)
    # 10 * (230 - 24 - 30) / 230 = 7.652...
    assert abs(prior(cfg) - 7.652) < 0.01


def test_empirical_needs_min_sprints(make_bundle, make_sprints):
    past = make_sprints(start=date(2026, 5, 1), n=3, first_id=101)
    issues = [
        _done("T-1", "ada", 6.0, date(2026, 5, 5)),    # sprint 101
        _done("T-2", "ada", 4.0, date(2026, 5, 15)),   # sprint 102
        _done("T-3", "ada", 5.0, date(2026, 5, 25)),   # sprint 103
        _done("T-4", "ada", 9.0, date(2026, 5, 6),
              summary="On console", ),                  # overhead: excluded
    ]
    b = make_bundle(sprints=past + make_sprints(), issues=issues)
    assert empirical(b, "ada") == 5.0                   # mean(6, 4, 5)
    assert empirical(b, "grace") == 0.0                 # present, idle
    b_short = make_bundle(
        sprints=make_sprints(start=date(2026, 6, 20), n=2, first_id=101)
        + make_sprints(),
        issues=issues[:1])
    assert empirical(b_short, "ada") is None            # only 2 past sprints


def test_throughput_falls_back_to_prior(make_bundle):
    b = make_bundle()  # no past sprints at all
    assert throughput_for(b, "ada") == prior(b.config)


def test_capacity_subtracts_overhead_and_exceptions(make_bundle):
    oncall = Issue(key="T-2", summary="on call", issue_type="Task",
                   status_category="todo", assignee="ada", sprint_id=1,
                   remaining_estimate_days=2.0)
    b = make_bundle(issues=[oncall],
                    exceptions=[ExceptionRow("ada", 1, 3.0)])
    bks = buckets_for(b)
    demand = compile_demand(b, bks)
    sprint1 = next(bk for bk in bks if bk.id == "sprint:1")
    expected = prior(b.config) - 2.0 - 3.0
    assert abs(capacity_for(b, "ada", sprint1, demand) - expected) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_throughput.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.throughput'`.

- [ ] **Step 3: Implement `src/tentpole/throughput.py`**

```python
"""Per-person throughput: empirical when history exists, prior until then
(spec section 5)."""
from __future__ import annotations

from tentpole.buckets import Bucket
from tentpole.demand import DemandItem, is_overhead
from tentpole.model import Bundle, Config


def prior(config: Config) -> float:
    available = (config.annual_working_days - config.annual_vacation_days
                 - config.annual_overhead_days)
    return config.sprint_length_days * available / config.annual_working_days


def empirical(bundle: Bundle, person: str) -> float | None:
    past = [s for s in bundle.sprints if s.end < bundle.as_of]
    if len(past) < bundle.config.min_sprints_for_empirical:
        return None
    per_sprint = []
    for sprint in past:
        total = sum(
            (issue.original_estimate_days or 0.0)
            for issue in bundle.issues
            if issue.assignee == person
            and issue.done_at is not None
            and sprint.start <= issue.done_at <= sprint.end
            and issue.issue_type != "Epic"
            and not is_overhead(issue, bundle.config)
        )
        per_sprint.append(total)
    return sum(per_sprint) / len(per_sprint)


def throughput_for(bundle: Bundle, person: str) -> float:
    measured = empirical(bundle, person)
    return measured if measured is not None else prior(bundle.config)


def capacity_for(bundle: Bundle, person: str, bucket: Bucket,
                 demand: list[DemandItem]) -> float:
    cap = throughput_for(bundle, person)
    cap -= sum(d.estimate_days for d in demand
               if d.kind == "overhead" and d.who == person
               and d.bucket_id == bucket.id)
    if bucket.id.startswith("sprint:"):
        sprint_id = int(bucket.id.split(":", 1)[1])
        cap -= sum(e.day_cost for e in bundle.exceptions
                   if e.person == person and e.sprint_id == sprint_id)
    return cap
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_throughput.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/throughput.py tests/test_throughput.py
git commit -m "feat: empirical throughput with configurable prior, capacity math"
```

**Known v1 simplification (do not fix in this task):** `empirical` averages over all past sprints in the bundle and treats zero-completion sprints as signal. The extract layer controls the history horizon (how many past sprints it emits). Documented here so the implementer doesn't "improve" it ad hoc; refinement belongs to Plan 2's snapshot work.

---

### Task 5: Capacity checks — sprint overload and team subscription

**Files:**
- Create: `src/tentpole/checks.py`
- Test: `tests/test_checks_capacity.py`

**Interfaces:**
- Consumes: Tasks 1–4 (`Bundle`, `Bucket`, `DemandItem`, `capacity_for`, `throughput_for`).
- Produces: `Finding(check: str, severity: str, subject: str, bucket_id: str | None, message: str)` (frozen dataclass — the shared result type for ALL checks in Tasks 5–7); `sprint_overload(bundle, buckets, demand) -> list[Finding]`; `team_subscription(bundle, buckets, demand) -> list[Finding]`. Check names are exactly `"sprint_overload"` and `"team_subscription"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_checks_capacity.py`:

```python
from tentpole.buckets import buckets_for
from tentpole.checks import sprint_overload, team_subscription
from tentpole.demand import compile_demand
from tentpole.model import Config, Ghost, Issue


def _task(key, person, est, sprint_id=None, **kw):
    return Issue(key=key, summary="t", issue_type="Task",
                 status_category="todo", assignee=person,
                 remaining_estimate_days=est, sprint_id=sprint_id, **kw)


def test_sprint_overload_flags_only_over_capacity(make_bundle):
    b = make_bundle(issues=[
        _task("T-1", "ada", 9.0, sprint_id=1),   # prior is ~7.65 -> overloaded
        _task("T-2", "grace", 2.0, sprint_id=1),  # fine
    ])
    bks = buckets_for(b)
    findings = sprint_overload(b, bks, compile_demand(b, bks))
    assert len(findings) == 1
    f = findings[0]
    assert (f.check, f.severity, f.subject, f.bucket_id) == (
        "sprint_overload", "red", "ada", "sprint:1")
    assert "9.0" in f.message


def test_team_subscription_counts_ghosts_and_tbd(make_bundle):
    # Team of 2, prior ~7.65 each -> sprint capacity ~15.3; plan+1 ~91.8
    b = make_bundle(
        issues=[_task("T-1", "ada", 4.0, sprint_id=1)],
        ghosts=[Ghost(title="Big ghost", estimate_days=100.0,
                      target="plan+1", owner=None)])
    bks = buckets_for(b)
    findings = team_subscription(b, bks, compile_demand(b, bks))
    assert [f.bucket_id for f in findings] == ["plan+1"]
    assert findings[0].subject == "team"
    assert "100.0" in findings[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_checks_capacity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.checks'`.

- [ ] **Step 3: Implement `src/tentpole/checks.py` (first two checks)**

```python
"""Deterministic planning checks (spec section 5). All checks return Findings."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.buckets import Bucket
from tentpole.demand import DemandItem
from tentpole.model import Bundle
from tentpole.throughput import capacity_for, throughput_for

PLAN_SCALE = {"plan+1": 6.0, "plan+2": 6.0}  # sprints per coarse bucket


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str          # "red" | "yellow"
    subject: str           # person, epic key, fixVersion name, or "team"
    bucket_id: str | None
    message: str


def _load(demand: list[DemandItem], bucket_id: str,
          who: str | None = ...) -> float:
    return sum(d.estimate_days for d in demand
               if d.bucket_id == bucket_id and d.kind in ("real", "ghost")
               and (who is ... or d.who == who))


def sprint_overload(bundle: Bundle, buckets: list[Bucket],
                    demand: list[DemandItem]) -> list[Finding]:
    findings = []
    for bucket in buckets:
        if not bucket.id.startswith("sprint:"):
            continue
        for person in bundle.config.team:
            load = _load(demand, bucket.id, person)
            cap = capacity_for(bundle, person, bucket, demand)
            if load > cap:
                findings.append(Finding(
                    "sprint_overload", "red", person, bucket.id,
                    f"{person}: {load:.1f}d planned vs {cap:.1f}d capacity "
                    f"in {bucket.id}"))
    return findings


def team_subscription(bundle: Bundle, buckets: list[Bucket],
                      demand: list[DemandItem]) -> list[Finding]:
    findings = []
    for bucket in buckets:
        if bucket.id in ("beyond", "unscheduled"):
            continue
        total = _load(demand, bucket.id)
        if bucket.id.startswith("sprint:"):
            cap = sum(capacity_for(bundle, p, bucket, demand)
                      for p in bundle.config.team)
        else:
            cap = sum(throughput_for(bundle, p) * PLAN_SCALE[bucket.id]
                      for p in bundle.config.team)
        if total > cap:
            findings.append(Finding(
                "team_subscription", "red", "team", bucket.id,
                f"{bucket.id}: {total:.1f}d demand vs {cap:.1f}d team "
                f"capacity ({total / cap:.0%} subscribed)"))
    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_checks_capacity.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/checks.py tests/test_checks_capacity.py
git commit -m "feat: sprint overload and team subscription checks"
```

---

### Task 6: Capacity checks — deadline risk and tent-pole runway

**Files:**
- Modify: `src/tentpole/checks.py` (append two functions)
- Test: `tests/test_checks_deadlines.py`

**Interfaces:**
- Consumes: Task 5 `Finding`, `_load`; Task 2 `bucket_for_issue`, `effective_deadline`, `sprint_equivalents_until`; Task 4 `throughput_for`.
- Produces: `deadline_risk(bundle, buckets) -> list[Finding]` (check name `"deadline_risk"`, subject = fixVersion name); `tentpole_runway(bundle, buckets, demand) -> list[Finding]` (check name `"tentpole_runway"`, subject = epic key).

- [ ] **Step 1: Write the failing tests**

`tests/test_checks_deadlines.py`:

```python
from datetime import date

from tentpole.buckets import buckets_for
from tentpole.checks import deadline_risk, tentpole_runway
from tentpole.demand import compile_demand
from tentpole.model import Config, FixVersion, Ghost, Issue


def _task(key, person=None, est=1.0, **kw):
    return Issue(key=key, summary="t", issue_type="Task",
                 status_category="todo", assignee=person,
                 remaining_estimate_days=est, **kw)


def test_deadline_risk(make_bundle):
    # v1 releases 2026-08-01, during sprint 2 (Jul 23 - Aug 1)
    fv = FixVersion("v1", release_date=date(2026, 8, 1))
    b = make_bundle(fix_versions=[fv], issues=[
        _task("OK-1", sprint_id=1, fix_versions=["v1"]),      # before: fine
        _task("LATE-1", sprint_id=4, fix_versions=["v1"]),    # after: red
        _task("LOST-1", fix_versions=["v1"]),  # no sprint -> deadline bucket,
                                               # which is sprint:2 -> fine
        _task("DONE-1", sprint_id=6, fix_versions=["v1"],
              status_category="done"),                        # done: ignored
    ])
    findings = deadline_risk(b, buckets_for(b))
    assert len(findings) == 1
    assert findings[0].subject == "v1"
    assert "LATE-1" in findings[0].message


def test_deadline_risk_flags_truly_unscheduled(make_bundle):
    fv = FixVersion("v1")  # no release date -> issues land unscheduled
    b = make_bundle(fix_versions=[fv],
                    issues=[_task("U-1", fix_versions=["v1"])])
    findings = deadline_risk(b, buckets_for(b))
    assert len(findings) == 1
    assert "unscheduled" in findings[0].message


def test_tentpole_runway(make_bundle):
    # Epic due end of plan+1 (2026-11-01). ada's prior ~7.65/sprint.
    # Runway: 6 sprints + ~5.2 plan+1 sprints ~= 11.2 -> cap ~85d.
    # Epic remaining 60d real + 40d ghost = 100d > 85d -> red.
    epic = Issue(key="E-1", summary="Big epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v9"])
    b = make_bundle(
        config=Config(team=["ada"]),
        fix_versions=[FixVersion("v9", release_date=date(2026, 11, 1))],
        issues=[
            epic,
            _task("T-1", "ada", 60.0, epic_key="E-1", sprint_id=1),
        ],
        ghosts=[Ghost(title="Rest of epic", estimate_days=40.0,
                      target="plan+1", owner="ada", intended_epic="E-1")])
    bks = buckets_for(b)
    findings = tentpole_runway(b, bks, compile_demand(b, bks))
    assert len(findings) == 1
    assert findings[0].subject == "E-1"
    assert findings[0].check == "tentpole_runway"


def test_tentpole_runway_quiet_when_fits(make_bundle):
    epic = Issue(key="E-1", summary="Small epic", issue_type="Epic",
                 status_category="in_progress", fix_versions=["v9"])
    b = make_bundle(
        fix_versions=[FixVersion("v9", release_date=date(2026, 11, 1))],
        issues=[epic, _task("T-1", "ada", 10.0, epic_key="E-1", sprint_id=1)])
    bks = buckets_for(b)
    assert tentpole_runway(b, bks, compile_demand(b, bks)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_checks_deadlines.py -v`
Expected: FAIL with `ImportError: cannot import name 'deadline_risk'`.

- [ ] **Step 3: Append to `src/tentpole/checks.py`**

Add these imports at the top of the file (merge with existing):

```python
from tentpole.buckets import (
    Bucket, bucket_for_issue, effective_deadline, sprint_equivalents_until,
)
```

Append these functions:

```python
def deadline_risk(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    findings = []
    by_bucket_end = {bk.id: bk.end for bk in buckets}
    for fv in bundle.fix_versions:
        if fv.released:
            continue
        late, unscheduled = [], []
        for issue in bundle.issues:
            if (fv.name not in issue.fix_versions
                    or issue.status_category == "done"
                    or issue.issue_type == "Epic" or issue.external):
                continue
            bucket_id = bucket_for_issue(issue, bundle, buckets)
            end = by_bucket_end.get(bucket_id)
            if end is None:
                unscheduled.append(issue.key)
            elif fv.release_date and end > fv.release_date:
                late.append(issue.key)
        if late:
            findings.append(Finding(
                "deadline_risk", "red", fv.name, None,
                f"{fv.name}: scheduled past the {fv.release_date} deadline: "
                f"{', '.join(sorted(late))}"))
        if unscheduled:
            findings.append(Finding(
                "deadline_risk", "red", fv.name, None,
                f"{fv.name}: milestone work unscheduled: "
                f"{', '.join(sorted(unscheduled))}"))
    return findings


def tentpole_runway(bundle: Bundle, buckets: list[Bucket],
                    demand: list[DemandItem]) -> list[Finding]:
    findings = []
    ended = {bk.id: bk.end for bk in buckets}
    for epic in bundle.issues:
        if epic.issue_type != "Epic" or epic.status_category == "done":
            continue
        deadline = effective_deadline(epic, bundle)
        if deadline is None:
            continue
        epic_items = [d for d in demand if d.epic_key == epic.key
                      and d.kind in ("real", "ghost")]
        remaining = sum(d.estimate_days for d in epic_items)
        if remaining == 0:
            continue
        people = sorted({d.who for d in epic_items if d.who}) or list(
            bundle.config.team)
        runway = sprint_equivalents_until(
            deadline, buckets, bundle.config.sprint_length_days)
        total_slack = 0.0
        for person in people:
            cap = throughput_for(bundle, person) * runway
            committed = sum(
                d.estimate_days for d in demand
                if d.who == person and d.epic_key != epic.key
                and d.kind in ("real", "ghost")
                and ended.get(d.bucket_id) is not None
                and ended[d.bucket_id] <= deadline)
            total_slack += max(0.0, cap - committed)
        if remaining > total_slack:
            findings.append(Finding(
                "tentpole_runway", "red", epic.key, None,
                f"{epic.key} ({epic.summary}): {remaining:.1f}d remaining but "
                f"only {total_slack:.1f}d of capacity before {deadline} — "
                f"~{remaining - total_slack:.0f}d short"))
    return findings
```

- [ ] **Step 4: Run all check tests to verify they pass**

Run: `.venv/bin/pytest tests/test_checks_capacity.py tests/test_checks_deadlines.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/checks.py tests/test_checks_deadlines.py
git commit -m "feat: deadline risk and tent-pole runway checks"
```

---

### Task 7: Dependency readiness and ghost claims

**Files:**
- Modify: `src/tentpole/checks.py` (append two functions)
- Test: `tests/test_checks_flow.py`

**Interfaces:**
- Consumes: Task 5 `Finding`; Task 2 `bucket_for_issue`.
- Produces: `dependency_readiness(bundle, buckets) -> list[Finding]` (check name `"dependency_readiness"`, subject = assignee or `"unassigned"`); `ghost_claims(bundle, buckets) -> list[Finding]` (check name `"ghost_claims"`, subject = owner or `"TBD"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_checks_flow.py`:

```python
from tentpole.buckets import buckets_for
from tentpole.checks import dependency_readiness, ghost_claims
from tentpole.model import Ghost, Issue, Link


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def blocked_by(other_key):
    return [Link(type="Blocks", direction="inward", other_key=other_key)]


def test_dependency_readiness(make_bundle):
    issues = [
        _task("T-1", assignee="ada", sprint_id=2, links=blocked_by("X-1")),
        _task("X-1", external=True, sprint_id=5),      # finishes after T-1 starts
        _task("T-2", assignee="ada", sprint_id=2, links=blocked_by("X-2")),
        _task("X-2", external=True, status_category="done"),   # fine
        _task("T-3", assignee="grace", sprint_id=2, links=blocked_by("X-3")),
        _task("X-3", external=True),                   # open, unscheduled
        _task("T-4", assignee="grace", sprint_id=2, links=blocked_by("GONE-1")),
    ]
    b = make_bundle(issues=issues)
    findings = dependency_readiness(b, buckets_for(b))
    by_msg = {f.message for f in findings}
    assert len(findings) == 3
    assert any("T-1" in m and "X-1" in m for m in by_msg)
    assert any("T-3" in m and "unscheduled" in m for m in by_msg)
    assert any("GONE-1" in m and "not in data" in m for m in by_msg)
    gone = next(f for f in findings if "GONE-1" in f.message)
    assert gone.severity == "yellow"


def test_ghost_claims_current_plan_only(make_bundle):
    b = make_bundle(ghosts=[
        Ghost(title="Now-ish", estimate_days=3.0, target="sprint:2",
              owner="ada"),
        Ghost(title="Later", estimate_days=3.0, target="plan+1"),
        Ghost(title="Ticketed", estimate_days=3.0, target="sprint:2",
              jira_key="T-1"),
    ])
    findings = ghost_claims(b, buckets_for(b))
    assert len(findings) == 1
    assert findings[0].subject == "ada"
    assert "Now-ish" in findings[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_checks_flow.py -v`
Expected: FAIL with `ImportError: cannot import name 'dependency_readiness'`.

- [ ] **Step 3: Append to `src/tentpole/checks.py`**

```python
def dependency_readiness(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    findings = []
    sprints_by_id = {f"sprint:{s.id}": s for s in bundle.sprints}
    for issue in bundle.issues:
        if issue.status_category == "done" or issue.external:
            continue
        my_bucket = bucket_for_issue(issue, bundle, buckets)
        if not my_bucket.startswith("sprint:"):
            continue
        my_start = sprints_by_id[my_bucket].start
        subject = issue.assignee or "unassigned"
        for link in issue.links:
            if link.type != "Blocks" or link.direction != "inward":
                continue
            other = bundle.issue(link.other_key)
            if other is None:
                findings.append(Finding(
                    "dependency_readiness", "yellow", subject, my_bucket,
                    f"{issue.key} is blocked by {link.other_key}, "
                    f"which is not in data"))
                continue
            if other.status_category == "done":
                continue
            other_bucket = bucket_for_issue(other, bundle, buckets)
            if not other_bucket.startswith("sprint:"):
                findings.append(Finding(
                    "dependency_readiness", "red", subject, my_bucket,
                    f"{issue.key} is blocked by {other.key}, which is open "
                    f"and unscheduled"))
            elif sprints_by_id[other_bucket].end > my_start:
                findings.append(Finding(
                    "dependency_readiness", "red", subject, my_bucket,
                    f"{issue.key} starts {my_bucket} but its blocker "
                    f"{other.key} finishes {other_bucket}"))
    return findings


def ghost_claims(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    findings = []
    sprint_ids = {bk.id for bk in buckets if bk.id.startswith("sprint:")}
    for ghost in bundle.ghosts:
        if ghost.jira_key or ghost.target not in sprint_ids:
            continue
        findings.append(Finding(
            "ghost_claims", "yellow", ghost.owner or "TBD", ghost.target,
            f"'{ghost.title}' ({ghost.estimate_days:.1f}d) is targeted at "
            f"{ghost.target} but has no Jira ticket — ticket it or push it"))
    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_checks_flow.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/checks.py tests/test_checks_flow.py
git commit -m "feat: dependency readiness and ghost claim checks"
```

---

### Task 8: Hygiene rules

**Files:**
- Create: `src/tentpole/hygiene.py`
- Create: `rules/hygiene.yaml` (the team's default rules, shippable example)
- Test: `tests/test_hygiene.py`

**Interfaces:**
- Consumes: Task 1 model.
- Produces: `Rule(name: str, severity: str, message: str, jql: str | None = None, derived: str | None = None)`; `Flag(rule: str, severity: str, key: str, message: str)` (frozen); `DERIVED_CHECKS: dict[str, Callable[[Issue, Bundle], bool]]` containing `"inherits_no_fixversion"`; `load_rules(path: Path) -> list[Rule]`; `evaluate(bundle: Bundle, rules: list[Rule]) -> list[Flag]`.
- Semantics (spec §5): a rule's `jql` is evaluated by Jira at extract time; the extract adapter stores matching keys in `bundle.hygiene_memberships[rule.name]`. `evaluate` ANDs membership (when `jql` present) with the derived check (when `derived` present). Scope: non-done, non-external issues.

- [ ] **Step 1: Write the failing tests**

`tests/test_hygiene.py`:

```python
import textwrap

from tentpole.hygiene import Rule, evaluate, load_rules
from tentpole.model import FixVersion, Issue


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_load_rules(tmp_path):
    p = tmp_path / "hygiene.yaml"
    p.write_text(textwrap.dedent("""\
        hygiene:
          - name: unanchored-work
            severity: red
            jql: "fixVersion is EMPTY"
            derived: inherits_no_fixversion
            message: "No milestone attached (directly or via epic)"
          - name: orphan-task
            severity: yellow
            jql: 'issuetype != Bug AND parent is EMPTY'
            message: "Task belongs to no epic"
    """))
    rules = load_rules(p)
    assert rules[0] == Rule(name="unanchored-work", severity="red",
                            message="No milestone attached (directly or via epic)",
                            jql="fixVersion is EMPTY",
                            derived="inherits_no_fixversion")
    assert rules[1].derived is None


def test_evaluate_ands_membership_with_derived(make_bundle):
    epic_with_fv = Issue(key="E-1", summary="Epic", issue_type="Epic",
                         status_category="in_progress", fix_versions=["v1"])
    issues = [
        epic_with_fv,
        _task("T-1"),                          # matches JQL, no inheritance -> flag
        _task("T-2", epic_key="E-1"),          # matches JQL, inherits v1 -> no flag
        _task("T-3", status_category="done"),  # done -> out of scope
        _task("T-4", external=True),           # external -> out of scope
    ]
    b = make_bundle(
        issues=issues,
        fix_versions=[FixVersion("v1")],
        hygiene_memberships={"unanchored-work": ["T-1", "T-2", "T-3", "T-4"]})
    rule = Rule(name="unanchored-work", severity="red", message="No milestone",
                jql="fixVersion is EMPTY", derived="inherits_no_fixversion")
    flags = evaluate(b, [rule])
    assert [f.key for f in flags] == ["T-1"]
    assert flags[0].severity == "red"


def test_evaluate_membership_only_rule(make_bundle):
    b = make_bundle(issues=[_task("T-1"), _task("T-2")],
                    hygiene_memberships={"orphan-task": ["T-2"]})
    rule = Rule(name="orphan-task", severity="yellow", message="No epic",
                jql="issuetype != Bug AND parent is EMPTY")
    flags = evaluate(b, [rule])
    assert [f.key for f in flags] == ["T-2"]


def test_missing_membership_means_no_flags(make_bundle):
    b = make_bundle(issues=[_task("T-1")])
    rule = Rule(name="orphan-task", severity="yellow", message="m",
                jql="whatever")
    assert evaluate(b, [rule]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_hygiene.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.hygiene'`.

- [ ] **Step 3: Implement `src/tentpole/hygiene.py`**

```python
"""Hygiene rules: literal JQL (evaluated at extract time) + named derived
checks (spec section 5). No invented query language."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from tentpole.model import Bundle, Issue


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    message: str
    jql: str | None = None
    derived: str | None = None


@dataclass(frozen=True)
class Flag:
    rule: str
    severity: str
    key: str
    message: str


def _inherits_no_fixversion(issue: Issue, bundle: Bundle) -> bool:
    if issue.fix_versions:
        return False
    epic = bundle.issue(issue.epic_key)
    return not (epic and epic.fix_versions)


DERIVED_CHECKS: dict[str, Callable[[Issue, Bundle], bool]] = {
    "inherits_no_fixversion": _inherits_no_fixversion,
}


def load_rules(path: Path) -> list[Rule]:
    raw = yaml.safe_load(Path(path).read_text())
    return [Rule(**entry) for entry in raw["hygiene"]]


def evaluate(bundle: Bundle, rules: list[Rule]) -> list[Flag]:
    flags = []
    for rule in rules:
        membership = set(bundle.hygiene_memberships.get(rule.name, []))
        check = DERIVED_CHECKS[rule.derived] if rule.derived else None
        for issue in bundle.issues:
            if issue.status_category == "done" or issue.external:
                continue
            if rule.jql is not None and issue.key not in membership:
                continue
            if check is not None and not check(issue, bundle):
                continue
            flags.append(Flag(rule=rule.name, severity=rule.severity,
                              key=issue.key, message=rule.message))
    return flags
```

- [ ] **Step 4: Write the shipped default rules**

`rules/hygiene.yaml`:

```yaml
# Team hygiene rules (spec section 5). `jql` is evaluated by Jira at extract
# time; the extract adapter stores matching keys under the rule's name in the
# bundle's hygiene.json. `derived` names a built-in check from
# tentpole.hygiene.DERIVED_CHECKS; when both are present they AND together.
hygiene:
  - name: unanchored-work
    severity: red
    jql: "fixVersion is EMPTY"
    derived: inherits_no_fixversion
    message: "No milestone attached (directly or via epic)"
  - name: orphan-task
    severity: yellow
    jql: 'issuetype != Bug AND parent is EMPTY'
    message: "Task belongs to no epic"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_hygiene.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/hygiene.py rules/hygiene.yaml tests/test_hygiene.py
git commit -m "feat: hygiene rules with JQL membership and derived checks"
```

---

### Task 9: Diagnostics assembly

**Files:**
- Create: `src/tentpole/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: everything from Tasks 2–8.
- Produces: `assemble(bundle: Bundle, rules: list[Rule] | None = None) -> dict` returning `{"as_of": date, "findings": list[Finding], "hygiene": list[Flag], "capacity": list[dict], "demand": list[DemandItem]}` where capacity rows are `{"person": str, "bucket_id": str, "load": float, "capacity": float}` for team × sprint buckets; `personal(diag: dict, bundle: Bundle, person: str) -> dict` (same shape, filtered); `to_json(diag: dict) -> str` (stable machine-readable output, spec §10 agent accommodation).

- [ ] **Step 1: Write the failing tests**

`tests/test_diagnostics.py`:

```python
import json

from tentpole.diagnostics import assemble, personal, to_json
from tentpole.hygiene import Rule
from tentpole.model import Issue, Link


def _task(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def _bundle(make_bundle):
    return make_bundle(
        issues=[
            _task("T-1", assignee="ada", sprint_id=1,
                  remaining_estimate_days=9.0),         # overloads ada
            _task("T-2", assignee="grace", sprint_id=1,
                  remaining_estimate_days=1.0),
        ],
        hygiene_memberships={"orphan-task": ["T-1", "T-2"]})


RULES = [Rule(name="orphan-task", severity="yellow", message="No epic",
              jql="issuetype != Bug AND parent is EMPTY")]


def test_assemble_shape(make_bundle):
    diag = assemble(_bundle(make_bundle), rules=RULES)
    checks_present = {f.check for f in diag["findings"]}
    assert "sprint_overload" in checks_present
    assert [fl.key for fl in diag["hygiene"]] == ["T-1", "T-2"]
    ada_row = next(r for r in diag["capacity"]
                   if r["person"] == "ada" and r["bucket_id"] == "sprint:1")
    assert ada_row["load"] == 9.0
    assert len(diag["demand"]) == 2


def test_personal_filters(make_bundle):
    b = _bundle(make_bundle)
    mine = personal(assemble(b, rules=RULES), b, "ada")
    assert all(f.subject == "ada" for f in mine["findings"])
    assert [fl.key for fl in mine["hygiene"]] == ["T-1"]   # T-2 is grace's
    assert all(r["person"] == "ada" for r in mine["capacity"])
    assert all(d.who == "ada" for d in mine["demand"])


def test_to_json_round_trips(make_bundle):
    diag = assemble(_bundle(make_bundle), rules=RULES)
    parsed = json.loads(to_json(diag))
    assert parsed["as_of"] == "2026-07-12"
    assert isinstance(parsed["findings"], list)
    assert parsed["findings"][0]["check"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_diagnostics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.diagnostics'`.

- [ ] **Step 3: Implement `src/tentpole/diagnostics.py`**

```python
"""Assemble all checks into one machine-readable diagnostics bundle
(spec sections 5 and 10: JSON diagnostics are a public interface)."""
from __future__ import annotations

import dataclasses
import json

from tentpole.buckets import buckets_for
from tentpole.checks import (
    deadline_risk, dependency_readiness, ghost_claims, sprint_overload,
    team_subscription, tentpole_runway,
)
from tentpole.demand import compile_demand
from tentpole.hygiene import Rule, evaluate
from tentpole.model import Bundle
from tentpole.throughput import capacity_for


def assemble(bundle: Bundle, rules: list[Rule] | None = None) -> dict:
    buckets = buckets_for(bundle)
    demand = compile_demand(bundle, buckets)
    findings = (
        sprint_overload(bundle, buckets, demand)
        + team_subscription(bundle, buckets, demand)
        + deadline_risk(bundle, buckets)
        + tentpole_runway(bundle, buckets, demand)
        + dependency_readiness(bundle, buckets)
        + ghost_claims(bundle, buckets)
    )
    capacity = [
        {"person": person, "bucket_id": bucket.id,
         "load": sum(d.estimate_days for d in demand
                     if d.who == person and d.bucket_id == bucket.id
                     and d.kind in ("real", "ghost")),
         "capacity": capacity_for(bundle, person, bucket, demand)}
        for bucket in buckets if bucket.id.startswith("sprint:")
        for person in bundle.config.team
    ]
    return {
        "as_of": bundle.as_of,
        "findings": findings,
        "hygiene": evaluate(bundle, rules) if rules else [],
        "capacity": capacity,
        "demand": demand,
    }


def personal(diag: dict, bundle: Bundle, person: str) -> dict:
    def _owner(key: str) -> str | None:
        issue = bundle.issue(key)
        return issue.assignee if issue else None

    return {
        "as_of": diag["as_of"],
        "findings": [f for f in diag["findings"] if f.subject == person],
        "hygiene": [fl for fl in diag["hygiene"] if _owner(fl.key) == person],
        "capacity": [r for r in diag["capacity"] if r["person"] == person],
        "demand": [d for d in diag["demand"] if d.who == person],
    }


def to_json(diag: dict) -> str:
    def _default(obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        return str(obj)  # dates -> ISO

    return json.dumps(diag, default=_default, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_diagnostics.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tentpole/diagnostics.py tests/test_diagnostics.py
git commit -m "feat: diagnostics assembly with personal slice and JSON output"
```

---

### Task 10: CLI — `tentpole check`

**Files:**
- Create: `src/tentpole/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 `load_bundle`; Task 8 `load_rules`; Task 9 `assemble`, `personal`, `to_json`.
- Produces: `main(argv: list[str] | None = None) -> int` (console entry point `tentpole`); subcommand `check --bundle DIR [--me NAME] [--rules FILE] [--json]`. Exit code 1 when any red finding is present in the (possibly person-filtered) output, else 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import json

import pytest

from tentpole.cli import main


@pytest.fixture
def bundle_dir(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"as_of": "2026-07-12"}))
    (tmp_path / "sprints.json").write_text(json.dumps([
        {"id": 1, "name": "S1", "start": "2026-07-13", "end": "2026-07-22"},
        {"id": 2, "name": "S2", "start": "2026-07-23", "end": "2026-08-01"},
        {"id": 3, "name": "S3", "start": "2026-08-02", "end": "2026-08-11"},
        {"id": 4, "name": "S4", "start": "2026-08-12", "end": "2026-08-21"},
        {"id": 5, "name": "S5", "start": "2026-08-22", "end": "2026-08-31"},
    ]))
    (tmp_path / "issues.json").write_text(json.dumps([
        {"key": "T-1", "summary": "Parse frames", "issue_type": "Task",
         "status_category": "todo", "assignee": "ada", "sprint_id": 1,
         "remaining_estimate_days": 12.0},
        {"key": "T-2", "summary": "Small fix", "issue_type": "Task",
         "status_category": "todo", "assignee": "grace", "sprint_id": 1,
         "remaining_estimate_days": 1.0},
    ]))
    (tmp_path / "config.json").write_text(json.dumps({"team": ["ada", "grace"]}))
    return tmp_path


def test_check_prints_overload_and_exits_1(bundle_dir, capsys):
    rc = main(["check", "--bundle", str(bundle_dir), "--me", "ada"])
    out = capsys.readouterr().out
    assert "sprint_overload" in out
    assert "12.0" in out
    assert rc == 1


def test_check_clean_person_exits_0(bundle_dir, capsys):
    rc = main(["check", "--bundle", str(bundle_dir), "--me", "grace"])
    out = capsys.readouterr().out
    assert "all clear" in out.lower()
    assert rc == 0


def test_check_json_output(bundle_dir, capsys):
    rc = main(["check", "--bundle", str(bundle_dir), "--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["as_of"] == "2026-07-12"
    assert any(f["check"] == "sprint_overload" for f in parsed["findings"])
    assert rc == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tentpole.cli'` (or `ImportError: cannot import name 'main'`).

- [ ] **Step 3: Implement `src/tentpole/cli.py`**

```python
"""CLI. `tentpole check --bundle DIR --me NAME` is the planning-week loop
(spec section 9)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tentpole.diagnostics import assemble, personal, to_json
from tentpole.hygiene import load_rules
from tentpole.model import load_bundle

_SECTION_ORDER = [
    "sprint_overload", "deadline_risk", "tentpole_runway",
    "dependency_readiness", "ghost_claims", "team_subscription",
]


def _render(diag: dict) -> str:
    lines = [f"as of {diag['as_of']}", ""]
    lines.append("capacity:")
    for row in diag["capacity"]:
        marker = "  OVERLOADED" if row["load"] > row["capacity"] else ""
        lines.append(f"  {row['person']:<10} {row['bucket_id']:<10} "
                     f"load {row['load']:5.1f} / cap {row['capacity']:5.1f}"
                     f"{marker}")
    findings = diag["findings"]
    for check in _SECTION_ORDER:
        section = [f for f in findings if f.check == check]
        if section:
            lines.append("")
            lines.append(f"{check}:")
            for f in section:
                lines.append(f"  [{f.severity}] {f.message}")
    if diag["hygiene"]:
        lines.append("")
        lines.append("hygiene:")
        for fl in diag["hygiene"]:
            lines.append(f"  [{fl.severity}] {fl.key}: {fl.message}")
    if not findings and not diag["hygiene"]:
        lines.append("")
        lines.append("all clear.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tentpole")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="planning checks over a bundle")
    check.add_argument("--bundle", required=True, type=Path)
    check.add_argument("--me", default=None,
                       help="filter to one person's slice")
    check.add_argument("--rules", type=Path, default=None,
                       help="hygiene rules YAML")
    check.add_argument("--json", action="store_true",
                       help="emit machine-readable diagnostics")
    args = parser.parse_args(argv)

    bundle = load_bundle(args.bundle)
    rules = load_rules(args.rules) if args.rules else None
    diag = assemble(bundle, rules=rules)
    if args.me:
        diag = personal(diag, bundle, args.me)
    print(to_json(diag) if args.json else _render(diag))
    return 1 if any(f.severity == "red" for f in diag["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (35 tests).

- [ ] **Step 5: Smoke-test the entry point**

Run: `.venv/bin/tentpole check --help`
Expected: usage text listing `--bundle`, `--me`, `--rules`, `--json`.

- [ ] **Step 6: Commit**

```bash
git add src/tentpole/cli.py tests/test_cli.py
git commit -m "feat: tentpole check CLI with personal slice and JSON output"
```

---

## Post-plan notes for the reviewer (not tasks)

- **Deferred to Plan 2 (sheet layer):** SheetSpecs + declared schemas, change planning (diff vs. current sheet state), snapshot records + estimation-accuracy rows, sync orchestration + run report, `schema show`. The `empirical()` refinement (snapshot-based history instead of `done_at` reconstruction) lands there too.
- **Deferred to Plan 3 (edges):** public Jira Cloud extract adapter (`/rest/api/3/search/jql`, token pagination, `parent`-based epics), Smartsheet load adapter (bulk ops, partial success, backoff, Gov base URL config), hygiene fix strategies + `fix apply`, bootstrap (lowest priority, per spec).
- Package name `tentpole` is a standing offer, not a commitment — renaming before Plan 2 is a five-minute find-replace.
