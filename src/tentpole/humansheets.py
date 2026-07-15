"""Parse human-owned sheet state (Future Work, People) back into bundle
inputs (spec section 7: the sync reads these, never writes them)."""
from __future__ import annotations

import re
from dataclasses import dataclass

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
        days = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"people sheet: burden {item!r} under {person!r}: Days must be "
            f"a number, got {value!r}") from None
    if days < 0:
        # A negative burden distorts demand: effective_throughput_for
        # computes prior - days, so a negative recurring burden INFLATES
        # capacity instead of consuming it, hiding over-subscription. Fail
        # loud rather than let a bad human cell silently reverse the sign.
        raise ValueError(
            f"people sheet: burden {item!r} under {person!r}: Days must be "
            f"non-negative, got {days!r}")
    return days


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
