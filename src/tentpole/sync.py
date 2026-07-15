"""Pure sync orchestration (spec section 8, steps 2-3): bundle + current
sheet state -> specs, change plans, snapshots, report. All I/O stays in
cli.py."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.changeplan import Change, plan_changes
from tentpole.diagnostics import assemble
from tentpole.hygiene import Rule
from tentpole.model import Bundle
from tentpole.runreport import build_report
from tentpole.schema import SCHEMAS
from tentpole.sheets import SheetSpec, build_sheetspecs
from tentpole.snapshots import snapshot_records


@dataclass
class SyncResult:
    diag: dict
    specs: dict[str, SheetSpec]
    plans: dict[str, list[Change]]
    snapshots: list[dict]
    report: dict


def run_sync(bundle: Bundle, rules: list[Rule] | None,
             current: dict[str, dict[str, dict]],
             prior_snapshots: list[dict] | None = None,
             gantt: bool = False) -> SyncResult:
    diag = assemble(bundle, rules=rules, prior_snapshots=prior_snapshots)
    specs = build_sheetspecs(bundle, diag, prior_snapshots, gantt)
    plans = {
        name: plan_changes(spec, current.get(name, {}), SCHEMAS[name],
                           gantt=(gantt and name == "issues"))
        for name, spec in specs.items()
    }
    return SyncResult(
        diag=diag,
        specs=specs,
        plans=plans,
        snapshots=snapshot_records(bundle),
        report=build_report(bundle, diag, plans),
    )
