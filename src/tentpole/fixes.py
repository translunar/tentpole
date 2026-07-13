"""Hygiene fix strategies (spec section 5): pure functions over the
bundle emitting structured proposals. Nothing here writes anywhere --
`fix apply` is a separate human-invoked command with its own narrow
Jira-write adapter."""
from __future__ import annotations

from dataclasses import dataclass, replace

from tentpole.hygiene import Rule, evaluate
from tentpole.model import Bundle


@dataclass(frozen=True)
class Proposal:
    issue: str
    action: str          # "set_fix_version" | "set_parent" | "add_link"
    value: str
    rationale: str
    confidence: str      # "mechanical" | "suggested"
    rule: str = ""


def _inherit_epic_fixversion(bundle: Bundle,
                             keys: list[str]) -> list[Proposal]:
    out = []
    for key in keys:
        issue = bundle.issue(key)
        if issue is None or issue.fix_versions:
            continue
        epic = bundle.issue(issue.epic_key)
        if epic and epic.fix_versions:
            version = epic.fix_versions[0]
            out.append(Proposal(
                issue=key, action="set_fix_version", value=version,
                rationale=f"epic {epic.key} carries {version}",
                confidence="mechanical"))
    return out


def _suggest_epic_from_siblings(bundle: Bundle,
                                keys: list[str]) -> list[Proposal]:
    out = []
    for key in keys:
        issue = bundle.issue(key)
        if issue is None or issue.epic_key:
            continue
        counts: dict[str, int] = {}
        for other in bundle.issues:
            if other.key == key or not other.epic_key or other.external:
                continue
            same_program = (issue.program is not None
                            and other.program == issue.program)
            shared_version = bool(
                set(issue.fix_versions) & set(other.fix_versions))
            if same_program or shared_version:
                counts[other.epic_key] = counts.get(other.epic_key,
                                                    0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for epic_key, n in ranked[:3]:
            out.append(Proposal(
                issue=key, action="set_parent", value=epic_key,
                rationale=(f"{n} issue(s) sharing this issue's "
                           f"program or milestone live in {epic_key}"),
                confidence="suggested"))
    return out


STRATEGIES = {
    "inherit_epic_fixversion": _inherit_epic_fixversion,
    "suggest_epic_from_siblings": _suggest_epic_from_siblings,
}


def propose(bundle: Bundle, rules: list[Rule]) -> list[Proposal]:
    out = []
    for rule in rules:
        if rule.fix is None:
            continue
        keys = bundle.hygiene_memberships.get(rule.name)
        if keys is None:
            keys = [f.key for f in evaluate(bundle, [rule])]
        for p in STRATEGIES[rule.fix](bundle, sorted(set(keys))):
            out.append(replace(p, rule=rule.name))
    return out
