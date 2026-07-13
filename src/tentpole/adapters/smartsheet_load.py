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
from tentpole.schema import SCHEMAS


def _headers(cfg: SmartsheetConfig) -> dict:
    return {"Authorization": f"Bearer {cfg.token}"}


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
