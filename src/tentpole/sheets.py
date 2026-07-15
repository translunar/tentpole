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


def _first_planned(prior_snapshots: list[dict] | None) -> dict[str, str]:
    # Earliest PRIOR snapshot run in which each ticket had a sprint (spec §7).
    # Blank (absent from the map) when there is no history -- the current run
    # is not yet snapshotted at sheet-build time, so a ticket first planned
    # this period shows blank now and dates itself next period.
    earliest: dict[str, str] = {}
    for r in (prior_snapshots or []):
        if r.get("sprint_id") is None:
            continue
        key, run = r["key"], r["run"]
        if key not in earliest or run < earliest[key]:
            earliest[key] = run
    return earliest


def issues_sheet(bundle: Bundle, diag: dict,
                 prior_snapshots: list[dict] | None = None,
                 gantt: bool = False) -> SheetSpec:
    hygiene: dict[str, list[str]] = {}
    for fl in diag["hygiene"]:
        hygiene.setdefault(fl.key, []).append(f"{fl.severity}:{fl.rule}")
    sprint_names = {s.id: s.name for s in bundle.sprints}
    at_risk = {f.subject for f in diag["findings"]
               if f.check == "tentpole_runway"}
    open_work = _open_work(bundle)
    first_planned = _first_planned(prior_snapshots)

    def rollups_for(issue: Issue) -> dict:
        # Populated only on epic rows; blank on tickets (spec §5). Remaining
        # Days is the rollup of OPEN children -- distinct from the
        # ticket-level Remaining Est, which on an epic row stays the epic's
        # own timetracking.
        if issue.issue_type != "Epic":
            return {"Deadline": None, "Open Tickets": None,
                    "Remaining Days": None, "People": None, "Runway": ""}
        children = [i for i in open_work if i.epic_key == issue.key]
        return {
            "Deadline": _iso(effective_deadline(issue, bundle)),
            "Open Tickets": len(children),
            "Remaining Days": sum(estimate_of(i) for i in children),
            "People": ", ".join(sorted({i.assignee for i in children
                                        if i.assignee})),
            "Runway": "AT RISK" if issue.key in at_risk else "",
        }

    def cells_for(issue: Issue) -> dict:
        cells = {
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
            "First Planned": first_planned.get(issue.key),
        }
        cells.update(rollups_for(issue))
        return cells

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
    if gantt:
        from tentpole.gantt import gantt_cells, milestone_rows
        gcells = gantt_cells(bundle)
        for row in rows:
            row.cells.update(gcells.get(row.key, {}))
        rows.extend(milestone_rows(bundle))
    return SheetSpec("issues", rows)


def _open_work(bundle: Bundle) -> list[Issue]:
    return [i for i in bundle.issues
            if not i.external and i.issue_type != "Epic"
            and i.status_category != "done"
            and not is_overhead(i, bundle.config)]


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


def dependencies_sheet(bundle: Bundle) -> SheetSpec:
    internal = {i.key for i in bundle.issues if not i.external}
    rows = []
    for issue in sorted(bundle.issues, key=lambda i: i.key):
        if issue.external:
            continue
        for link in issue.links:
            if link.type != "Blocks" or link.other_key in internal:
                continue
            other = bundle.issue(link.other_key)
            inward = link.direction == "inward"
            key = (f"{issue.key}<-{link.other_key}" if inward
                   else f"{issue.key}->{link.other_key}")
            rows.append(Row(key, {
                "Edge": key,
                "Our Issue": issue.key,
                "Direction": "blocked by" if inward else "blocks",
                "Their Issue": link.other_key,
                "Their Status": other.status_category if other else "unknown",
                "Their Sprint": (str(other.sprint_id)
                                 if other and other.sprint_id else None),
            }))
    return SheetSpec("dependencies", rows)


def capacity_sheet(diag: dict) -> SheetSpec:
    rows = []
    for r in diag["capacity"]:
        key = f"{r['person']}|{r['bucket_id']}"
        rows.append(Row(key, {
            "Cell": key,
            "Person": r["person"],
            "Bucket": r["bucket_id"],
            "Load": r["load"],
            "Capacity": r["capacity"],
            "Overloaded": r["load"] > r["capacity"],
        }))
    return SheetSpec("capacity", rows)


def accuracy_sheet(bundle: Bundle) -> SheetSpec:
    rows = []
    for issue in sorted(bundle.issues, key=lambda i: i.key):
        if (issue.external or issue.issue_type == "Epic"
                or issue.status_category != "done"
                or is_overhead(issue, bundle.config)
                or not issue.original_estimate_days
                or not issue.first_in_progress or not issue.done_at):
            continue
        cycle = (issue.done_at - issue.first_in_progress).days + 1
        rows.append(Row(issue.key, {
            "Key": issue.key,
            "Assignee": issue.assignee,
            "Program": issue.program,
            "Original Est": issue.original_estimate_days,
            "Cycle Days": cycle,
            "Ratio": round(cycle / issue.original_estimate_days, 2),
            "Done": _iso(issue.done_at),
        }))
    return SheetSpec("accuracy", rows)


def build_sheetspecs(bundle: Bundle, diag: dict,
                     prior_snapshots: list[dict] | None = None,
                     gantt: bool = False) -> dict[str, SheetSpec]:
    return {
        "issues": issues_sheet(bundle, diag, prior_snapshots, gantt),
        "fixversions": fixversions_sheet(bundle, diag),
        "dependencies": dependencies_sheet(bundle),
        "capacity": capacity_sheet(diag),
        "accuracy": accuracy_sheet(bundle),
    }
