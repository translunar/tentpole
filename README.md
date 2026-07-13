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

1. Write `tentpole.yaml`:

   ```yaml
   jira:
     base_url: https://yourco.atlassian.net
     email: you@yourco.com
     token_env: JIRA_TOKEN          # token read from this env var
     scope_jql: project = ABC
     projects: [ABC]
     board_id: 42
   smartsheet:
     # Gov deployments: https://api.smartsheetgov.com/2.0
     base_url: https://api.smartsheet.com/2.0
     token_env: SMARTSHEET_TOKEN
     sheets:                        # ids from `tentpole bootstrap`
       issues: 111                  # or created by hand from
       epics: 222                   # `tentpole schema show`
       fixversions: 333             # All six machine-owned sheets must
       dependencies: 444            # be configured; sync produces plans
       capacity: 555                # for each, and push refuses to let
       accuracy: 666                # any plan go nowhere
   core:
     team: [ada, grace]
   ```

2. Create the sheets: print `tentpole schema show` and build them by
   hand (supported path), or try the experimental `tentpole bootstrap
   --config tentpole.yaml`.

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

## Releasing

```sh
python -m build
python -m twine upload dist/*
```

## License

MIT
