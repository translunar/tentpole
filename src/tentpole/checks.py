"""Deterministic planning checks (spec section 5). All checks return Findings."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.buckets import Bucket
from tentpole.demand import DemandItem
from tentpole.model import Bundle
from tentpole.throughput import capacity_for, throughput_for

PLAN_SCALE = {"plan+1": 6.0, "plan+2": 6.0}  # sprints per coarse bucket


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str          # "red" | "yellow"
    subject: str           # person, epic key, fixVersion name, or "team"
    bucket_id: str | None
    message: str


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
            cap = sum(throughput_for(bundle, p) * PLAN_SCALE[bucket.id]
                      for p in bundle.config.team)
        if total > cap:
            findings.append(Finding(
                "team_subscription", "red", "team", bucket.id,
                f"{bucket.id}: {total:.1f}d demand vs {cap:.1f}d team "
                f"capacity ({total / cap:.0%} subscribed)"))
    return findings
