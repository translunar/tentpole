from datetime import date

from tentpole.gantt import gantt_cells, milestone_rows
from tentpole.model import FixVersion, Issue, Link


def _t(key, **kw):
    base = dict(summary="t", issue_type="Task", status_category="todo")
    base.update(kw)
    return Issue(key=key, **base)


def test_seed_root_gets_start_and_duration(make_bundle):
    # A todo ticket with no incoming arrow: Forecast Start (today = as_of,
    # no future sprint) + Duration; no Predecessors.
    b = make_bundle(issues=[_t("T-1", remaining_estimate_days=3.0)])
    cells = gantt_cells(b)["T-1"]
    assert cells["Forecast Start"] == "2026-07-12"   # bundle.as_of
    assert cells["Duration"] == 3.0
    assert "Predecessors" not in cells                # root has none


def test_seed_root_future_sprint_starts_at_sprint_window(make_bundle):
    # Sprint 2 starts 2026-07-23 (make_sprints default), which is after
    # as_of -> Forecast Start is the sprint window start.
    b = make_bundle(issues=[_t("T-1", remaining_estimate_days=2.0,
                               sprint_id=2)])
    assert gantt_cells(b)["T-1"]["Forecast Start"] == "2026-07-23"


def test_seed_unstarted_with_incoming_edge_gets_duration_and_predecessors(
        make_bundle):
    # B-1 blocks T-1 (T-1 inward). T-1 is unstarted -> Duration +
    # Predecessors=[B-1], and NO Forecast Start (engine chains it =
    # write-never).
    b = make_bundle(issues=[
        _t("B-1", remaining_estimate_days=2.0),
        _t("T-1", remaining_estimate_days=3.0,
           links=[Link("Blocks", "inward", "B-1")])])
    cells = gantt_cells(b)["T-1"]
    assert cells["Predecessors"] == "B-1"
    assert cells["Duration"] == 3.0
    assert "Forecast Start" not in cells


def test_seed_started_anchors_at_actual_start_drops_arrows(make_bundle):
    b = make_bundle(issues=[
        _t("B-1", remaining_estimate_days=2.0),
        _t("T-1", status_category="in_progress",
           first_in_progress=date(2026, 7, 5), remaining_estimate_days=3.0,
           links=[Link("Blocks", "inward", "B-1")])])
    cells = gantt_cells(b)["T-1"]
    assert cells["Forecast Start"] == "2026-07-05"    # actual start
    assert cells["Duration"] == 3.0
    assert "Predecessors" not in cells                # reality retires arrows


def test_seed_done_bars_from_actuals_no_arrows(make_bundle):
    b = make_bundle(issues=[
        _t("T-1", status_category="done",
           first_in_progress=date(2026, 6, 1), done_at=date(2026, 6, 8))])
    cells = gantt_cells(b)["T-1"]
    assert cells["Forecast Start"] == "2026-06-01"
    assert cells["Forecast Finish"] == "2026-06-08"
    assert "Predecessors" not in cells


def test_seed_missing_estimate_defaults_and_flags(make_bundle):
    b = make_bundle(issues=[_t("T-1")])   # no estimate
    cells = gantt_cells(b)["T-1"]
    assert cells["Duration"] == 1.0
    assert "no estimate" in cells["Flags"]


def test_external_edge_renders_as_flag_not_arrow(make_bundle):
    b = make_bundle(issues=[
        _t("T-1", remaining_estimate_days=3.0,
           links=[Link("Blocks", "inward", "OTHER-9")])])   # OTHER-9 not in scope
    cells = gantt_cells(b)["T-1"]
    assert "Predecessors" not in cells
    assert "OTHER-9" in cells["Flags"] and "external" in cells["Flags"]


def test_cycle_dropped_edge_named_in_flags(make_bundle):
    b = make_bundle(issues=[
        _t("A", remaining_estimate_days=1.0,
           links=[Link("Blocks", "outward", "B")]),
        _t("B", remaining_estimate_days=1.0,
           links=[Link("Blocks", "outward", "A")]),
    ])
    cells = gantt_cells(b)
    # (B, A) is the highest-sorted edge -> dropped; both A and B name it.
    flags = cells["A"]["Flags"] + cells["B"]["Flags"]
    assert "B" in flags and "A" in flags and "cycle" in flags.lower()


def test_epic_rows_have_no_gantt_cells(make_bundle):
    epic = Issue(key="E-1", summary="e", issue_type="Epic",
                 status_category="in_progress")
    b = make_bundle(issues=[epic, _t("T-1", epic_key="E-1",
                                     remaining_estimate_days=2.0)])
    assert gantt_cells(b)["E-1"] == {}    # engine rolls epics up (write-never)


def test_epic_blocks_link_renders_as_flag_not_arrow(make_bundle):
    # Spec §6: epic-level blocks links render in Flags, not arrows. An epic
    # E-1 blocking a ticket T-1 flags the non-epic endpoint (T-1) and draws
    # no Predecessors arrow; an epic-to-epic link flags both epic rows.
    e1 = Issue(key="E-1", summary="e", issue_type="Epic",
               status_category="in_progress",
               links=[Link("Blocks", "outward", "T-1"),
                      Link("Blocks", "outward", "E-2")])
    e2 = Issue(key="E-2", summary="e2", issue_type="Epic",
               status_category="todo")
    b = make_bundle(issues=[e1, e2,
                            _t("T-1", remaining_estimate_days=2.0)])
    cells = gantt_cells(b)
    assert "Predecessors" not in cells["T-1"]           # no arrow
    assert "E-1 -> T-1" in cells["T-1"]["Flags"]         # flagged on ticket
    assert "E-1 -> E-2" in cells["E-1"]["Flags"]         # both epics flagged
    assert "E-1 -> E-2" in cells["E-2"]["Flags"]


def test_milestone_rows_for_unreleased_versions(make_bundle):
    b = make_bundle(fix_versions=[
        FixVersion("v1", release_date=date(2026, 9, 1)),
        FixVersion("v2", release_date=date(2026, 9, 1), released=True),
        FixVersion("v3", release_date=None)])
    rows = milestone_rows(b)
    keys = {r.key for r in rows}
    assert keys == {"milestone:v1"}      # released and dateless excluded
    m = rows[0].cells
    assert m["Forecast Start"] == "2026-09-01"
    assert m["Forecast Finish"] == "2026-09-01"
    assert m["Duration"] == 0
