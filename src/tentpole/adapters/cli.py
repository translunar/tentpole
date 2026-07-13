"""Edge-command CLI handlers (extract / pull / push / fix / bootstrap).
The only tentpole commands that do network I/O. The adapter edge may
read the clock (as_of below); the core never does."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from tentpole.adapters import jira_extract, smartsheet_load
from tentpole.adapters.config import load_config
from tentpole.fixes import propose
from tentpole.hygiene import load_rules
from tentpole.model import load_bundle


def add_parsers(sub) -> None:
    extract_cmd = sub.add_parser("extract", help="Jira -> bundle dir")
    extract_cmd.add_argument("--config", required=True, type=Path)
    extract_cmd.add_argument("--out", required=True, type=Path)
    extract_cmd.add_argument("--rules", type=Path, default=None)

    pull_cmd = sub.add_parser("pull", help="Smartsheet -> state dir")
    pull_cmd.add_argument("--config", required=True, type=Path)
    pull_cmd.add_argument("--state", required=True, type=Path)

    push_cmd = sub.add_parser(
        "push", help="apply change plans to Smartsheet")
    push_cmd.add_argument("--config", required=True, type=Path)
    push_cmd.add_argument("--plans", required=True, type=Path)
    push_cmd.add_argument("--state", required=True, type=Path)

    fix_cmd = sub.add_parser("fix", help="hygiene fix proposals")
    fix_sub = fix_cmd.add_subparsers(dest="fix_command", required=True)
    prop = fix_sub.add_parser("propose",
                              help="emit structured fix proposals")
    prop.add_argument("--bundle", required=True, type=Path)
    prop.add_argument("--rules", required=True, type=Path)
    prop.add_argument("--out", type=Path, default=None)
    prop.add_argument("--json", action="store_true")


def dispatch(args) -> int | None:
    if args.command == "extract":
        return _extract(args)
    if args.command == "pull":
        return _pull(args)
    if args.command == "push":
        return _push(args)
    if args.command == "fix" and args.fix_command == "propose":
        return _fix_propose(args)
    return None


def _extract(args) -> int:
    cfg = load_config(args.config)
    if cfg.jira is None:
        raise SystemExit("config has no jira: section")
    rules = load_rules(args.rules) if args.rules else []
    programs = {}
    if cfg.jira.programs_file:
        programs = json.loads(Path(cfg.jira.programs_file).read_text())
    categories = jira_extract.fetch_status_categories(cfg.jira)
    issues = jira_extract.fetch_issues(cfg.jira, categories, programs)
    jira_extract.write_bundle(
        args.out,
        as_of=date.today().isoformat(),
        issues=issues,
        sprints=jira_extract.fetch_sprints(cfg.jira),
        versions=jira_extract.fetch_versions(cfg.jira),
        hygiene=jira_extract.fetch_hygiene(cfg.jira, rules),
        config=cfg.core or None,
    )
    print(f"bundle written to {args.out}")
    return 0


def _pull(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    pulled = smartsheet_load.pull_state(cfg.smartsheet, args.state)
    print(f"pulled {len(pulled)} sheet(s): {', '.join(pulled)}")
    return 0


def _push(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    report = smartsheet_load.push_plans(cfg.smartsheet, args.plans,
                                        args.state)
    failed = 0
    for name in sorted(report):
        r = report[name]
        line = (f"{name}: +{r['added']} ~{r['updated']} "
                f"-{r['removed']}")
        if r["failed"]:
            line += f"  FAILED {len(r['failed'])}"
        print(line)
        for f in r["failed"]:
            print(f"  {f['op']} {f['key']}: {f['error']}")
        failed += len(r["failed"])
    # Spec section 8: a silently failing sync must be impossible.
    return 1 if failed else 0


def _fix_propose(args) -> int:
    bundle = load_bundle(args.bundle)
    rules = load_rules(args.rules)
    proposals = propose(bundle, rules)
    payload = [asdict(p) for p in proposals]
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2))
    if args.json:
        print(json.dumps(payload, indent=2))
    elif not proposals:
        print("no fix proposals.")
    else:
        for p in proposals:
            print(f"[{p.confidence}] {p.issue}: {p.action} -> "
                  f"{p.value}  ({p.rationale}; rule {p.rule})")
    return 0
