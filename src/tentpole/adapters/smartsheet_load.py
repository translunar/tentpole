"""Smartsheet adapter: pull current sheet state, push change plans,
bootstrap sheets from schemas (spec sections 3, 7, 8). A dumb executor
-- every decision was made by the core's change planner. Gov note: the
base URL comes from config; anything shape-sensitive here should be
integration-tested against api.smartsheetgov.com before being trusted."""
from __future__ import annotations

import json
from pathlib import Path

from tentpole.adapters.config import SmartsheetConfig
from tentpole.adapters.http import request
from tentpole.schema import SCHEMAS, SheetSchema


def _headers(cfg: SmartsheetConfig) -> dict:
    return {"Authorization": f"Bearer {cfg.token.reveal()}"}


def _call(cfg, method, path, *, params=None, body=None, http=request):
    return http(method, cfg.base_url + path, _headers(cfg),
                params=params, body=body)


def pull_sheet(cfg, sheet_id: int, http=request) -> dict[str, dict]:
    data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
    columns = data.get("columns", [])
    titles = {c["id"]: c["title"] for c in columns}
    primary_id = next(c["id"] for c in columns if c.get("primary"))
    key_by_row_id = {}
    parent_row_ids = {}
    state = {}
    for row in data.get("rows", []):
        cells = {}
        key = None
        for cell in row.get("cells", []):
            value = cell.get("value")
            if cell["columnId"] == primary_id and value is not None:
                key = str(value)
            title = titles.get(cell["columnId"])
            if title is not None and value is not None:
                cells[title] = value
        if key is None:
            continue   # keyless row: nothing the planner can address
        key_by_row_id[row["id"]] = key
        cells["_row_id"] = row["id"]
        parent_row_ids[key] = row.get("parentId")
        state[key] = cells
    for key, cells in state.items():
        cells["_parent"] = key_by_row_id.get(parent_row_ids[key])
    return state


def pull_state(cfg, state_dir: Path, http=request) -> list[str]:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    pulled = []
    for name in sorted(cfg.sheets):
        if name not in SCHEMAS:
            raise ValueError(
                f"unknown sheet {name!r} in config "
                f"(known: {sorted(SCHEMAS)})")
        state = pull_sheet(cfg, cfg.sheets[name], http=http)
        (state_dir / f"{name}.json").write_text(
            json.dumps(state, indent=2))
        pulled.append(name)
    return pulled


def _column_ids(cfg, sheet_id, http=request) -> dict[str, int]:
    data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
    return {c["title"]: c["id"] for c in data.get("columns", [])}


def _cells_payload(cells: dict, col_ids: dict) -> list[dict]:
    return [{"columnId": col_ids[name],
             "value": "" if value is None else value}
            for name, value in cells.items()
            if name in col_ids and not name.startswith("_")]


def _tally(resp, items, counter, result, count=True) -> set[int]:
    failed = set()
    for f in resp.get("failedItems", []):
        failed.add(f["index"])
        result["failed"].append(
            {"op": items[f["index"]]["op"],
             "key": items[f["index"]]["key"],
             "error": f.get("error", {}).get("message", "unknown")})
    if count:
        result[counter] += len(items) - len(failed)
    return failed


def _push_adds(cfg, sheet_id, wave, col_ids, row_ids, result,
               http=request) -> None:
    body, included = [], []
    for c in wave:
        parent = c.get("parent_key")
        if parent and parent not in row_ids:
            # A named parent that never resolved (not the same as "no
            # parent" -- an add with no parent_key legitimately goes to
            # toBottom). Refuse rather than silently landing at root.
            result["failed"].append(
                {"op": c["op"], "key": c["key"],
                 "error": f"add parent {parent!r} not found in "
                          "sheet state"})
            continue
        row = {"cells": _cells_payload(c.get("cells") or {}, col_ids)}
        if parent:
            row["parentId"] = row_ids[parent]
        else:
            row["toBottom"] = True
        body.append(row)
        included.append(c)
    if not included:
        return
    resp = _call(cfg, "POST", f"/sheets/{sheet_id}/rows",
                 params={"allowPartialSuccess": "true"}, body=body,
                 http=http)
    failed = _tally(resp, included, "added", result)
    created = resp.get("result", [])
    if isinstance(created, dict):
        created = [created]
    ok = [c for i, c in enumerate(included) if i not in failed]
    for c, row in zip(ok, created):
        row_ids[c["key"]] = row["id"]


def push_plan(cfg, sheet_id: int, changes: list[dict],
              state: dict[str, dict], schema: SheetSchema,
              http=request) -> dict:
    col_ids = _column_ids(cfg, sheet_id, http=http)
    missing = sorted(set(schema.synced_names()) - set(col_ids))
    if missing:
        # Fail loudly but actionably (same posture as humansheets._number):
        # a column the schema expects is absent from the live sheet, so
        # every cell for it would otherwise be silently dropped from every
        # add/update, the row still tallied as a success, and the sync
        # would never converge (pull can't read back what push never
        # wrote). Refuse rather than degrade quietly.
        raise ValueError(
            f"sheet {schema.name!r} (id {sheet_id}) is missing column(s) "
            f"{missing} required by the {schema.name!r} schema; the live "
            f"sheet only has {sorted(col_ids)}. Recreate the missing "
            f"column(s) exactly as named by `tentpole schema show` before "
            f"pushing.")
    row_ids = {key: cells["_row_id"] for key, cells in state.items()
               if isinstance(cells, dict) and "_row_id" in cells}
    result = {"added": 0, "updated": 0, "removed": 0, "failed": []}

    adds = [c for c in changes if c["op"] == "add"]
    for wave in ([c for c in adds if not c.get("parent_key")],
                 [c for c in adds if c.get("parent_key")]):
        if wave:
            _push_adds(cfg, sheet_id, wave, col_ids, row_ids, result,
                       http=http)

    cell_updates, reparents = [], []
    for c in changes:
        if c["op"] not in ("update", "flag_gone"):
            continue
        if c["key"] not in row_ids:
            result["failed"].append(
                {"op": c["op"], "key": c["key"],
                 "error": "row not found in sheet state"})
            continue
        if c.get("cells"):
            cell_updates.append(c)
        if c["op"] == "update" and c.get("parent_key") is not None:
            reparents.append(c)
    if cell_updates:
        body = [{"id": row_ids[c["key"]],
                 "cells": _cells_payload(c["cells"], col_ids)}
                for c in cell_updates]
        resp = _call(cfg, "PUT", f"/sheets/{sheet_id}/rows",
                     params={"allowPartialSuccess": "true"}, body=body,
                     http=http)
        _tally(resp, cell_updates, "updated", result)
    if reparents:
        # Location changes ride in their own PUT: Smartsheet rejects
        # mixing location and cell updates in one row object.
        body, resolved = [], []
        for c in reparents:
            target = c["parent_key"]
            if target == "":
                body.append({"id": row_ids[c["key"]], "parentId": None})
                resolved.append(c)
            elif target in row_ids:
                body.append({"id": row_ids[c["key"]],
                             "parentId": row_ids[target]})
                resolved.append(c)
            else:
                # A named reparent target that never resolved must NOT
                # fall back to parentId: null (silent move-to-root).
                result["failed"].append(
                    {"op": c["op"], "key": c["key"],
                     "error": f"reparent target {target!r} not found "
                              "in sheet state"})
        if body:
            resp = _call(cfg, "PUT", f"/sheets/{sheet_id}/rows",
                         params={"allowPartialSuccess": "true"},
                         body=body, http=http)
            # Tally failures but do NOT increment "updated" for
            # location-only changes.
            _tally(resp, resolved, "updated", result, count=False)

    removes = [c for c in changes if c["op"] == "remove"]
    found_removes = [c for c in removes if c["key"] in row_ids]
    for c in removes:
        if c["key"] not in row_ids:
            result["failed"].append(
                {"op": c["op"], "key": c["key"],
                 "error": "row not found in sheet state"})
    if found_removes:
        ids = ",".join(str(row_ids[c["key"]]) for c in found_removes)
        resp = _call(cfg, "DELETE", f"/sheets/{sheet_id}/rows",
                     params={"ids": ids, "ignoreRowsNotFound": "true"},
                     http=http)
        # Smartsheet's DELETE response reports the row IDs it actually
        # removed in "result"; ignoreRowsNotFound=true means rows
        # already absent are skipped without error, so the requested
        # count is not the same as what happened. Fall back to the
        # requested set only if the response omits "result" entirely.
        result["removed"] += len(resp.get("result", found_removes))
    return result


def push_plans(cfg, plans_dir: Path, state_dir: Path,
               http=request) -> dict[str, dict]:
    plans_dir, state_dir = Path(plans_dir), Path(state_dir)
    report = {}
    # Iterate the plans `sync` actually produced (one per machine sheet),
    # not cfg.sheets: a machine sheet missing from tentpole.yaml must be
    # reported as skipped, not silently dropped (spec: a silently failing
    # sync must be impossible -- see the README Quickstart, which lists
    # only "issues" and "epics").
    for name, schema in SCHEMAS.items():
        if schema.owned != "machine":
            continue
        plan_path = plans_dir / f"{name}.json"
        if not plan_path.exists():
            continue
        if name not in cfg.sheets:
            report[name] = {
                "added": 0, "updated": 0, "removed": 0,
                "failed": [{
                    "op": "push", "key": name,
                    "error": f"SKIPPED (no sheet id configured for "
                             f"{name!r} in tentpole.yaml)"}]}
            continue
        changes = json.loads(plan_path.read_text())
        state_path = state_dir / f"{name}.json"
        state = (json.loads(state_path.read_text())
                 if state_path.exists() else {})
        report[name] = push_plan(cfg, cfg.sheets[name], changes, state,
                                 schema, http=http)
    return report


_COLUMN_TYPES = {"TEXT": "TEXT_NUMBER", "NUMBER": "TEXT_NUMBER",
                 "DATE": "DATE", "CHECKBOX": "CHECKBOX"}


def bootstrap(cfg, http=request) -> dict[str, int]:
    """Create all sheets from SCHEMAS. Lowest-priority path (spec
    section 7): NOT integration-tested against SmartsheetGov; the
    supported v1 path is manual creation from `tentpole schema show`."""
    path = (f"/workspaces/{cfg.workspace_id}/sheets"
            if cfg.workspace_id else "/sheets")
    created = {}
    for name, schema in SCHEMAS.items():
        columns = []
        for col in schema.columns:
            spec = {"title": col.name,
                    "type": _COLUMN_TYPES[col.type]}
            if col.primary:
                spec["primary"] = True
                spec["type"] = "TEXT_NUMBER"
            columns.append(spec)
        resp = _call(cfg, "POST", path,
                     body={"name": f"tentpole {name}",
                           "columns": columns}, http=http)
        created[name] = resp["result"]["id"]
    return created
