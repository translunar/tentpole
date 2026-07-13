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
