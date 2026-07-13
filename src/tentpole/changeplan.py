"""Diff a SheetSpec against current sheet state into an explicit change
plan (spec section 3: the sync never blind-rewrites, never touches
human-owned data; section 8: deletions are soft on the issues sheet)."""
from __future__ import annotations

from dataclasses import dataclass

from tentpole.schema import SheetSchema
from tentpole.sheets import SheetSpec


@dataclass
class Change:
    op: str                        # "add" | "update" | "remove" | "flag_gone"
    key: str
    cells: dict | None = None
    parent_key: str | None = None


def plan_changes(spec: SheetSpec, current: dict[str, dict],
                 schema: SheetSchema) -> list[Change]:
    if schema.owned != "machine":
        raise ValueError(
            f"refusing to plan changes for human-owned sheet "
            f"'{schema.name}'")
    if spec.sheet != schema.name:
        raise ValueError(
            f"spec sheet '{spec.sheet}' does not match schema "
            f"'{schema.name}'")
    synced = set(schema.synced_names())
    changes: list[Change] = []
    spec_keys = set()
    for row in spec.rows:
        spec_keys.add(row.key)
        cells = {c: v for c, v in row.cells.items() if c in synced}
        existing = current.get(row.key)
        if existing is None:
            changes.append(Change("add", row.key, cells, row.parent_key))
            continue
        changed = {c: v for c, v in cells.items() if existing.get(c) != v}
        if changed:
            changes.append(Change("update", row.key, changed))
    for key in sorted(set(current) - spec_keys):
        if schema.name == "issues":
            if current[key].get("In Jira") is not False:
                changes.append(Change("flag_gone", key, {"In Jira": False}))
        else:
            changes.append(Change("remove", key))
    return changes
