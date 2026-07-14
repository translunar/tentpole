# Jira Data Center / Server Extract Adapter + Configurable Plan Length — Design

**Date:** 2026-07-13
**Status:** Proposed
**Owner:** Juno
**Sequencing:** targets release **0.4.0**, planned and executed **after
0.3.0 (roster + token_env_var rename) lands** — both touch
`adapters/config.py`, `checks.py`, and the README, and every config
example below assumes the post-0.3.0 `token_env_var:` key.

## 1. Purpose

Add a second Jira extract adapter targeting **Jira Data Center / Server**
(the current OSS core ships a Cloud-only extract adapter), and make the
"sprints per plan" horizon **configurable** instead of hardcoded. Both are
additive: the pure transform/load core and the existing Cloud adapter are
unchanged except for the config plumbing described here.

Many teams run self-hosted Jira Data Center/Server, whose REST surface
differs from Cloud in auth, search pagination, the epic relationship, and a
couple of endpoint versions. tentpole's adapter seam exists precisely so a
new deployment target is a new adapter, not a core change.

## 2. Scope

- **In:** a `jira_extract_dc` adapter producing the *identical* bundle
  contract the Cloud adapter produces; the config knobs it needs; a
  `sprints_per_plan` core-config field replacing the hardcoded coarse-bucket
  assumptions (dates **and** capacity scale — see §6); tests.
- **Out:** any change to the transform core beyond §6, the load adapter, or
  the Smartsheet data model. (One doc-only note: the load adapter already
  accepts an alternate `base_url`, so non-default Smartsheet regions/clouds
  are already a configuration concern, not a code change.)

## 3. The bundle contract is the invariant

The transform core consumes a plain-data bundle and performs no I/O. The DC
adapter's sole obligation is to emit **the same bundle shape** the Cloud
adapter emits, so the core cannot tell which adapter produced it. That shape
is already established by the Cloud adapter's `parse_issue` output — per
issue: `key, summary, issue_type, status_category (todo|in_progress|done),
assignee, original_estimate_days, remaining_estimate_days, epic_key,
fix_versions[], sprint_id, labels[], links[], program, first_in_progress,
done_at, external` — plus sprints (`id, name, start, end`), fixVersions
(`name, release_date, released`), changelog-derived cycle dates, and hygiene
memberships.

**Reuse, don't fork, the pure helpers.** `_cycle_dates`, `_days`,
`_status_category`, `_sprint_id`, and the external-link stubbing logic are
deployment-independent and must be shared (extract a common module rather
than copy-paste). `parse_issue` is shareable **except its epic-key
extraction**: the Cloud adapter reads the epic key from `fields.parent`,
whereas DC reads it from the configured `epic_link_field` (§4). Parameterize
that one step — resolve `epic_key` in the fetch layer and pass it into a
shared `parse_issue` (or pass the field location), rather than baking
`parent` in. Everything else `parse_issue` does (estimates, links,
fixVersions, sprint id, `program` lookup, cycle dates, statusCategory) is
identical across deployments. Only *fetching* — HTTP shape, auth,
pagination, endpoint paths, and where the epic key comes from — differs.

**The pagination seam is part of the shared boundary.**
`_search_pages` is consumed by `fetch_issues` (twice — scope query and
external-link backfill) **and** `fetch_hygiene`. The shared module must
expose the fetch loops in a way that lets each adapter supply its own
search-pagination primitive, so hygiene JQL evaluation works on DC without a
second fork. Concretely: `fetch_issues` and `fetch_hygiene` logic is shared;
each adapter provides its `search_pages(cfg, jql, fields, expand, http)`
implementation (token cursor on Cloud, offset on DC).

## 4. Data Center deltas from Cloud

| Concern | Cloud (existing) | Data Center / Server (this adapter) |
| --- | --- | --- |
| Auth | `Authorization: Basic base64(email:token)` | `Authorization: Bearer <PAT>` (no email). Implied by `deployment:` (§7) — no separate `auth_scheme` knob. |
| Issue search | `POST /rest/api/3/search/jql`, `nextPageToken` cursor | `POST /rest/api/2/search`, **offset** pagination (`startAt` / `maxResults` / `total`). The Cloud token cursor does not exist here. |
| Epic relationship | `fields.parent.key` | No `parent` for epics; the epic key lives in an **instance-specific custom field**. Add `epic_link_field` config (the custom-field id holding the epic key); the adapter reads `epic_key` from it. |
| Sprint field | custom field id (already `sprint_field` config) | Same config mechanism, **but the value shape can differ** — see the sprint-serialization note below. |
| Project versions | `GET /rest/api/3/project/{k}/versions` | `GET /rest/api/2/project/{k}/versions` |
| Board sprints | `GET /rest/agile/1.0/board/{id}/sprint` | Same (Agile REST 1.0 is available on DC/Server). |
| Status list | `GET /rest/api/3/status` | `GET /rest/api/2/status` (same statusCategory-key mapping; reuse `_status_category`). |

The DC fetch must also add `epic_link_field` to the requested `fields` list
(the Cloud adapter requests `parent`; DC requests the epic custom field
instead), and reuse the existing external/linked-issue stubbing on 403/404.

**Field ids are instance-specific.** Epic-link and sprint custom-field ids
vary between Jira instances; the adapter must treat both as required config
(`epic_link_field`, `sprint_field`) and never hardcode a value. Document
that operators find these via `GET /rest/api/2/field` on their instance.

**Sprint-field serialization on DC can be legacy strings — and
the current helper swallows them silently.** Modern DC returns the sprint
custom field as a list of objects (same as Cloud), but older Server/DC API
versions serialize each entry as a string of the form
`com.atlassian.greenhopper.service.sprint.Sprint@1a2b3c[id=123,rapidViewId=...,name=...]`.
The existing `_sprint_id` returns `None` for any non-dict entry, which on
such an instance means **every issue silently loses its sprint** — the sync
looks healthy while all sprint planning data evaporates. That violates the
project's fail-loud posture ("a silently failing sync must be impossible",
spec §8). Requirement: the shared `_sprint_id` must (a) handle dict entries
as today, (b) parse the legacy string form (extract `id=<int>` via regex),
and (c) raise an actionable `ValueError` naming the offending value for any
other shape — never return `None` for an unrecognized non-empty value.
Empty/absent field still yields `None` (issue genuinely not in a sprint).

## 5. Program classification is already generic — no new mechanism

The Cloud adapter already accepts an opaque `programs: dict[str, str]`
mapping (issue key or epic key → program string) and sets
`program = programs.get(key) or programs.get(epic_key)`; the core treats
`program` as an opaque grouping label. The DC adapter takes the **same**
`programs` argument with the **same** semantics. How an operator computes
that mapping (naming conventions, a lookup table, an external classifier) is
deployment-specific and lives entirely outside tentpole; the adapter just
threads the mapping through. Absent a mapping, `program` is `None` and the
core still functions.

## 6. Configurable plan length (`sprints_per_plan`)

The six-sprint plan assumption is hardcoded in **two** places that must move
together, not one:

1. `checks.py` — the capacity scale:
   `PLAN_SCALE = {"plan+1": 6.0, "plan+2": 6.0}` (sprints of team capacity
   per coarse bucket, used by `team_subscription`).
2. `buckets.py` (`buckets_for`) — the coarse buckets' **date spans**:
   `plan+1` ends `anchor + 60 days` and `plan+2` ends `anchor + 120 days`,
   i.e. 6 × the default 10-day `sprint_length_days`. These spans feed
   `deadline_risk` through `sprint_equivalents_until`, which converts
   coarse-bucket days into sprint equivalents.

Configuring only the capacity scale would make the two checks
disagree: with `sprints_per_plan: 4`, `team_subscription` would price a plan
bucket at 4 sprints of capacity while `deadline_risk` still counted ~6
sprint-equivalents across the unchanged 60-day window.

**Requirement — one derivation.** Add `sprints_per_plan: int = 6` to the
core `Config` dataclass (the one exposed as `bundle.config`). Derive both
consumers from it:

- `buckets_for`:
  `plan_days = round(bundle.config.sprints_per_plan * bundle.config.sprint_length_days)`;
  `p1_end = anchor + plan_days`, `p2_end = anchor + 2 * plan_days`
  (`buckets_for` already receives the bundle, so no signature change).
- `team_subscription`: coarse-bucket capacity =
  `throughput_for(...) * bundle.config.sprints_per_plan` — delete the
  module-level `PLAN_SCALE` constant.

Default `sprints_per_plan = 6` with `sprint_length_days = 10.0` reproduces
today's 60/120-day spans and 6.0 scale exactly, so existing configs and all
existing test fixtures are unaffected. Near-term per-sprint buckets are
already derived from `bundle.sprints` and need no change.

## 7. Config additions (summary)

Adapter config (Jira):

- `deployment: cloud | datacenter` — explicit, no probing (§9 q1 resolved).
  Default `cloud` (backward compatible). `datacenter` implies Bearer-PAT
  auth and the `/rest/api/2` + offset-search surface; `cloud` implies Basic
  auth and the current `/rest/api/3` surface. No separate `auth_scheme`
  knob unless a real instance demands a mismatch (YAGNI).
- `epic_link_field` — required when `deployment: datacenter`; actionable
  error if absent.
- `email` — optional when `deployment: datacenter`; still required for
  `cloud`. Actionable error either way.
- Token stays env-var-indirect via `token_env_var:` (post-0.3.0 name).

Core config: `sprints_per_plan: int = 6`.

## 8. Testing

- **Bundle-shape equivalence:** feed recorded DC REST fixtures (a search
  page, agile sprint page, project versions, status list, a changelog
  expand) through the DC adapter and assert the emitted bundle is
  structurally identical to the Cloud adapter's output for an equivalent
  issue — same keys, same types. This is the load-bearing test.
- **Auth:** header construction for both deployments; datacenter omits
  email and sends `Bearer`.
- **Pagination:** offset paging terminates correctly at
  `startAt + len ≥ total`, no dropped/duplicated pages, including an
  exact-full-final-page boundary.
- **Epic link:** `epic_key` is read from the configured `epic_link_field`;
  missing field → `epic_key = None`.
- **Sprint serialization:** dict form, legacy
  `Sprint@...[id=123,...]` string form (parses to 123), and an
  unrecognized shape (raises actionable ValueError); empty → None.
- **External/linked issues:** 403/404 on linked-but-unreadable projects
  still yields status-unknown stubs (reuse existing behavior); other HTTP
  errors propagate.
- **`sprints_per_plan`:** (a) coarse-bucket *date spans* and
  `team_subscription` capacity both reflect a non-default value (e.g. 4)
  consistently; (b) default of 6 reproduces current bucket boundaries and
  current check numbers exactly (regression guard); (c) a
  `deadline_risk`/`team_subscription` consistency case at the non-default
  value.
- **One live smoke** against a real DC/Server instance before trusting the
  adapter, since recorded fixtures can drift from a live instance's shapes
  (same posture as SmartsheetGov: shape-sensitive code isn't trusted until
  exercised against the real deployment).

## 9. Open questions

1. ~~Cloud vs DC detection~~ — **resolved:** explicit
   `deployment: cloud | datacenter` config key, default `cloud`.
2. **Server vs Data Center nuances:** confirm the `/rest/api/2` +
   `/rest/agile/1.0` surface is identical across the Server and Data Center
   editions in scope, or whether any endpoint needs a version fallback.
   The legacy-sprint-string handling in §4 covers the known shape drift.
3. **Shared-helper module boundary:** exact location/name for the extracted
   common parse/format helpers now shared by both adapters — must include
   the fetch loops per §3's pagination-seam note (implementation detail;
   decide during the plan).
