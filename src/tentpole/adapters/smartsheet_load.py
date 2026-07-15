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


def _workspace_sheets(cfg, http=request) -> dict[str, list[int]]:
    # GET /workspaces/{id} -> {"sheets": [{"id", "name"}, ...]}. Shape is
    # UNVERIFIED against SmartsheetGov; smoke before trusting (spec §2, §11).
    if cfg.workspace_id is None:
        return {}
    data = _call(cfg, "GET", f"/workspaces/{cfg.workspace_id}", http=http)
    out: dict[str, list[int]] = {}
    for sh in data.get("sheets", []):
        out.setdefault(sh["name"], []).append(sh["id"])
    return out


def resolve_sheets(cfg, http=request) -> dict[str, int | None]:
    # Spec §2 resolution order, per schema name: explicit id wins; else a
    # workspace sheet whose name equals the schema name exactly; else OFF.
    # Preserve the unknown-explicit-key guard here (moved out of pull_state)
    # so both push and pull inherit it: a typo'd key under smartsheet.sheets
    # (a sheet id pointing nowhere) must fail loud, not silently do nothing.
    unknown = [name for name in cfg.sheets if name not in SCHEMAS]
    if unknown:
        raise ValueError(
            f"unknown sheet name(s) {sorted(unknown)} under "
            f"smartsheet.sheets (known schemas: {sorted(SCHEMAS)}) -- a "
            f"typo'd explicit id would otherwise resolve to nothing silently")
    ws = _workspace_sheets(cfg, http=http)
    resolved: dict[str, int | None] = {}
    for name in SCHEMAS:
        if name in cfg.sheets:
            resolved[name] = cfg.sheets[name]
            continue
        ids = ws.get(name, [])
        if len(ids) > 1:
            raise ValueError(
                f"workspace {cfg.workspace_id} has {len(ids)} sheets named "
                f"{name!r} (ids {sorted(ids)}); exact-name matching cannot "
                f"choose -- rename all but one, or pin the id under "
                f"smartsheet.sheets.{name}")
        resolved[name] = ids[0] if ids else None
    return resolved


def pull_sheet(cfg, sheet_id: int, http=request, *, sheet_name=None,
               human: bool = False) -> dict[str, dict]:
    data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
    columns = data.get("columns", [])
    titles = {c["id"]: c["title"] for c in columns}
    primary_id = next(c["id"] for c in columns if c.get("primary"))
    primary_by_row_id = {}
    parsed = []                      # (row_id, primary, cells, parent_row_id)
    for row in data.get("rows", []):
        cells = {}
        primary = None
        for cell in row.get("cells", []):
            value = cell.get("value")
            if cell["columnId"] == primary_id and value is not None:
                primary = str(value)
            title = titles.get(cell["columnId"])
            if title is not None and value is not None:
                cells[title] = value
        if primary is None:
            continue   # keyless row: nothing the planner can address
        cells["_row_id"] = row["id"]
        primary_by_row_id[row["id"]] = primary
        parsed.append((row["id"], primary, cells, row.get("parentId")))
    state = {}
    label = sheet_name if sheet_name is not None else sheet_id
    for _row_id, primary, cells, parent_row_id in parsed:
        parent_primary = primary_by_row_id.get(parent_row_id)
        cells["_parent"] = parent_primary
        # Human sheets (people, future_work) can legitimately repeat a
        # primary across parents (ada's "PTO" and grace's "PTO"); qualify
        # their child keys so both survive. Machine sheets keep bare keys
        # (spec §11: byte-identical pulls -- their primaries are unique).
        if human and parent_primary is not None:
            key = f"{parent_primary}|{primary}"
        else:
            key = primary
        if key in state:
            # A duplicate after qualification is always a human error;
            # silent merge understates demand (the future_work bug) or
            # drops a burden. Fail loud (spec §8).
            raise ValueError(
                f"sheet {label!r}: two rows resolve to the same key "
                f"{key!r} -- rename one so each row is unique (a duplicate "
                f"primary would silently merge in pull state)")
        state[key] = cells
    return state


def pull_state(cfg, state_dir: Path, http=request) -> dict[str, dict]:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    resolved = resolve_sheets(cfg, http=http)   # inherits the unknown-key guard
    report: dict[str, dict] = {}
    for name in sorted(SCHEMAS):
        owned = SCHEMAS[name].owned
        sheet_id = resolved.get(name)
        if sheet_id is None:
            # OFF human sheet falls back exactly as an absent state file:
            # people -> yaml, future_work -> none (spec §2). We simply do not
            # write a state file, so cli's _state(name) returns None.
            report[name] = {"state": "OFF", "sheet_id": None, "owned": owned}
            continue
        state = pull_sheet(cfg, sheet_id, http=http, sheet_name=name,
                           human=owned == "human")
        (state_dir / f"{name}.json").write_text(json.dumps(state, indent=2))
        report[name] = {"state": "SYNCED", "sheet_id": sheet_id,
                        "owned": owned}
    return report


def _column_ids(cfg, sheet_id, http=request) -> dict[str, int]:
    data = _call(cfg, "GET", f"/sheets/{sheet_id}", http=http)
    return {c["title"]: c["id"] for c in data.get("columns", [])}


def _validate_columns(schema: SheetSchema, sheet_id: int,
                      col_ids: dict) -> str | None:
    # Fail loudly but actionably (same posture as humansheets._number):
    # a column the schema expects is absent from the live sheet, so
    # every cell for it would otherwise be silently dropped from every
    # add/update, the row still tallied as a success, and the sync
    # would never converge (pull can't read back what push never
    # wrote). Refuse rather than degrade quietly.
    missing = sorted(set(schema.synced_names()) - set(col_ids))
    if not missing:
        return None
    return (f"sheet {schema.name!r} (id {sheet_id}) is missing column(s) "
            f"{missing} required by the {schema.name!r} schema; the live "
            f"sheet only has {sorted(col_ids)}. Recreate the missing "
            f"column(s) exactly as named by `tentpole schema show` before "
            f"pushing.")


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
              http=request, col_ids: dict | None = None) -> dict:
    if col_ids is None:
        col_ids = _column_ids(cfg, sheet_id, http=http)
        problem = _validate_columns(schema, sheet_id, col_ids)
        if problem:
            raise ValueError(problem)
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
    resolved = resolve_sheets(cfg, http=http)

    # Expect (spec §2): any expected schema that resolved OFF is a hard
    # error, and the message names the sheets actually present so a
    # rename/typo is diagnosable from the message alone.
    missing = [name for name in cfg.expect if resolved.get(name) is None]
    if missing:
        present = sorted(_workspace_sheets(cfg, http=http))
        raise ValueError(
            f"expected sheet(s) {missing} did not resolve (no explicit id and "
            f"no exact-name match in workspace {cfg.workspace_id}). Sheets "
            f"present in the workspace: {present or '(none)'}. Fix the name or "
            f"drop it from smartsheet.expect.")

    report: dict[str, dict] = {}
    targets = []
    for name, schema in SCHEMAS.items():
        if schema.owned != "machine":
            continue
        plan_path = plans_dir / f"{name}.json"
        sheet_id = resolved.get(name)
        if sheet_id is None:
            # OFF is a normal state (spec §2): printed every run, exit 0.
            report[name] = {"state": "OFF", "sheet_id": None,
                            "added": 0, "updated": 0, "removed": 0,
                            "failed": []}
            continue
        if not plan_path.exists():
            # Resolved but sync produced no plan (rare); nothing to do.
            report[name] = {"state": "SYNCED", "sheet_id": sheet_id,
                            "added": 0, "updated": 0, "removed": 0,
                            "failed": []}
            continue
        targets.append((name, schema, plan_path, sheet_id))

    # Pre-flight EVERY target sheet's columns before the first write (a
    # mid-loop mismatch would leave earlier sheets written and the report
    # discarded).
    col_ids_by_name = {}
    problems = []
    for name, schema, _plan, sheet_id in targets:
        col_ids = _column_ids(cfg, sheet_id, http=http)
        problem = _validate_columns(schema, sheet_id, col_ids)
        if problem:
            problems.append(problem)
        col_ids_by_name[name] = col_ids
    if problems:
        raise ValueError("\n".join(problems))

    for name, schema, plan_path, sheet_id in targets:
        changes = json.loads(plan_path.read_text())
        state_path = state_dir / f"{name}.json"
        state = (json.loads(state_path.read_text())
                 if state_path.exists() else {})
        r = push_plan(cfg, sheet_id, changes, state, schema, http=http,
                      col_ids=col_ids_by_name[name])
        r["state"] = "SYNCED"
        r["sheet_id"] = sheet_id
        report[name] = r
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
