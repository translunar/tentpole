"""Hygiene rules: literal JQL (evaluated at extract time) + named derived
checks (spec section 5). No invented query language."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from tentpole.model import Bundle, Issue


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    message: str
    jql: str | None = None
    derived: str | None = None


@dataclass(frozen=True)
class Flag:
    rule: str
    severity: str
    key: str
    message: str


def _inherits_no_fixversion(issue: Issue, bundle: Bundle) -> bool:
    if issue.fix_versions:
        return False
    epic = bundle.issue(issue.epic_key)
    return not (epic and epic.fix_versions)


DERIVED_CHECKS: dict[str, Callable[[Issue, Bundle], bool]] = {
    "inherits_no_fixversion": _inherits_no_fixversion,
}


VALID_SEVERITIES = {"red", "yellow"}


def load_rules(path: Path) -> list[Rule]:
    raw = yaml.safe_load(Path(path).read_text())
    rules = [Rule(**entry) for entry in raw["hygiene"]]
    for rule in rules:
        if rule.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"hygiene rule {rule.name!r}: severity {rule.severity!r} "
                f"is not one of {sorted(VALID_SEVERITIES)}")
        if rule.derived is not None and rule.derived not in DERIVED_CHECKS:
            raise ValueError(
                f"hygiene rule {rule.name!r}: unknown derived check "
                f"{rule.derived!r} (known: {sorted(DERIVED_CHECKS)})")
        if rule.jql is None and rule.derived is None:
            raise ValueError(
                f"hygiene rule {rule.name!r}: must set jql, derived, or "
                f"both — a rule with neither would match every in-scope "
                f"issue")
    return rules


def evaluate(bundle: Bundle, rules: list[Rule]) -> list[Flag]:
    flags = []
    for rule in rules:
        membership = set(bundle.hygiene_memberships.get(rule.name, []))
        check = DERIVED_CHECKS[rule.derived] if rule.derived else None
        for issue in bundle.issues:
            if issue.status_category == "done" or issue.external:
                continue
            if rule.jql is not None and issue.key not in membership:
                continue
            if check is not None and not check(issue, bundle):
                continue
            flags.append(Flag(rule=rule.name, severity=rule.severity,
                              key=issue.key, message=rule.message))
    return flags
