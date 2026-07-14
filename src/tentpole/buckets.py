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
    # One derivation: the same sprints_per_plan that prices a plan
    # bucket's capacity in checks.team_subscription also sets how many
    # days it spans, so the two can never disagree about the horizon.
    plan_days = round(bundle.config.sprints_per_plan
                      * bundle.config.sprint_length_days)
    p1_start = anchor + timedelta(days=1)
    p1_end = anchor + timedelta(days=plan_days)
    p2_end = anchor + timedelta(days=2 * plan_days)
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
