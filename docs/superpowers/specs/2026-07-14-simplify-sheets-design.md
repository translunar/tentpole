# Simplifying the Smartsheet Surface — Design (0.5.0)

**Date:** 2026-07-14
**Status:** Proposed
**Owner:** Juno

## 1. Purpose

tentpole currently defines nine sheet schemas (six machine-owned, three
human-owned), requires all six machine sheets to be configured, and wires
every sheet by numeric id in `tentpole.yaml`. Setup — not information — is
the burden: nine hand-built sheets and six ids before the first useful sync.

0.5.0 reduces the surface on three fronts:

1. **Sheets resolve by name inside a workspace; existence is the config.**
   A sheet syncs because it exists. Turning a sheet on means creating it.
2. **One human "people" sheet** replaces `team` + `exceptions` and absorbs
   recurring non-Jira burden (ops load, lead overhead), with a yaml-only
   default so no sheet is required at all.
3. **The `epics` sheet folds into `issues`** as rollup columns on the epic
   rows that already exist there.

End state: seven schemas (five machine: issues, fixversions,
dependencies, capacity, accuracy; two human: people, future_work),
minimum viable setup = one workspace id + one `issues` sheet.

This supersedes the earlier mandatory-six decision, which is reversed:
machine sheets are opt-in.

## 2. Sheet selection and name resolution

### Resolution order, per schema name

1. An explicit id in `smartsheet.sheets.<name>` — always wins when present.
2. Otherwise, if `smartsheet.workspace_id` is set: a sheet in that
   workspace whose name equals the schema name exactly (`issues`,
   `capacity`, ...). Discovery uses the workspace listing endpoint
   (`GET /2.0/workspaces/{id}`), one request per run.
3. Otherwise the schema is **OFF** for this run.

`sheets:` becomes fully optional. A config may pin some ids and discover
the rest. If neither `sheets:` nor `workspace_id` is present, every
machine schema is OFF and `push` has nothing to do — which the run report
says out loud (below).

Exact-name matching, no fuzziness. Two sheets in the workspace with the
same schema name is a config error (actionable ValueError naming both
sheet ids).

### Never silent: the run report enumerates everything

Every `push` (and `pull`) run report lists **all** known schemas with
their resolution:

```
issues        SYNCED   sheet 1234  (12 added, 3 updated)
capacity      SYNCED   sheet 5678  (6 updated)
epics         (no such schema — folded into issues in 0.5.0)
fixversions   OFF      no sheet named "fixversions" in workspace 999
...
```

OFF is a normal state, printed every run, exit 0. A renamed or deleted
sheet therefore cannot fail silently — it flips to OFF in the very next
run report. (The pre-0.5.0 behavior — SKIPPED + exit 1 for any
unconfigured machine sheet — is removed.)

### `expect:` — the hard-guarantee opt-in

```yaml
smartsheet:
  workspace_id: 999
  expect: [issues, capacity]
```

Any expected schema that resolves OFF is an `ERROR:` line + exit 1, and
the error lists the sheet names actually present in the workspace so a
rename/typo is diagnosable from the message alone. Teams that want the
old strictness set `expect:` to the full list.

### pull and human sheets

`pull` applies the same resolution to human schemas. An OFF human sheet
falls back exactly as an absent state file does today (people → yaml,
future_work → none). Sheets in the workspace matching **no** schema name
are ignored (people keep dashboards and scratch sheets in the same
workspace); the run report does not enumerate them.

### bootstrap

`bootstrap` gains `--sheets a,b,c` to create a named subset in the
workspace (default remains all known schemas). Still experimental until
smoked on SmartsheetGov.

## 3. The people sheet (replaces `team` and `exceptions`)

Human-owned. Columns: `Item` (TEXT, primary), `Sprint` (NUMBER),
`Days` (NUMBER), `Notes` (TEXT).

```
ada                          ← root row: roster membership
    team lead            2          ← child, Sprint blank: recurring days/sprint
    PTO           3      4          ← child, Sprint set: one-off in that sprint
grace
    ops rotation         2
```

### Semantics

- **Root rows are the roster.** Same contract as the 0.3.0 team sheet:
  present sheet is authoritative (including present-but-empty → empty
  team); absent sheet falls back to yaml. Feeds `team_drift` unchanged.
  Duplicate person names raise (as `team_from_sheet` does today).
- **Child rows are burdens.** `Sprint` blank → recurring, every sprint.
  `Sprint` set → one-off in that sprint (exactly today's `ExceptionRow`:
  person, sprint_id, day_cost — the parent row supplies the person).
  `Days` is fractional-friendly (`0.5` for a half-day ops rotation is
  fine); `Sprint` must be a whole number because it is a sprint id, and
  a fractional value there raises like any other malformed cell.
- **No `(defaults)` group.** Config globals (`annual_vacation_days`,
  `annual_overhead_days`, ...) stay in yaml only. Considered and
  rejected: a second home for org constants creates a precedence puzzle
  for zero information gain. Revisit only on demonstrated need.

### Fail-loud rules (all actionable ValueError naming sheet/row)

- Child row with `Days` blank or non-numeric.
- `Days` on a root row (a person row is a name, not a burden).
- A child whose parent is itself a child (no grandchildren).
- Duplicate root names; duplicate (person, item) child pairs.
- `Sprint` set but not matching any known sprint id is *not* an error at
  parse time (future sprints may not exist yet in the bundle) — but a
  one-off whose sprint never matches any bucket is reported as a yellow
  finding by sync, not dropped.

### yaml default (no sheet needed)

```yaml
core:
  team:
    ada: {}                    # roster only
    grace: {ops rotation: 2}   # recurring days/sprint, by label
```

The 0.1.x list form `team: [ada, grace]` remains accepted (roster-only).
The map form adds recurring burden. One-off exceptions have no yaml form
— they are inherently ephemeral and sheet-native; without a people sheet
there are simply no exceptions, as today with an absent exceptions sheet.

### Model changes

`Config.team: list[str]` is unchanged. New `Config.recurring_days:
dict[str, float]` — person → summed recurring days/sprint (labels are
documentation; the math only needs the sum). `ExceptionRow` and
`bundle.exceptions` are unchanged, now sourced from people-sheet child
rows with `Sprint` set. `SCHEMAS` drops `team` and `exceptions`, gains
`people`.

## 4. Capacity math: the double-count rule

Recurring burden must not be charged twice. `empirical()` measures real
(non-overhead) delivery per sprint — a person carrying 2d/sprint of
untracked ops **already** shows reduced empirical throughput.

**Rule:** recurring burden reduces capacity only while the person's
throughput comes from the prior:

```python
def effective_throughput_for(bundle, person) -> float:
    measured = empirical(bundle, person)
    if measured is not None:
        return measured                      # burden already in the data
    return prior(bundle.config) - bundle.config.recurring_days.get(person, 0.0)
```

`capacity_for` and `team_subscription`'s coarse scaling both build on
`effective_throughput_for`, so sprint capacity and plan-bucket capacity
stay consistent. One-off exceptions always subtract from their specific
sprint bucket regardless of throughput source — history cannot know
about next month's PTO. The result is deliberately not clamped: a
recurring burden that exceeds the prior yields non-positive capacity,
which makes every capacity check fire — loud and correct for a person
who is, by configuration, fully allocated to non-Jira work. This rule gets a spec-level comment in the code;
it will otherwise be "fixed" into double-counting by a future reader.

## 5. Epic/issue merge

`issues_sheet` already emits epic rows with their tickets nested beneath
(`Row(..., parent_key=epic.key)`). The separate `epics` sheet is a flat
rollup of the same entities. Merge:

- `issues` schema gains five columns, populated **only on epic rows**,
  blank on tickets: `Deadline` (DATE), `Open Tickets` (NUMBER),
  `Remaining Days` (NUMBER — rollup of open children; distinct from the
  ticket-level `Remaining Est`, which on an epic row stays the epic's own
  timetracking), `People`, `Runway` ("AT RISK" or blank).
- The `epics` schema, `epics_sheet` builder, and its state file are
  removed. Resolution treats a workspace sheet named `epics` as matching
  no schema; the run report prints a one-line hint for it in 0.5.x
  ("folded into issues in 0.5.0") so upgraders aren't confused.
- Blocks/Blocked By already apply to epic rows (epics are issues); no
  change needed.

**Explicitly deferred, not dropped:** synthetic per-person subtotal rows
under each epic (epic → "ada: 4 tickets, 6.5d" → tickets). Smartsheet's
report builder can group a merged issues sheet by Epic and Assignee
natively; we try that first at work (Gov included). Synthetic rows come
back in 0.6 only if the report path proves inadequate — they carry real
change-plan cost (stable keys for rows that mirror nothing in Jira).

## 6. Prerequisite: pull-state keying

`pull_sheet` keys state by primary-column value, so duplicate primaries
silently collapse — already filed from the 0.3.0 review (future_work:
two ghosts titled "Migrate DB" merge; demand silently understated). The
people sheet makes this load-bearing: ada's "PTO" child and grace's
"PTO" child are the common case, not the edge.

Fix, uniform for all sheets: state key = `f"{parent_primary}|{primary}"`
for rows with a parent, bare primary for roots. After qualification, a
duplicate key raises an actionable ValueError naming the sheet and the
colliding value (this closes the future_work bug: duplicate root titles
now fail loud instead of merging). Machine-sheet primaries are unique by
construction, so change-planning against machine state is unaffected;
`_parent` bookkeeping already exists and is unchanged.

## 7. Sheet inventory after 0.5.0

| Schema | Owner | Status |
| --- | --- | --- |
| issues | machine | the one sheet most setups start with (now carries epic rollups) |
| fixversions | machine | opt-in |
| dependencies | machine | opt-in |
| capacity | machine | opt-in |
| accuracy | machine | opt-in |
| people | human | optional; yaml default covers roster + recurring burden |
| future_work | human | optional |

Seven schemas, zero required ids, minimum setup = `workspace_id` + an
`issues` sheet created from `schema show`.

## 8. Config summary

- `smartsheet.sheets` — now optional; explicit ids override discovery.
- `smartsheet.workspace_id` — enables name resolution (already existed
  for bootstrap).
- `smartsheet.expect` — optional list; OFF-when-expected → exit 1.
- `core.team` — list (roster) or map (roster + recurring days/sprint).
- Removed: mandatory six-sheet requirement; `team`/`exceptions` schemas.

Breaking changes (pre-1.0, acceptable): `team` and `exceptions` sheets
stop being recognized (README migration note: rename/rebuild into a
`people` sheet — the 0.3.0 team sheet shipped one day before this spec);
`epics` sheet retired; push no longer exits 1 on unconfigured sheets
(that role moves to `expect:`).

## 9. Testing

- **Resolution:** explicit id beats discovery; discovery matches exact
  name; ambiguous duplicate names raise; no workspace_id + no sheets →
  all OFF, exit 0; `expect` miss → exit 1 with workspace sheet names in
  the message; run report enumerates every schema every run.
- **People sheet parsing:** roster/recurring/one-off happy path; each
  fail-loud rule in §3 (days-on-root, grandchild, missing days,
  duplicate person, duplicate person+item); present-but-empty sheet →
  empty team (parity with the 0.3.0 semantics test).
- **Capacity math:** prior-based person loses recurring days from sprint
  AND coarse capacity; empirical-based person does not (the
  double-count regression test — the load-bearing one); one-off
  subtracts under both throughput sources; unmatched one-off sprint →
  yellow finding, not silence.
- **Merge:** epic rows carry the five rollups, ticket rows leave them
  blank; values match the retired epics_sheet builder for the same
  bundle (equivalence pin during the transition); reparenting unchanged.
- **Pull keying:** child keys parent-qualified; duplicate qualified keys
  raise; future_work duplicate titles raise (regression for the filed
  bug); machine-sheet pulls byte-identical to today.
- **Live before trust:** workspace discovery and bootstrap --sheets get
  a SmartsheetGov smoke before the README drops the experimental label.

## 10. Decisions log

- Mandatory-six: reversed (Juno, 2026-07-14).
- `(defaults)` group in people sheet: rejected, yaml keeps globals.
- Synthetic per-person epic rows: deferred to 0.6 pending report-builder
  trial at work.
- Recurring burden under empirical throughput: documentation, not a
  deduction (§4 rule).
- Discovery is default; `expect:` is the strictness opt-in.
