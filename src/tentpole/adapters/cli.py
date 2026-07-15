"""Edge-command CLI handlers (extract / pull / push / fix / bootstrap).
The only tentpole commands that do network I/O. The adapter edge may
read the clock (as_of below); the core never does."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from tentpole.adapters import (jira_extract, jira_extract_dc, jira_write,
                               smartsheet_load)
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
    ap = fix_sub.add_parser("apply",
                            help="review and apply fix proposals")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--proposals", required=True, type=Path)

    boot_cmd = sub.add_parser(
        "bootstrap", help="create sheets from schemas (experimental)")
    boot_cmd.add_argument("--config", required=True, type=Path)
    boot_cmd.add_argument(
        "--sheets", default=None,
        help="comma-separated subset to create (default: all known schemas)")


def dispatch(args) -> int | None:
    try:
        return _dispatch(args)
    except ValueError as err:
        # Every edge handler below calls load_config() outside its own
        # try/except -- a stale config (e.g. a 0.2.1 file still using
        # the renamed token_env key) must not surface as a bare
        # traceback (spec section 8: a silently failing sync must be
        # impossible; the same posture applies to a loud one that's
        # unreadable).
        print(f"ERROR: {err}")
        return 1


def _dispatch(args) -> int | None:
    if args.command == "extract":
        return _extract(args)
    if args.command == "pull":
        return _pull(args)
    if args.command == "push":
        return _push(args)
    if args.command == "fix" and args.fix_command == "propose":
        return _fix_propose(args)
    if args.command == "fix" and args.fix_command == "apply":
        return _fix_apply(args)
    if args.command == "bootstrap":
        return _bootstrap(args)
    return None


def _adapter(jira_cfg):
    """Deployment picks the extract adapter. Both emit the same bundle,
    so nothing downstream of here can tell them apart."""
    if jira_cfg.deployment == "datacenter":
        return jira_extract_dc
    return jira_extract


def _extract(args) -> int:
    cfg = load_config(args.config)
    if cfg.jira is None:
        raise SystemExit("config has no jira: section")
    adapter = _adapter(cfg.jira)
    rules = load_rules(args.rules) if args.rules else []
    programs = {}
    if cfg.jira.programs_file:
        programs = json.loads(Path(cfg.jira.programs_file).read_text())
    categories = adapter.fetch_status_categories(cfg.jira)
    issues = adapter.fetch_issues(cfg.jira, categories, programs)
    adapter.write_bundle(
        args.out,
        as_of=date.today().isoformat(),
        issues=issues,
        sprints=adapter.fetch_sprints(cfg.jira),
        versions=adapter.fetch_versions(cfg.jira),
        hygiene=adapter.fetch_hygiene(cfg.jira, rules),
        config=cfg.core or None,
    )
    print(f"bundle written to {args.out}")
    return 0


def _pull(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    try:
        report = smartsheet_load.pull_state(cfg.smartsheet, args.state)
    except ValueError as err:
        # An ambiguous workspace name or an unknown smartsheet.sheets key
        # (spec §2/§8) -- print it and drive a nonzero exit.
        print(f"ERROR: {err}")
        return 1
    for name in sorted(report):
        r = report[name]
        if r["state"] == "SYNCED":
            print(f"{name}: SYNCED sheet {r['sheet_id']}")
        elif r["owned"] == "human":
            fallback = ("roster falls back to yaml" if name == "people"
                        else "treated as absent" if name == "future_work"
                        else "falls back to config")
            print(f"{name}: OFF -- no sheet in workspace; {fallback}")
        else:
            print(f"{name}: OFF -- no sheet in workspace")
    return 0


def _push(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    try:
        report = smartsheet_load.push_plans(cfg.smartsheet, args.plans,
                                            args.state)
    except ValueError as err:
        # A missing column, an ambiguous workspace name, or an unmet
        # expect: -- print it and drive a nonzero exit (spec §8: a
        # silently failing sync must be impossible).
        print(f"ERROR: {err}")
        return 1
    # Upgraders may still have an `epics` sheet in the workspace; it now
    # matches no schema (folded into issues in 0.5.0). Say so once.
    try:
        ws_names = set(smartsheet_load._workspace_sheets(cfg.smartsheet))
    except Exception:
        ws_names = set()
    if "epics" in ws_names:
        print("note: a sheet named 'epics' is in the workspace but no longer "
              "matches a schema -- its rollups folded into issues in 0.5.0")
    failed = 0
    # Enumerate EVERY known schema and its resolution every run (spec §2):
    # a renamed/deleted sheet flips to OFF here, never fails silently.
    for name in sorted(report):
        r = report[name]
        if r["state"] == "OFF":
            print(f"{name}: OFF (no explicit id, no sheet named {name!r} "
                  f"in the workspace)")
            continue
        line = (f"{name}: SYNCED sheet {r['sheet_id']}  "
                f"+{r['added']} ~{r['updated']} -{r['removed']}")
        if r["failed"]:
            line += f"  FAILED {len(r['failed'])}"
        print(line)
        for f in r["failed"]:
            print(f"  {f['op']} {f['key']}: {f['error']}")
        failed += len(r["failed"])
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


def _fix_apply(args) -> int:
    cfg = load_config(args.config)
    if cfg.jira is None:
        raise SystemExit("config has no jira: section")
    proposals = json.loads(Path(args.proposals).read_text())
    applied = skipped = 0
    accept_mechanical = False
    for p in proposals:
        line = (f"{p['issue']}: {p['action']} -> {p['value']} "
                f"[{p['confidence']}] ({p['rationale']})")
        if accept_mechanical and p["confidence"] == "mechanical":
            answer = "y"
        else:
            answer = input(f"{line}  apply? [y/n/all/q] ").strip().lower()
        if answer == "q":
            break
        if answer == "all":
            # Spec section 5: batch accept covers mechanical fixes
            # only; suggested proposals still prompt one by one.
            accept_mechanical = True
            answer = "y" if p["confidence"] == "mechanical" else input(
                f"{line}  apply this one? [y/n] ").strip().lower()
        if answer != "y":
            skipped += 1
            continue
        jira_write.apply_action(cfg.jira, p["action"], p["issue"],
                                p["value"])
        applied += 1
    print(f"applied {applied}, skipped {skipped}")
    return 0


def _bootstrap(args) -> int:
    cfg = load_config(args.config)
    if cfg.smartsheet is None:
        raise SystemExit("config has no smartsheet: section")
    print("WARNING: bootstrap is not integration-tested against "
          "SmartsheetGov; the supported path is manual creation from "
          "`tentpole schema show`.")
    names = ([s.strip() for s in args.sheets.split(",") if s.strip()]
             if args.sheets else None)
    created = smartsheet_load.bootstrap(cfg.smartsheet, names=names)
    print("created sheets -- add to tentpole.yaml:")
    print("smartsheet:")
    print("  sheets:")
    for name in created:
        print(f"    {name}: {created[name]}")
    return 0
