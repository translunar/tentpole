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
