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
    # On "add": the parent row's key (hierarchy placement).
    # On "update": None = leave parent alone; "" = move to top level;
    # "KEY" = move under KEY. Only emitted when the current state
    # tracks parents (a "_parent" key from `tentpole pull`).
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
        new_parent = None
        if "_parent" in existing:
            current_parent = existing["_parent"] or None
            if row.parent_key != current_parent:
                new_parent = row.parent_key or ""
        if changed or new_parent is not None:
            changes.append(Change("update", row.key, changed, new_parent))
    for key in sorted(set(current) - spec_keys):
        if schema.name == "issues":
            if current[key].get("In Jira") is not False:
                changes.append(Change("flag_gone", key, {"In Jira": False}))
        else:
            changes.append(Change("remove", key))
    return changes
