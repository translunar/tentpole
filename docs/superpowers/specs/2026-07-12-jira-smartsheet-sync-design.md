# Jira → Smartsheet One-Way Sync — Design

**Date:** 2026-07-12
**Status:** Approved pending final review
**Owner:** Juno

## 1. Purpose

A one-way sync and analysis pipeline that mirrors Jira work data into Smartsheet and computes planning intelligence on top of it: per-person capacity vs. demand, milestone deadline risk, long-epic runway, inter-team dependency gaps, and longitudinal estimation-accuracy learning. Jira remains the sole authoring surface for work data; nobody maintains anything in two places.

Intended to be an open-source core with deployment-specific adapters (the work deployment uses internal proprietary Jira/Smartsheet CLIs; the open-source version uses public REST APIs).

## 2. Context and constraints

- **Team practices:** fixVersions represent externally imposed milestones with dates. Epics are small, specific featuresets (used the way others use user stories). Both map to programs via an existing classification capability. An issue may belong to an epic, a fixVersion, both, or neither. The 60-day plan is six 10-day sprints in Jira; tickets (not epics) are placed into sprints during planning week. Tickets carry day-denominated time estimates. Vacation is handled implicitly: people scope less work into sprints where they'll be out.
- **Actuals:** no reliable worklogs. "Actual" effort is approximated from status-transition timestamps (changelog) and, over time, estimate-churn history captured by the sync itself.
- **Dependencies:** Jira issue links (blocks / is-blocked-by) generally exist across teams but have gaps. The remedy for a gap is always adding the link in Jira.
- **Access:** no Jira admin. Read access to relevant projects plus API-token-level auth is assumed. Work runs on **SmartsheetGov** (same API surface, `api.smartsheetgov.com` base URL — adapter configuration, but a reason to integration-test anything API-shape-sensitive like bootstrap before trusting it). Off-the-shelf connectors were researched (2026-07-12) and rejected: Smartsheet's native connector and Workato require a permanently-admin Jira account; none of the options address capacity analysis or estimation learning anyway.
- **Audiences:** Juno (planning), director/leadership (dashboards), org PMO (may impose formats — treated as additional render targets). Team members interact through Jira and a CLI planning check, not by editing Smartsheet.

## 3. Architecture

Three layers with hard boundaries:

```
EXTRACT (adapters)      TRANSFORM (open-source core)         LOAD (adapters)
Jira REST or Jira CLI → pure functions: raw data bundle    → Smartsheet API or SS CLI
                        → SheetSpecs + snapshots + reports
```

- **The core performs no I/O.** Input: a bundle of plain data files — issues (status, assignee, estimates, epic parent, fixVersions, sprint, links, program mapping), sprint definitions with dates, fixVersion definitions with release dates, changelog extracts, prior snapshot history, and the human-authored sheets read back from Smartsheet. Output: **SheetSpecs** (declarative descriptions of target sheet contents), append-only snapshot records, rendered reports, and diagnostics.
- **Adapters are dumb.** Extract adapters fetch and dump. Load adapters execute an explicit change plan. The work-vs-open-source split is exactly the adapter boundary; nothing proprietary touches the core.
- **Change planning lives in the core.** Given a SheetSpec and current sheet state, the core computes an explicit plan: row adds, updates, archive-flags — keyed on Jira issue key, never touching human-owned sheets or columns, never blind-rewriting. The load adapter just executes it.
- **Purity is the extensibility hook.** Because the core takes all inputs as plain data, features like a what-if overlay (compute against hypothetical ticket placements) are cheap later additions, not architectural commitments now (parked; see §10).

## 4. Unified demand model

The core's internal currency is the **demand item**: `{who (person or TBD), how much (estimate-days), when (time bucket), context (epic, fixVersion, program), kind (real | ghost | overhead)}`.

- **Real** items come from Jira tickets.
- **Ghost** items come from the human-authored Future Work sheet (pre-ticket scoped work).
- **Overhead** items (on-call, console, vacation placeholders — recognized by label such as `overhead` or summary pattern where present) deduct from capacity instead of counting as work, and are excluded from throughput/accuracy history.

**Time buckets** coarsen with distance, matching available truth:

- Current plan: sprints 1–6 (from Jira). Person × sprint resolution.
- Beyond: "next plan," "plan after," anchored by fixVersion release dates. Tickets without sprints land here via epic deadline or fixVersion; ghosts via their target-placement column.
- Owner-TBD demand counts against team-level capacity for its bucket, so unstaffed scoped work is visible ("plan N+1 is 140% subscribed before names are assigned").

Partially scoped epics work across the boundary: an epic's demand = its real tickets + ghosts pointing at it via the ghost's intended-epic column.

## 5. Capacity model

- **Empirical per-person throughput:** estimated-days of (non-overhead) work completed per sprint, measured from snapshot history. This inherently prices in code review, anomaly preemptions, on-call drag, and individual estimation dialects ("a Juno day" vs. anyone else's day) — it is the unit-normalization benefit of story points without changing how anyone estimates.
- **Bootstrap prior:** until history accrues, baseline = `10 × (annual working days − vacation days − console/on-call days − anomaly allowance) / annual working days`, from annualized team figures. Measured values replace the prior as sprints complete. Where overhead is explicitly modeled in a sprint (recognized overhead tickets or exception rows), the baseline computation avoids double-counting that drag.
- **Sparse Exceptions sheet (human-owned, optional):** person × sprint rows entered only for known atypical sprints ("on console sprint 3"), applied as adjustments. Empty is the normal state. No team-wide convention is imposed on how people represent on-call/vacation in Jira.

**Checks computed by the core:**

1. **Sprint overload:** per person × sprint, committed estimate vs. personal throughput (prior or empirical).
2. **fixVersion deadline risk:** milestone tickets sitting in sprints that end after the release date; unscheduled milestone tickets.
3. **Tent-pole runway:** for epics with future-bucket deadlines, remaining demand vs. capacity its people have left across intervening buckets after milestone-bound work is served — "finishes 12 days late in plan N+2 at current pace."
4. **Team subscription:** per bucket — total demand (incl. ghosts and TBD) vs. team capacity; program balance.

**Hygiene rules:** a declarative config (rules as data, per-team tunable); no invented query language. Each rule = name, severity (red/yellow), message, and a predicate composed of (a) a **literal JQL string**, evaluated by Jira itself at extract time (the extract adapter runs each rule as a keys-only query scoped to the in-scope set and dumps matching keys into the bundle; the core joins membership → flag), and/or (b) a **named derived check** from a short menu implemented in the core (e.g. `inherits_no_fixversion`) for the few things JQL cannot express, such as epic-field inheritance. Examples: red `fixVersion is EMPTY` + `inherits_no_fixversion` (unanchored work); yellow `issuetype != Bug AND parent is EMPTY` (orphan task). Flags render as an Issues-mirror column (conditional formatting), a `plan check` section, and conversation starters for the parked planning-assistant agent. Anything richer than JQL + named checks becomes core code or an agent judgment.

## 6. Estimation learning

- **Snapshots:** every run appends per-issue records (date, status, sprint, assignee, original/remaining estimate) to the sync's own data store (files persisted by the load adapter — not Smartsheet). This is the longitudinal substrate; Jira retains no estimate time-series, and rolling never-closed tickets are reconstructed from snapshots ("which sprint was it in at each run").
- **Actuals:** cycle time from changelog transitions (first In Progress → Done), later enriched by estimate-churn history.
- **Outputs:** an Estimation Accuracy sheet (one bounded row per closed issue: original estimate, final estimate, cycle time, accuracy ratio, assignee, program, close date) for trends and retros; per-person calibration ratios feeding the CLI nudge ("your estimates on tickets like this run 1.4×").

## 7. Smartsheet data model

**Machine-owned mirrors** (sync rewrites; humans read):

| Sheet | Row unit | Notes |
|---|---|---|
| Issues | issue (key = primary column) | summary, status, assignee, estimates, epic, fixVersions (flat column), sprint, program, links, cycle timestamps, still-in-Jira flag. Epic parent rows with issues indented (one tree per sheet; fixVersion stays flat). |
| Epics | epic | totals, open count, people, deadline (own or inherited), program, runway flag |
| fixVersions | milestone | release date, remaining by person, status counts, deadline-risk flag |
| Dependencies | cross-team link edge | our issue ↔ their issue, direction, their project/team, their status/updated. The gap-discovery surface. |
| Capacity grid | person × bucket | demand, capacity, load %, overload flag |
| Estimation Accuracy | closed issue | see §6 |

**Human-owned sheets** (sync reads, never writes):

| Sheet | Row unit | Notes |
|---|---|---|
| Future Work | pre-ticket item (ghost) | title, program, owner or TBD, rough estimate, target placement (sprint / plan bucket / fixVersion), intended epic, Jira key column — once filled, the ghost is superseded by the real ticket; mismatches flagged by the sync |
| Exceptions | person × sprint | day cost or multiplier for known atypical sprints |

**Provisioning:** sheet schemas are declared once in the core (columns, types, primary column, picklists) and used two ways: the sync validates live sheets against them on every run, and a `bootstrap` command can create the full workspace from them via the Smartsheet API. Bootstrap is **lowest implementation priority** — it needs integration testing against SmartsheetGov before it can be trusted, so the supported v1 path is manual sheet creation from a schema listing the tool prints (`schema show`). Reports and dashboards cannot be created via the API (read/copy only, per current docs — reverify during implementation); they are built by hand once over the precomputed columns, and the API's workspace-copy (which carries reports/dashboards and rewires references) covers any future need to stamp out copies.

Rollups/derived values are **computed by the core, not by Smartsheet cross-sheet formulas** (testable pure functions over fragile formula webs). Smartsheet provides what it is good at: reports, dashboards, conditional formatting, Gantt — over precomputed columns. Sheet limits (20k rows / 500k cells) are respected by scoping mirrors per team and letting Reports roll up if scope ever grows.

## 8. Sync run lifecycle

1. **Extract** — incremental issue pull on `updated` since last run + periodic full pull for reconciliation; sprints, fixVersions, changelogs; read back human sheets.
2. **Transform** — demand items, rollups, capacity, flags, accuracy rows; SheetSpecs + snapshot records + run report.
3. **Plan** — diff SheetSpecs vs. current sheet state → explicit change plan.
4. **Load** — bulk row operations (one bulk call = one request against Smartsheet's 300/min budget; partial-success enabled so one bad row fails alone), serialized per sheet, exponential backoff on 429s.
5. **Report** — run summary to a visible Sync Health surface: counts, flags, failed rows, ghosts with unknown Jira keys, dependency gaps discovered. A silently failing sync must be impossible.

**Failure posture:** failed runs leave sheets consistent-but-stale, never half-written (plans commit sheet-by-sheet; snapshots recorded only after successful extract). Runs are idempotent; the recovery procedure is "run it again." Deletions are soft (still-in-Jira flag) — the sync never destroys information based on an absence it might be misreading.

**Cadence:** scheduled daily minimum (snapshot history accrues at run frequency); on-demand runs any time.

## 9. Surfaces

Every computation renders in up to two places; nothing is computed twice, and nothing exists *only* in the CLI:

| Computation | Smartsheet (shared, persistent) | CLI `plan check --me` (personal, live) |
|---|---|---|
| Sprint load vs. personal throughput | capacity grid (daily cadence) | ✔ core planning-week loop |
| Calibration nudge | — (ratio visible in Accuracy sheet) | ✔ at the moment of estimating |
| fixVersion deadline risk | ✔ dashboard (leadership/PMO) | personal slice |
| Tent-pole runway | ✔ dashboard | personal slice |
| Dependency gaps | ✔ Dependencies sheet (cross-team) | personal slice ("your sprint-2 ticket is blocked by something unscheduled") |
| Ghost claims | ✔ Future Work sheet | personal slice ("ticket it or push it") |
| Team subscription / program balance | ✔ planning meeting + standing view | — |
| Estimation-accuracy trends | ✔ sheet + report | — |

PMO-imposed formats are additional render targets fed from the same core outputs — never allowed to shape the core data model.

## 10. Out of scope / parked

- **Interactive planning UI** (local web what-if cockpit or richer): parked by explicit decision.
- **What-if overlay** (compute against hypothetical placements, e.g. `plan check --me --move KEY:sprint4`): parked. Core purity (§3) makes this a small later addition; no v1 accommodation needed. During planning week, Jira itself serves as the sandbox (move, re-check, move back).
- **Two-way sync of any kind.** Jira is the sole authoring surface for work data, permanently.
- **Google Calendar / payroll integration** for availability: rejected in favor of the empirical throughput model.
- **Planning-assistant agent** (LLM advisor for 60-day planning: semantic dependency-mining from ticket text, decomposition coaching for junior engineers, conversational delivery of core flags): parked, deliberately accommodated. The agent is a *consumer* of the core — it reads the data bundle + computed diagnostics and produces advisory suggestions that humans apply in Jira; it never writes to Jira/Smartsheet itself. Near-term implementation can be a Claude Code skill pointed at the tool's data directory (same mechanism as the existing program-classification skills). Design accommodations (both wanted anyway): diagnostics emitted as stable machine-readable JSON alongside rendered output, and the data-bundle format documented as a public interface.
- **Unito trial:** available as 30-minute due diligence but not on the critical path.
- **Smartsheet Data Shuttle:** noted as a possible simplification of the work deployment's load path (CSV import, no Jira admin) if org licensing covers it; does not affect core design because the CSV boundary already exists at the adapter seam.

## 11. Open questions

1. ~~Implementation language~~ **Decided: Python** (easiest for colleagues to read and extend).
2. **Jira Cloud vs. Data Center at work** — the internal CLI insulates the work deployment; the open-source extract adapter should target Cloud first (`/rest/api/3/search/jql` with token pagination; epic relationship via `parent`, since Epic Link is retired on Cloud).
3. **Scope query** — the precise JQL defining "in-scope issues" (team project + externally linked issues reachable from dependency edges), and read access to other teams' projects for dependency status.
4. **Snapshot store format** — flat files vs. SQLite for the history the load adapter persists (decision belongs to implementation planning).
5. **Program mapping input format** — how the existing classification capability's output is fed to the core.
