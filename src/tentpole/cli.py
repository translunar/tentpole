"""CLI. `tentpole check --bundle DIR --me NAME` is the planning-week loop
(spec section 9)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

from tentpole.adapters import cli as edge_cli
from tentpole.diagnostics import assemble, personal, to_json
from tentpole.humansheets import ghosts_from_sheet, people_from_sheet
from tentpole.hygiene import load_rules
from tentpole.model import load_bundle
from tentpole.runreport import render_report
from tentpole.schema import SCHEMAS, render_schemas
from tentpole.snapshots import to_jsonl
from tentpole.sync import run_sync

_SECTION_ORDER = [
    "sprint_overload", "deadline_risk", "tentpole_runway",
    "dependency_readiness", "ghost_claims", "team_subscription",
    "team_drift", "unmatched_exception",
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

    schema_cmd = sub.add_parser("schema", help="sheet schema utilities")
    schema_sub = schema_cmd.add_subparsers(dest="schema_command",
                                           required=True)
    schema_sub.add_parser("show", help="print schemas for manual creation")

    sync_cmd = sub.add_parser("sync", help="bundle + state -> change plans")
    sync_cmd.add_argument("--bundle", required=True, type=Path)
    sync_cmd.add_argument("--state", required=True, type=Path)
    sync_cmd.add_argument("--out", required=True, type=Path)
    sync_cmd.add_argument("--rules", type=Path, default=None)

    edge_cli.add_parsers(sub)

    args = parser.parse_args(argv)

    edge_code = edge_cli.dispatch(args)
    if edge_code is not None:
        return edge_code

    if args.command == "schema":
        print(render_schemas())
        return 0

    if args.command == "sync":
        try:
            bundle = load_bundle(args.bundle)
        except ValueError as err:
            # e.g. a bundle's config.json carries a bad sprints_per_plan
            # -- print it and drive a nonzero exit rather than let a
            # bare traceback be the only signal (spec section 8: a
            # silently failing sync must be impossible), matching the
            # posture already established in adapters/cli.py's dispatch().
            print(f"ERROR: {err}")
            return 1
        rules = load_rules(args.rules) if args.rules else None

        def _state(name: str) -> dict | None:
            # None = state file absent (leave bundle data untouched);
            # {} = state file present but empty (an authoritative "there
            # is nothing here", e.g. a human deleted the last row).
            path = args.state / f"{name}.json"
            return json.loads(path.read_text()) if path.exists() else None

        future_work = _state("future_work")
        if future_work is not None:
            bundle = replace(bundle, ghosts=ghosts_from_sheet(future_work))
        people = _state("people")
        if people is not None:
            # Present is authoritative, including present-but-empty (an empty
            # roster is a deliberate human act, spec §3). Absent falls back
            # to the bundle's core: team: / recurring_days and no exceptions.
            parsed = people_from_sheet(people)
            bundle = replace(
                bundle,
                exceptions=parsed.exceptions,
                config=replace(bundle.config, team=parsed.team,
                               recurring_days=parsed.recurring_days))
        # run_sync expects a dict (never None) per machine sheet, even when
        # its state file is absent.
        current = {name: _state(name) or {}
                   for name, schema in SCHEMAS.items()
                   if schema.owned == "machine"}
        result = run_sync(bundle, rules, current)

        plans_dir = args.out / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        for name, plan in result.plans.items():
            (plans_dir / f"{name}.json").write_text(
                json.dumps([asdict(c) for c in plan], indent=2))
        (args.out / "report.json").write_text(
            json.dumps(result.report, indent=2))
        text = render_report(result.report)
        (args.out / "report.txt").write_text(text + "\n")
        args.state.mkdir(parents=True, exist_ok=True)
        with (args.state / "snapshots.jsonl").open("a") as fh:
            fh.write(to_jsonl(result.snapshots))
        print(text)
        return 0

    try:
        bundle = load_bundle(args.bundle)
    except ValueError as err:
        # Same posture as the sync command above and adapters/cli.py's
        # dispatch(): a bad sprints_per_plan (or other Config error)
        # must not surface as a bare traceback.
        print(f"ERROR: {err}")
        return 1
    rules = load_rules(args.rules) if args.rules else None
    diag = assemble(bundle, rules=rules)
    if args.me:
        diag = personal(diag, bundle, args.me)
    print(to_json(diag) if args.json else _render(diag))
    return 1 if any(f.severity == "red" for f in diag["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
