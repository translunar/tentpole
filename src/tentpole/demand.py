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
