"""Append-only snapshot records (spec section 6): the longitudinal substrate
for estimation learning. Stored as JSONL by the CLI; this module only
builds/serializes records (pure)."""
from __future__ import annotations

import json

from tentpole.model import Bundle


def snapshot_records(bundle: Bundle) -> list[dict]:
    return [
        {
            "run": bundle.as_of.isoformat(),
            "key": issue.key,
            "status": issue.status_category,
            "sprint_id": issue.sprint_id,
            "assignee": issue.assignee,
            "original": issue.original_estimate_days,
            "remaining": issue.remaining_estimate_days,
            "epic_key": issue.epic_key,
            "program": issue.program,
        }
        for issue in bundle.issues
        if not issue.external and issue.issue_type != "Epic"
    ]


def to_jsonl(records: list[dict]) -> str:
    if not records:
        return ""
    return "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n"


def parse_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]
