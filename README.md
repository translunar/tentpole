# tentpole

One-way Jira → Smartsheet planning transformer. Jira stays the sole
authoring surface; tentpole mirrors work data into Smartsheet and
computes the planning intelligence on top: per-person capacity vs.
demand, milestone deadline risk, long-epic ("tent-pole") runway,
cross-team dependency gaps, hygiene flags, and longitudinal
estimation-accuracy learning.

## Design

Three layers with hard boundaries:

- **Extract** (`tentpole extract`, `tentpole pull`): Jira Cloud REST →
  a plain-data bundle directory; Smartsheet → current sheet state.
- **Transform** (`tentpole sync`): a pure core — no I/O, no clock —
  turns bundle + state into explicit per-sheet change plans, snapshot
  records, and a sync-health report.
- **Load** (`tentpole push`): executes the change plans with bulk row
  operations, partial-success handling, and 429 backoff.

The sync never writes to Jira. The only Jira writes are the
human-invoked `tentpole fix apply` walk over structured hygiene fix
proposals, restricted to a hard allowlist (set fixVersion, set parent,
add link — never transitions, never deletes).

## Install

```sh
pip install tentpole
```

## Quickstart

> **Upgrading from 0.4.x.** The `team` and `exceptions` sheets are no
> longer recognized — rename/rebuild them into one `people` sheet (roster
> as root rows, exceptions as child rows with `Sprint` set). `push` no
> longer exits 1 on an unconfigured machine sheet; that strictness now
> lives in `expect:`. See "The people sheet" below.

1. Write `tentpole.yaml`:

   ```yaml
   jira:
     deployment: cloud              # cloud (default) | datacenter
     base_url: https://yourco.atlassian.net
     email: you@yourco.com
     token_env_var: JIRA_TOKEN      # NAME of the env var holding the
                                    # token; the token itself never
                                    # lives in this file
     scope_jql: project = ABC
     projects: [ABC]
     board_id: 42
   smartsheet:
     # Gov deployments: https://api.smartsheetgov.com/2.0
     base_url: https://api.smartsheet.com/2.0
     token_env_var: SMARTSHEET_TOKEN
     workspace_id: 999             # enables discovery: a sheet syncs
                                   # because it exists, named for its schema
     sheets:                       # optional; an explicit id always wins
       issues: 111                 # over discovery. Pin only what you must.
     expect: [issues]              # optional strictness: any expected schema
                                   # that resolves OFF is an error + exit 1
   core:
     team:                         # list form = roster only, OR map form:
       ada: {}                     #   roster + recurring non-Jira burden
       grace: {ops rotation: 2}    #   (days/sprint; labels are documentation)
     sprints_per_plan: 6           # how many sprints a plan+N bucket spans
                                   # AND is priced at (default 6)
   ```

2. Create at least an `issues` sheet: print `tentpole schema show` and
   build it by hand in your workspace (supported path), or try the
   experimental `tentpole bootstrap --config tentpole.yaml` (optionally
   `--sheets issues,capacity` for a subset). Minimum viable setup is one
   `workspace_id` plus one `issues` sheet — every other machine sheet is
   opt-in and simply OFF until it exists.

   **Sheets resolve by name.** For each schema (`issues`, `capacity`,
   `fixversions`, `dependencies`, `accuracy`, `people`, `future_work`),
   tentpole uses the explicit id under `smartsheet.sheets` if present,
   otherwise a sheet in `workspace_id` whose name matches the schema name
   exactly, otherwise the schema is OFF. Every `push` and `pull` prints one
   line per schema — SYNCED or OFF — so a renamed or deleted sheet flips to
   OFF in the very next run instead of failing silently. `expect:` turns an
   unwanted OFF into a hard error. Two sheets sharing a schema name is a
   config error naming both ids.

   **Smoke discovery before you trust it.** Workspace listing and
   `bootstrap --sheets` are shape-sensitive against the live API. Run one
   real `tentpole pull` (or `bootstrap`) against your instance and confirm
   the resolution lines before wiring into a scheduled sync.

3. Write `rules/hygiene.yaml` (required for `tentpole fix propose`;
   optional for `tentpole extract` and `tentpole sync`):

   ```yaml
   # Team hygiene rules (spec section 5). `jql` is evaluated by Jira at extract
   # time; the extract adapter stores matching keys under the rule's name in the
   # bundle's hygiene.json. `derived` names a built-in check from
   # tentpole.hygiene.DERIVED_CHECKS; when both are present they AND together.
   # `fix` names a proposal strategy from tentpole.fixes.STRATEGIES.
   hygiene:
     - name: unanchored-work
       severity: red
       jql: "fixVersion is EMPTY"
       derived: inherits_no_fixversion
       message: "No milestone attached (directly or via epic)"
       fix: inherit_epic_fixversion
     - name: orphan-task
       severity: yellow
       jql: 'issuetype != Bug AND parent is EMPTY'
       message: "Task belongs to no epic"
       fix: suggest_epic_from_siblings
   ```

4. Run the loop (daily or on demand):

   ```sh
   tentpole extract --config tentpole.yaml --out bundle/ --rules rules/hygiene.yaml
   tentpole pull    --config tentpole.yaml --state state/
   tentpole sync    --bundle bundle/ --state state/ --out out/ --rules rules/hygiene.yaml
   tentpole push    --config tentpole.yaml --plans out/plans --state state/
   ```

5. Personal planning check, any time:

   ```sh
   tentpole check --bundle bundle/ --me ada
   ```

6. Hygiene fixes (human-reviewed; the only path that writes to Jira):

   ```sh
   tentpole fix propose --bundle bundle/ --rules rules/hygiene.yaml --out proposals.json
   tentpole fix apply --config tentpole.yaml --proposals proposals.json
   ```

### The people sheet

The roster and recurring non-Jira burden live in one human-owned `people`
sheet (it replaces the 0.4.x `team` and `exceptions` sheets). It is
optional: without it, `core: team:` in `tentpole.yaml` is the roster and
the map form supplies recurring burden.

Rows are hierarchical:

- **Root rows are the roster** — one row per person; `Item` must match the
  Jira display name exactly. A present sheet is authoritative (including
  present-but-empty → empty team); an absent sheet falls back to
  `core: team:`. `team_drift` flags mismatches in both directions.
- **Child rows are burdens.** `Sprint` blank → recurring, every sprint
  (fed into capacity). `Sprint` set → a one-off in that sprint. `Days` is
  fractional-friendly (`0.5` for a half-day rotation); `Sprint` must be a
  whole sprint id.

Columns: `Item` (primary), `Sprint`, `Days`, `Notes`. Fail-loud rules
(each an actionable error naming the sheet and row): `Days` on a person
row, a burden nested under a burden (no grandchildren), a child with no
`Days`, a fractional `Sprint`, and duplicate person or duplicate
(person, item) rows. A one-off whose sprint is not in the current plan is
reported as a yellow `unmatched_exception` finding, never silently dropped.

**Capacity and recurring burden are never double-counted.** Recurring
burden reduces a person's capacity only while their throughput comes from
the prior; once there is enough history for an empirical throughput, the
burden is already baked into the measurement (spec §4). A recurring burden
larger than the prior yields non-positive capacity on purpose — it fires
every capacity check for someone fully allocated to non-Jira work.

Keep `core: team:` in `tentpole.yaml` even once the people sheet exists:
`tentpole check` reads only the bundle and has no access to sheet state
(only `sync` reads state), so removing `core: team:` makes `check` treat
the roster as empty.

## Jira Data Center / Server

Self-hosted Jira speaks a different REST dialect than Cloud. Set
`deployment: datacenter` and tentpole switches adapters: Bearer personal
access token instead of Basic `email:token`, `/rest/api/2` instead of
`/rest/api/3`, `startAt`/`maxResults` offset paging instead of Cloud's
`nextPageToken` cursor, and the epic key from a custom field instead of
`parent`. The bundle it produces is identical, so everything downstream —
`sync`, `check`, `push` — is unchanged. `tentpole fix apply` writes back to
Data Center too: it uses the same `/rest/api/2` surface, and the epic-link
fix writes the epic key into your `epic_link_field` rather than `parent`.

```yaml
jira:
  deployment: datacenter
  base_url: https://jira.internal.yourco.com
  # email is not needed: Data Center authenticates with a Bearer PAT
  token_env_var: JIRA_PAT
  epic_link_field: customfield_10014   # required on datacenter
  sprint_field: customfield_10104      # required on datacenter too
  scope_jql: project = ABC
  projects: [ABC]
  board_id: 42
```

**Custom-field ids are instance-specific.** `epic_link_field` (the Epic
Link) and `sprint_field` differ between Jira instances and must never be
guessed, so both are **required when `deployment: datacenter`** and
tentpole refuses to start without them: leaving `sprint_field` unset
would silently inherit Cloud's `customfield_10020`, and since Jira
ignores unknown field ids instead of rejecting them, every issue's
`sprint_id` would come back null with no error at all. Find your
instance's ids with:

```sh
curl -H "Authorization: Bearer $JIRA_PAT" \
     https://jira.internal.yourco.com/rest/api/2/field
```

and look for the fields named "Epic Link" and "Sprint".

**Smoke it before you trust it.** Recorded fixtures can drift from a live
instance's shapes. Run one real `tentpole extract` against your instance and
eyeball `bundle/issues.json` — every issue should carry the `epic_key` and
`sprint_id` you expect — before wiring the adapter into a scheduled sync.

This goes double for writes: `fix apply` prompts per proposal, so apply a
single low-stakes `set_parent` fix by hand first and confirm in the Jira UI
that the epic link actually moved. A wrong `epic_link_field` writes to the
wrong custom field, and unlike a bad read, that one is visible to your team.

## Releasing

Releases are published to PyPI by CI (trusted publishing — no tokens).
Tag a version and push the tag; `.github/workflows/publish.yml` runs the
test suite, builds, and uploads:

```sh
git tag v0.2.1
git push origin v0.2.1
```

Do not `twine upload` by hand — the tag's CI job would then fail on
PyPI's "file already exists".

## License

MIT
