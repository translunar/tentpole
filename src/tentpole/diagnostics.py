"""Assemble all checks into one machine-readable diagnostics bundle
(spec sections 5 and 10: JSON diagnostics are a public interface)."""
from __future__ import annotations

import dataclasses
import json

from tentpole.buckets import buckets_for
from tentpole.checks import (
    carryover, deadline_risk, dependency_readiness, ghost_claims,
    link_hygiene, sprint_overload, team_drift, team_subscription,
    tentpole_runway, unmatched_exception,
)
from tentpole.demand import compile_demand
from tentpole.hygiene import Rule, evaluate
from tentpole.model import Bundle
from tentpole.throughput import capacity_for


def assemble(bundle: Bundle, rules: list[Rule] | None = None,
             prior_snapshots: list[dict] | None = None) -> dict:
    buckets = buckets_for(bundle)
    demand = compile_demand(bundle, buckets)
    findings = (
        sprint_overload(bundle, buckets, demand)
        + team_subscription(bundle, buckets, demand)
        + deadline_risk(bundle, buckets)
        + tentpole_runway(bundle, buckets, demand)
        + dependency_readiness(bundle, buckets)
        + ghost_claims(bundle, buckets)
        + team_drift(bundle, buckets, demand)
        + unmatched_exception(bundle, buckets)
        + carryover(bundle, prior_snapshots)
        + link_hygiene(bundle)
    )
    capacity = [
        {"person": person, "bucket_id": bucket.id,
         "load": sum(d.estimate_days for d in demand
                     if d.who == person and d.bucket_id == bucket.id
                     and d.kind in ("real", "ghost")),
         "capacity": capacity_for(bundle, person, bucket, demand)}
        for bucket in buckets if bucket.id.startswith("sprint:")
        for person in bundle.config.team
    ]
    return {
        "as_of": bundle.as_of,
        "findings": findings,
        "hygiene": evaluate(bundle, rules) if rules else [],
        "capacity": capacity,
        "demand": demand,
    }


def personal(diag: dict, bundle: Bundle, person: str) -> dict:
    my_demand = [d for d in diag["demand"] if d.who == person]
    my_fix_versions = {fv for d in my_demand for fv in d.fix_versions}
    my_epics = {d.epic_key for d in my_demand if d.epic_key}

    def _mine(f) -> bool:
        if f.subject == person:
            return True
        if f.check == "deadline_risk":
            return f.subject in my_fix_versions
        if f.check == "tentpole_runway":
            return f.subject in my_epics
        return False

    def _owner(key: str) -> str | None:
        issue = bundle.issue(key)
        return issue.assignee if issue else None

    return {
        "as_of": diag["as_of"],
        "findings": [f for f in diag["findings"] if _mine(f)],
        "hygiene": [fl for fl in diag["hygiene"] if _owner(fl.key) == person],
        "capacity": [r for r in diag["capacity"] if r["person"] == person],
        "demand": my_demand,
    }


def to_json(diag: dict) -> str:
    def _default(obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        return str(obj)  # dates -> ISO

    return json.dumps(diag, default=_default, indent=2)
