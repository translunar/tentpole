"""Per-person throughput: empirical when history exists, prior until then
(spec section 5)."""
from __future__ import annotations

from tentpole.buckets import Bucket
from tentpole.demand import DemandItem, is_overhead
from tentpole.model import Bundle, Config


def prior(config: Config) -> float:
    available = (config.annual_working_days - config.annual_vacation_days
                 - config.annual_overhead_days)
    return config.sprint_length_days * available / config.annual_working_days


def empirical(bundle: Bundle, person: str) -> float | None:
    past = [s for s in bundle.sprints if s.end < bundle.as_of]
    if len(past) < bundle.config.min_sprints_for_empirical:
        return None
    per_sprint = []
    for sprint in past:
        total = sum(
            (issue.original_estimate_days or 0.0)
            for issue in bundle.issues
            if issue.assignee == person
            and issue.done_at is not None
            and sprint.start <= issue.done_at <= sprint.end
            and issue.issue_type != "Epic"
            and not is_overhead(issue, bundle.config)
        )
        per_sprint.append(total)
    if not per_sprint:
        return None
    return sum(per_sprint) / len(per_sprint)


def throughput_for(bundle: Bundle, person: str) -> float:
    measured = empirical(bundle, person)
    return measured if measured is not None else prior(bundle.config)


def effective_throughput_for(bundle: Bundle, person: str) -> float:
    # Spec §4 (the double-count rule -- do NOT "simplify" this into always
    # subtracting recurring_days; that reintroduces the bug). empirical()
    # measures real delivery, so a person carrying recurring ops ALREADY
    # shows reduced empirical throughput. Recurring burden therefore
    # reduces capacity only while throughput comes from the prior. The
    # result is deliberately not clamped: a burden exceeding the prior
    # yields non-positive capacity, firing every capacity check -- correct
    # for someone fully allocated to non-Jira work.
    measured = empirical(bundle, person)
    if measured is not None:
        return measured
    return prior(bundle.config) - bundle.config.recurring_days.get(person, 0.0)


def capacity_for(bundle: Bundle, person: str, bucket: Bucket,
                 demand: list[DemandItem]) -> float:
    cap = effective_throughput_for(bundle, person)
    cap -= sum(d.estimate_days for d in demand
               if d.kind == "overhead" and d.who == person
               and d.bucket_id == bucket.id)
    if bucket.id.startswith("sprint:"):
        sprint_id = int(bucket.id.split(":", 1)[1])
        cap -= sum(e.day_cost for e in bundle.exceptions
                   if e.person == person and e.sprint_id == sprint_id)
    return cap
