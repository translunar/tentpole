"""Pure Gantt seeding (spec §6): forecast columns, the curated arrow
subset with deterministic cycle-breaking, and synthetic milestone rows.
No I/O, no clock -- "today" is bundle.as_of. Engine-owned cells are
OMITTED (the write-never realization: an omitted cell is never diffed and
never written)."""
from __future__ import annotations

from tentpole.demand import estimate_of
from tentpole.linkgraph import blocks_edges, break_cycles
from tentpole.model import Bundle, Issue
from tentpole.sheets import Row

DEFAULT_DURATION = 1.0


def _iso(d):
    return d.isoformat() if d else None


def _duration(issue: Issue) -> tuple[float, str | None]:
    est = estimate_of(issue)
    if est and est > 0:
        return est, None
    return DEFAULT_DURATION, "no estimate (defaulted to 1d)"


def _root_start(issue: Issue, bundle: Bundle) -> str:
    # Future sprint-assigned work starts at the sprint window; else today.
    if issue.sprint_id is not None:
        for s in bundle.sprints:
            if s.id == issue.sprint_id and s.start > bundle.as_of:
                return s.start.isoformat()
    return bundle.as_of.isoformat()


def gantt_cells(bundle: Bundle) -> dict[str, dict]:
    ours = {i.key: i for i in bundle.issues if not i.external}
    # Curated arrows: Blocks edges between in-scope non-done tickets where
    # the target has not started; then cycle-broken deterministically.
    candidate = []
    external_into: dict[str, list[str]] = {}
    epic_flag: dict[str, list[str]] = {}
    for src, dst in blocks_edges(bundle):
        target = ours.get(dst)
        source = ours.get(src)
        if target is None or source is None:
            # External / cross-team edge: render as Flags text on whichever
            # endpoint is in scope (mark where the schedule depends on others).
            if target is not None:
                external_into.setdefault(dst, []).append(src)
            continue
        src_epic = source.issue_type == "Epic"
        dst_epic = target.issue_type == "Epic"
        if src_epic or dst_epic:
            # Epic-level blocks links render in Flags, not arrows (spec §6).
            # Flag the non-epic endpoint; when both are epics, flag both epic
            # rows (Flags is our text column, not engine-owned).
            note = f"epic-level blocks link {src} -> {dst}"
            targets = ([src, dst] if src_epic and dst_epic
                       else [dst] if src_epic else [src])
            for ep in targets:
                epic_flag.setdefault(ep, []).append(note)
            continue
        if (target.status_category == "done"
                or source.status_category == "done"):
            continue   # done work takes no arrow (link-hygiene flags staleness)
        if target.first_in_progress is not None \
                or target.status_category == "in_progress":
            continue   # target already started: not schedulable-blocked
        candidate.append((src, dst))
    kept, dropped = break_cycles(candidate)
    preds: dict[str, list[str]] = {}
    for src, dst in kept:
        preds.setdefault(dst, []).append(src)
    cycle_flag: dict[str, list[str]] = {}
    for src, dst in dropped:
        for endpoint in (src, dst):
            cycle_flag.setdefault(endpoint, []).append(f"{src}->{dst}")

    cells: dict[str, dict] = {}
    for key, issue in ours.items():
        if issue.issue_type == "Epic":
            # Engine rolls epic bars up (omit forecast cells), but an
            # epic-level blocks link still renders in the epic's Flags.
            ef = epic_flag.get(key)
            cells[key] = {"Flags": "; ".join(ef)} if ef else {}
            continue
        c: dict = {}
        flags: list[str] = []
        if issue.status_category == "done":
            # Bars from actuals; no arrows, no Duration seed.
            c["Forecast Start"] = _iso(issue.first_in_progress)
            c["Forecast Finish"] = _iso(issue.done_at)
        elif issue.first_in_progress is not None \
                or issue.status_category == "in_progress":
            # Started: anchor at actual start, drop incoming arrows.
            c["Forecast Start"] = _iso(issue.first_in_progress) \
                or bundle.as_of.isoformat()
            dur, note = _duration(issue)
            c["Duration"] = dur
            if note:
                flags.append(note)
        elif key in preds:
            # Unstarted with an included incoming edge: Duration +
            # Predecessors only. Forecast Start is engine-chained (omit).
            dur, note = _duration(issue)
            c["Duration"] = dur
            c["Predecessors"] = ", ".join(sorted(preds[key]))
            if note:
                flags.append(note)
        else:
            # Root: Forecast Start + Duration.
            c["Forecast Start"] = _root_start(issue, bundle)
            dur, note = _duration(issue)
            c["Duration"] = dur
            if note:
                flags.append(note)
        for ext in external_into.get(key, []):
            flags.append(f"blocked by {ext} (external)")
        for edge in cycle_flag.get(key, []):
            flags.append(f"cycle edge dropped: {edge}")
        for note in epic_flag.get(key, []):
            flags.append(note)
        if flags:
            c["Flags"] = "; ".join(flags)
        cells[key] = c
    return cells


def milestone_rows(bundle: Bundle) -> list[Row]:
    # Synthetic zero-duration diamonds for unreleased fixVersions with a
    # release date. Stable keys (milestone:<version>) so they diff cleanly.
    rows = []
    for fv in sorted(bundle.fix_versions, key=lambda f: f.name):
        if fv.released or fv.release_date is None:
            continue
        # "Key" carries the stable primary so the row round-trips through
        # pull; "Summary" labels the diamond. The only rows in the mirror
        # that do not correspond to a Jira issue.
        rows.append(Row(f"milestone:{fv.name}", {
            "Key": f"milestone:{fv.name}",
            "Summary": f"milestone: {fv.name}",
            "Forecast Start": fv.release_date.isoformat(),
            "Forecast Finish": fv.release_date.isoformat(),
            "Duration": 0,
        }))
    return rows
