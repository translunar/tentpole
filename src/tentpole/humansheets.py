"""Parse human-owned sheet state (Future Work, Exceptions) back into
bundle inputs (spec section 7: the sync reads these, never writes them)."""
from __future__ import annotations

import re

from tentpole.model import ExceptionRow, Ghost


def _text(cells: dict, name: str) -> str | None:
    value = cells.get(name)
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def _number(cells: dict, name: str, *, sheet: str, row: str) -> float:
    value = cells.get(name)
    if value is None or str(value).strip() == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        # Fail loudly but actionably: a human mistyped a hand-edited cell.
        # Do NOT coerce to 0.0 here -- that would silently understate
        # demand, the exact failure class this tool exists to prevent.
        raise ValueError(
            f"{sheet} row '{row}': column '{name}' must be a number, "
            f"got {value!r}") from None


_TARGET_RE = re.compile(
    r"^(sprint:\d+|plan\+[12]|fixversion:.+|unscheduled)$")


def _target(cells: dict, *, row: str) -> str:
    value = _text(cells, "Target")
    if value is None:
        return "unscheduled"
    if not _TARGET_RE.match(value):
        # Same fail-loud-but-actionable posture as _number: a silent
        # bad Target both understates demand and escapes ghost_claims.
        raise ValueError(
            f"future_work row '{row}': column 'Target' must be one of "
            f"'sprint:<id>', 'plan+1', 'plan+2', 'fixversion:<name>', "
            f"'unscheduled', got {value!r}")
    return value


def ghosts_from_sheet(rows: dict[str, dict]) -> list[Ghost]:
    ghosts = []
    for cells in rows.values():
        title = _text(cells, "Title")
        if not title:
            continue
        ghosts.append(Ghost(
            title=title,
            estimate_days=_number(cells, "Estimate Days",
                                  sheet="future_work", row=title),
            target=_target(cells, row=title),
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
            sprint_id=int(_number(cells, "Sprint",
                                  sheet="exceptions", row=person)),
            day_cost=_number(cells, "Day Cost",
                             sheet="exceptions", row=person),
        ))
    return out


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
