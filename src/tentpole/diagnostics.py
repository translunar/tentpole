"""Assemble all checks into one machine-readable diagnostics bundle
(spec sections 5 and 10: JSON diagnostics are a public interface)."""
from __future__ import annotations

import dataclasses
import json

from tentpole.buckets import buckets_for
from tentpole.checks import (
    deadline_risk, dependency_readiness, ghost_claims, sprint_overload,
    team_subscription, tentpole_runway,
)
from tentpole.demand import compile_demand
from tentpole.hygiene import Rule, evaluate
from tentpole.model import Bundle
from tentpole.throughput import capacity_for


def assemble(bundle: Bundle, rules: list[Rule] | None = None) -> dict:
    buckets = buckets_for(bundle)
    demand = compile_demand(bundle, buckets)
    findings = (
        sprint_overload(bundle, buckets, demand)
        + team_subscription(bundle, buckets, demand)
        + deadline_risk(bundle, buckets)
        + tentpole_runway(bundle, buckets, demand)
        + dependency_readiness(bundle, buckets)
        + ghost_claims(bundle, buckets)
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
    def _owner(key: str) -> str | None:
        issue = bundle.issue(key)
        return issue.assignee if issue else None

    return {
        "as_of": diag["as_of"],
        "findings": [f for f in diag["findings"] if f.subject == person],
        "hygiene": [fl for fl in diag["hygiene"] if _owner(fl.key) == person],
        "capacity": [r for r in diag["capacity"] if r["person"] == person],
        "demand": [d for d in diag["demand"] if d.who == person],
    }


def to_json(diag: dict) -> str:
    def _default(obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        return str(obj)  # dates -> ISO

    return json.dumps(diag, default=_default, indent=2)
