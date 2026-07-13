"""SheetSpec builders: bundle + diagnostics -> desired mirror-sheet contents
(spec section 7). Cells are JSON-safe primitives; dates are ISO strings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tentpole.buckets import effective_deadline
from tentpole.demand import estimate_of, is_overhead
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


def _open_work(bundle: Bundle) -> list[Issue]:
    return [i for i in bundle.issues
            if not i.external and i.issue_type != "Epic"
            and i.status_category != "done"
            and not is_overhead(i, bundle.config)]


def epics_sheet(bundle: Bundle, diag: dict) -> SheetSpec:
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "tentpole_runway"}
    open_work = _open_work(bundle)
    rows = []
    for epic in sorted((i for i in bundle.issues
                        if i.issue_type == "Epic" and not i.external),
                       key=lambda i: i.key):
        children = [i for i in open_work if i.epic_key == epic.key]
        rows.append(Row(epic.key, {
            "Epic": epic.key,
            "Summary": epic.summary,
            "Program": epic.program,
            "Deadline": _iso(effective_deadline(epic, bundle)),
            "Open Tickets": len(children),
            "Remaining Days": sum(estimate_of(i) for i in children),
            "People": ", ".join(sorted({i.assignee for i in children
                                        if i.assignee})),
            "Runway": "AT RISK" if epic.key in at_risk else "",
        }))
    return SheetSpec("epics", rows)


def fixversions_sheet(bundle: Bundle, diag: dict) -> SheetSpec:
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "deadline_risk"}
    open_work = _open_work(bundle)
    rows = []
    for fv in sorted(bundle.fix_versions, key=lambda f: f.name):
        mine = [i for i in open_work if fv.name in i.fix_versions]
        by_person: dict[str, float] = {}
        for i in mine:
            who = i.assignee or "unassigned"
            by_person[who] = by_person.get(who, 0.0) + estimate_of(i)
        rows.append(Row(fv.name, {
            "Version": fv.name,
            "Release Date": _iso(fv.release_date),
            "Released": fv.released,
            "Open Tickets": len(mine),
            "Remaining Days": sum(estimate_of(i) for i in mine),
            "Remaining By Person": "; ".join(
                f"{p}: {d}" for p, d in sorted(by_person.items())),
            "Risk": "AT RISK" if fv.name in at_risk else "",
        }))
    return SheetSpec("fixversions", rows)
