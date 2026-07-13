"""Edge-command CLI handlers (extract / pull / push / fix / bootstrap).
The only tentpole commands that do network I/O. The adapter edge may
read the clock (as_of below); the core never does."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tentpole.adapters import jira_extract, smartsheet_load
from tentpole.adapters.config import load_config
from tentpole.hygiene import load_rules


def add_parsers(sub) -> None:
    extract_cmd = sub.add_parser("extract", help="Jira -> bundle dir")
    extract_cmd.add_argument("--config", required=True, type=Path)
    extract_cmd.add_argument("--out", required=True, type=Path)
    extract_cmd.add_argument("--rules", type=Path, default=None)

    pull_cmd = sub.add_parser("pull", help="Smartsheet -> state dir")
    pull_cmd.add_argument("--config", required=True, type=Path)
    pull_cmd.add_argument("--state", required=True, type=Path)


def dispatch(args) -> int | None:
    if args.command == "extract":
        return _extract(args)
    if args.command == "pull":
        return _pull(args)
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
