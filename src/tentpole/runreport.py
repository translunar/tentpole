"""Run report / Sync Health (spec section 8): a silently failing or
silently weird sync must be impossible."""
from __future__ import annotations

from tentpole.changeplan import Change
from tentpole.model import Bundle


def build_report(bundle: Bundle, diag: dict,
                 plans: dict[str, list[Change]]) -> dict:
    findings: dict[str, int] = {}
    for f in diag["findings"]:
        findings[f.check] = findings.get(f.check, 0) + 1
    changes = {}
    for sheet, plan in plans.items():
        ops: dict[str, int] = {}
        for change in plan:
            ops[change.op] = ops.get(change.op, 0) + 1
        if ops:
            changes[sheet] = ops
    return {
        "as_of": bundle.as_of.isoformat(),
        "issues": sum(1 for i in bundle.issues if not i.external),
        "findings": findings,
        "reds": sum(1 for f in diag["findings"] if f.severity == "red"),
        "yellows": sum(1 for f in diag["findings"]
                       if f.severity == "yellow"),
        "hygiene": len(diag["hygiene"]),
        "ghosts_unknown_jira_key": sorted(
            g.title for g in bundle.ghosts
            if g.jira_key and bundle.issue(g.jira_key) is None),
        "changes": changes,
    }


def render_report(report: dict) -> str:
    lines = [f"SYNC HEALTH — as of {report['as_of']}",
             f"issues: {report['issues']}   reds: {report['reds']}   "
             f"yellows: {report['yellows']}   hygiene: {report['hygiene']}"]
    for check, n in sorted(report["findings"].items()):
        lines.append(f"  {check}: {n}")
    lines.append("changes:")
    if not report["changes"]:
        lines.append("  (none)")
    for sheet, ops in sorted(report["changes"].items()):
        summary = ", ".join(f"{op} {n}" for op, n in sorted(ops.items()))
        lines.append(f"  {sheet}: {summary}")
    if report["ghosts_unknown_jira_key"]:
        lines.append("ghosts with unknown Jira keys: "
                     + ", ".join(report["ghosts_unknown_jira_key"]))
    return "\n".join(lines)
