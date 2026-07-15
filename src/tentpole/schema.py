"""Declarative sheet schemas (spec section 7). One source of truth for
sheet shape: change planning validates against these; `schema show`
renders them for manual sheet creation; Plan 3's bootstrap will create
sheets from them."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str = "TEXT"      # TEXT | NUMBER | DATE | CHECKBOX
    primary: bool = False
    synced: bool = True     # False = human-owned; the sync never writes it
    gantt: bool = False     # gantt-mode-only column (spec §6)


@dataclass(frozen=True)
class SheetSchema:
    name: str
    owned: str              # "machine" | "human"
    columns: tuple[ColumnDef, ...]

    def primary_column(self) -> ColumnDef:
        return next(c for c in self.columns if c.primary)

    def synced_names(self, gantt: bool = False) -> list[str]:
        return [c.name for c in self.columns
                if c.synced and (gantt or not c.gantt)]

    def column_names(self, gantt: bool = False) -> list[str]:
        return [c.name for c in self.columns if gantt or not c.gantt]


def _human(name: str, *cols: ColumnDef) -> SheetSchema:
    unsynced = tuple(
        ColumnDef(c.name, c.type, c.primary, synced=False) for c in cols)
    return SheetSchema(name, "human", unsynced)


GANTT_COLUMNS = ("Forecast Start", "Forecast Finish", "Duration",
                 "Predecessors", "Flags")


SCHEMAS: dict[str, SheetSchema] = {
    "issues": SheetSchema("issues", "machine", (
        ColumnDef("Key", primary=True),
        ColumnDef("Summary"), ColumnDef("Type"), ColumnDef("Status"),
        ColumnDef("Assignee"),
        ColumnDef("Original Est", "NUMBER"),
        ColumnDef("Remaining Est", "NUMBER"),
        ColumnDef("Epic"), ColumnDef("Fix Versions"), ColumnDef("Sprint"),
        ColumnDef("Program"), ColumnDef("Blocked By"), ColumnDef("Blocks"),
        ColumnDef("Hygiene"),
        ColumnDef("Deadline", "DATE"),
        ColumnDef("Open Tickets", "NUMBER"),
        ColumnDef("Remaining Days", "NUMBER"),
        ColumnDef("People"), ColumnDef("Runway"),
        ColumnDef("First Planned", "DATE"),
        ColumnDef("Forecast Start", "DATE", gantt=True),
        ColumnDef("Forecast Finish", "DATE", gantt=True),
        ColumnDef("Duration", "NUMBER", gantt=True),
        ColumnDef("Predecessors", gantt=True),
        ColumnDef("Flags", gantt=True),
        ColumnDef("In Progress", "DATE"), ColumnDef("Done", "DATE"),
        ColumnDef("In Jira", "CHECKBOX"),
    )),
    "fixversions": SheetSchema("fixversions", "machine", (
        ColumnDef("Version", primary=True),
        ColumnDef("Release Date", "DATE"),
        ColumnDef("Released", "CHECKBOX"),
        ColumnDef("Open Tickets", "NUMBER"),
        ColumnDef("Remaining Days", "NUMBER"),
        ColumnDef("Remaining By Person"), ColumnDef("Risk"),
    )),
    "dependencies": SheetSchema("dependencies", "machine", (
        ColumnDef("Edge", primary=True),
        ColumnDef("Our Issue"), ColumnDef("Direction"),
        ColumnDef("Their Issue"), ColumnDef("Their Status"),
        ColumnDef("Their Sprint"),
    )),
    "capacity": SheetSchema("capacity", "machine", (
        ColumnDef("Cell", primary=True),
        ColumnDef("Person"), ColumnDef("Bucket"),
        ColumnDef("Load", "NUMBER"), ColumnDef("Capacity", "NUMBER"),
        ColumnDef("Overloaded", "CHECKBOX"),
    )),
    "accuracy": SheetSchema("accuracy", "machine", (
        ColumnDef("Key", primary=True),
        ColumnDef("Assignee"), ColumnDef("Program"),
        ColumnDef("Original Est", "NUMBER"),
        ColumnDef("Cycle Days", "NUMBER"), ColumnDef("Ratio", "NUMBER"),
        ColumnDef("Done", "DATE"),
    )),
    "future_work": _human(
        "future_work",
        ColumnDef("Title", primary=True),
        ColumnDef("Program"), ColumnDef("Owner"),
        ColumnDef("Estimate Days", "NUMBER"),
        ColumnDef("Target"), ColumnDef("Intended Epic"),
        ColumnDef("Jira Key"),
    ),
    "people": _human(
        "people",
        ColumnDef("Item", primary=True),
        ColumnDef("Sprint", "NUMBER"),
        ColumnDef("Days", "NUMBER"),
        ColumnDef("Notes"),
    ),
}


def render_schemas() -> str:
    lines = ["tentpole sheet schemas", "======================", ""]
    for schema in SCHEMAS.values():
        lines.append(f"{schema.name}  ({schema.owned}-owned)")
        for col in schema.columns:
            marks = []
            if col.primary:
                marks.append("primary")
            if not col.synced:
                marks.append("human-edited")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            lines.append(f"  - {col.name}: {col.type}{suffix}")
        lines.append("")
    return "\n".join(lines)
