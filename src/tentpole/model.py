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
