"""Deterministic planning checks (spec section 5). All checks return Findings."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.buckets import (
    Bucket, bucket_for_issue, effective_deadline, sprint_equivalents_until,
)
from tentpole.demand import DemandItem
from tentpole.model import Bundle
from tentpole.throughput import capacity_for, effective_throughput_for


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str          # "red" | "yellow"
    subject: str           # person, epic key, fixVersion name, or "team"
    bucket_id: str | None
    message: str
    epic_key: str | None = None   # set by carryover so reports group by epic


def _load(demand: list[DemandItem], bucket_id: str,
          who: str | None = ...) -> float:
    return sum(d.estimate_days for d in demand
               if d.bucket_id == bucket_id and d.kind in ("real", "ghost")
               and (who is ... or d.who == who))


def sprint_overload(bundle: Bundle, buckets: list[Bucket],
                    demand: list[DemandItem]) -> list[Finding]:
    findings = []
    for bucket in buckets:
        if not bucket.id.startswith("sprint:"):
            continue
        for person in bundle.config.team:
            load = _load(demand, bucket.id, person)
            cap = capacity_for(bundle, person, bucket, demand)
            if load > cap:
                findings.append(Finding(
                    "sprint_overload", "red", person, bucket.id,
                    f"{person}: {load:.1f}d planned vs {cap:.1f}d capacity "
                    f"in {bucket.id}"))
    return findings


def team_subscription(bundle: Bundle, buckets: list[Bucket],
                      demand: list[DemandItem]) -> list[Finding]:
    findings = []
    for bucket in buckets:
        if bucket.id in ("beyond", "unscheduled"):
            continue
        total = _load(demand, bucket.id)
        if bucket.id.startswith("sprint:"):
            cap = sum(capacity_for(bundle, p, bucket, demand)
                      for p in bundle.config.team)
        else:
            cap = sum(effective_throughput_for(bundle, p)
                      * bundle.config.sprints_per_plan
                      for p in bundle.config.team)
        if total > cap:
            pct = f" ({total / cap:.0%} subscribed)" if cap > 0 else ""
            findings.append(Finding(
                "team_subscription", "red", "team", bucket.id,
                f"{bucket.id}: {total:.1f}d demand vs {cap:.1f}d team "
                f"capacity{pct}"))
    return findings


def deadline_risk(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    findings = []
    by_bucket_end = {bk.id: bk.end for bk in buckets}
    for fv in bundle.fix_versions:
        if fv.released:
            continue
        late, unscheduled = [], []
        for issue in bundle.issues:
            if (fv.name not in issue.fix_versions
                    or issue.status_category == "done"
                    or issue.issue_type == "Epic" or issue.external):
                continue
            bucket_id = bucket_for_issue(issue, bundle, buckets)
            end = by_bucket_end.get(bucket_id)
            if end is None:
                unscheduled.append(issue.key)
            elif fv.release_date and end > fv.release_date:
                late.append(issue.key)
        if late:
            findings.append(Finding(
                "deadline_risk", "red", fv.name, None,
                f"{fv.name}: scheduled past the {fv.release_date} deadline: "
                f"{', '.join(sorted(late))}"))
        if unscheduled:
            findings.append(Finding(
                "deadline_risk", "red", fv.name, None,
                f"{fv.name}: milestone work unscheduled: "
                f"{', '.join(sorted(unscheduled))}"))
    return findings


def tentpole_runway(bundle: Bundle, buckets: list[Bucket],
                    demand: list[DemandItem]) -> list[Finding]:
    findings = []
    ended = {bk.id: bk.end for bk in buckets}
    for epic in bundle.issues:
        if epic.issue_type != "Epic" or epic.status_category == "done":
            continue
        deadline = effective_deadline(epic, bundle)
        if deadline is None:
            continue
        epic_items = [d for d in demand if d.epic_key == epic.key
                      and d.kind in ("real", "ghost")]
        remaining = sum(d.estimate_days for d in epic_items)
        if remaining == 0:
            continue
        people = sorted({d.who for d in epic_items if d.who}) or list(
            bundle.config.team)
        runway = sprint_equivalents_until(
            deadline, buckets, bundle.config.sprint_length_days)
        total_slack = 0.0
        for person in people:
            cap = effective_throughput_for(bundle, person) * runway
            committed = sum(
                d.estimate_days for d in demand
                if d.who == person and d.epic_key != epic.key
                and d.kind in ("real", "ghost")
                and ended.get(d.bucket_id) is not None
                and ended[d.bucket_id] <= deadline)
            total_slack += max(0.0, cap - committed)
        if remaining > total_slack:
            findings.append(Finding(
                "tentpole_runway", "red", epic.key, None,
                f"{epic.key} ({epic.summary}): {remaining:.1f}d remaining but "
                f"only {total_slack:.1f}d of capacity before {deadline} — "
                f"~{remaining - total_slack:.0f}d short"))
    return findings


def dependency_readiness(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    findings = []
    sprints_by_id = {f"sprint:{s.id}": s for s in bundle.sprints}
    for issue in bundle.issues:
        if issue.status_category == "done" or issue.external:
            continue
        my_bucket = bucket_for_issue(issue, bundle, buckets)
        if not my_bucket.startswith("sprint:"):
            continue
        my_start = sprints_by_id[my_bucket].start
        subject = issue.assignee or "unassigned"
        for link in issue.links:
            if link.type != "Blocks" or link.direction != "inward":
                continue
            other = bundle.issue(link.other_key)
            if other is None:
                findings.append(Finding(
                    "dependency_readiness", "yellow", subject, my_bucket,
                    f"{issue.key} is blocked by {link.other_key}, "
                    f"which is not in data"))
                continue
            if other.status_category == "done":
                continue
            other_bucket = bucket_for_issue(other, bundle, buckets)
            if not other_bucket.startswith("sprint:"):
                findings.append(Finding(
                    "dependency_readiness", "red", subject, my_bucket,
                    f"{issue.key} is blocked by {other.key}, which is open "
                    f"and unscheduled"))
            elif sprints_by_id[other_bucket].end > my_start:
                findings.append(Finding(
                    "dependency_readiness", "red", subject, my_bucket,
                    f"{issue.key} starts {my_bucket} but its blocker "
                    f"{other.key} finishes {other_bucket}"))
    return findings


def ghost_claims(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    findings = []
    sprint_ids = {bk.id for bk in buckets if bk.id.startswith("sprint:")}
    for ghost in bundle.ghosts:
        if ghost.jira_key or ghost.target not in sprint_ids:
            continue
        findings.append(Finding(
            "ghost_claims", "yellow", ghost.owner or "TBD", ghost.target,
            f"'{ghost.title}' ({ghost.estimate_days:.1f}d) is targeted at "
            f"{ghost.target} but has no Jira ticket — ticket it or push it"))
    return findings


def team_drift(bundle: Bundle, buckets: list[Bucket],
               demand: list[DemandItem]) -> list[Finding]:
    findings = []
    sprint_ids = {bk.id for bk in buckets if bk.id.startswith("sprint:")}
    real_days: dict[str, float] = {}
    for d in demand:
        if d.who and d.bucket_id in sprint_ids and d.kind == "real":
            real_days[d.who] = real_days.get(d.who, 0.0) + d.estimate_days
    present = set(real_days) | {
        d.who for d in demand
        if d.who and d.bucket_id in sprint_ids and d.kind in ("ghost", "overhead")}
    team = set(bundle.config.team)
    for person in sorted(set(real_days) - team):
        findings.append(Finding(
            "team_drift", "yellow", person, None,
            f"{person} has {real_days[person]:.1f}d of sprint work but is "
            f"not in team — roster drift or a display-name mismatch"))
    if present:   # an empty plan (pre-planning week) should not flag anyone
        for person in sorted(team - present):
            findings.append(Finding(
                "team_drift", "yellow", person, None,
                f"{person} is in team but has no work in the current plan"))
    return findings


def unmatched_exception(bundle: Bundle, buckets: list[Bucket]) -> list[Finding]:
    # Spec §3: a one-off burden whose Sprint matches no known sprint is not
    # a parse-time error (future sprints may not exist in the bundle yet),
    # but it must never be silently dropped -- report it so the human fixes
    # the Sprint cell or accepts the burden is ignored.
    sprint_ids = {s.id for s in bundle.sprints}
    findings = []
    for e in bundle.exceptions:
        if e.sprint_id not in sprint_ids:
            findings.append(Finding(
                "unmatched_exception", "yellow", e.person, None,
                f"{e.person}: one-off burden of {e.day_cost:.1f}d targets "
                f"sprint {e.sprint_id}, which is not in the current plan -- "
                f"fix the Sprint cell on the people sheet or the burden is "
                f"ignored"))
    return findings


def carryover(bundle: Bundle, prior_snapshots: list[dict] | None) -> list[Finding]:
    # Spec §7: compare the two most recent snapshot runs (the most recent
    # prior run vs the current bundle). A ticket sprint-planned then, still
    # not done, and sprint-planned again now is a yellow carryover. First
    # run ever (no prior) -> nothing. Ticket-level (sprints hold tickets);
    # the epic-level rollup is parked for 0.6.
    if not prior_snapshots:
        return []
    latest_run = max(r["run"] for r in prior_snapshots)
    was_planned = {
        r["key"]: r for r in prior_snapshots
        if r["run"] == latest_run and r.get("sprint_id") is not None}
    findings = []
    for issue in bundle.issues:
        if issue.external or issue.issue_type == "Epic":
            continue
        if issue.status_category == "done" or issue.sprint_id is None:
            continue
        prev = was_planned.get(issue.key)
        if prev is None:
            continue
        prev_rem = prev.get("remaining")
        prev_txt = f"{prev_rem:.1f}d" if isinstance(prev_rem, (int, float)) \
            else "?"
        cur_rem = issue.remaining_estimate_days
        cur_txt = f"{cur_rem:.1f}d" if isinstance(cur_rem, (int, float)) \
            else "?"
        findings.append(Finding(
            "carryover", "yellow", issue.assignee or "unassigned", None,
            f"{issue.key}: second consecutive plan; {prev_txt} -> {cur_txt} "
            f"remaining", epic_key=issue.epic_key))
    return findings
