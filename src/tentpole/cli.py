"""CLI. `tentpole check --bundle DIR --me NAME` is the planning-week loop
(spec section 9)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tentpole.diagnostics import assemble, personal, to_json
from tentpole.hygiene import load_rules
from tentpole.model import load_bundle

_SECTION_ORDER = [
    "sprint_overload", "deadline_risk", "tentpole_runway",
    "dependency_readiness", "ghost_claims", "team_subscription",
]


def _render(diag: dict) -> str:
    lines = [f"as of {diag['as_of']}", ""]
    lines.append("capacity:")
    for row in diag["capacity"]:
        marker = "  OVERLOADED" if row["load"] > row["capacity"] else ""
        lines.append(f"  {row['person']:<10} {row['bucket_id']:<10} "
                     f"load {row['load']:5.1f} / cap {row['capacity']:5.1f}"
                     f"{marker}")
    findings = diag["findings"]
    for check in _SECTION_ORDER:
        section = [f for f in findings if f.check == check]
        if section:
            lines.append("")
            lines.append(f"{check}:")
            for f in section:
                lines.append(f"  [{f.severity}] {f.message}")
    if diag["hygiene"]:
        lines.append("")
        lines.append("hygiene:")
        for fl in diag["hygiene"]:
            lines.append(f"  [{fl.severity}] {fl.key}: {fl.message}")
    if not findings and not diag["hygiene"]:
        lines.append("")
        lines.append("all clear.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tentpole")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="planning checks over a bundle")
    check.add_argument("--bundle", required=True, type=Path)
    check.add_argument("--me", default=None,
                       help="filter to one person's slice")
    check.add_argument("--rules", type=Path, default=None,
                       help="hygiene rules YAML")
    check.add_argument("--json", action="store_true",
                       help="emit machine-readable diagnostics")
    args = parser.parse_args(argv)

    bundle = load_bundle(args.bundle)
    rules = load_rules(args.rules) if args.rules else None
    diag = assemble(bundle, rules=rules)
    if args.me:
        diag = personal(diag, bundle, args.me)
    print(to_json(diag) if args.json else _render(diag))
    return 1 if any(f.severity == "red" for f in diag["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
