from datetime import date

from tentpole.buckets import buckets_for
from tentpole.demand import DemandItem, compile_demand
from tentpole.model import Config, ExceptionRow, Issue
from tentpole.throughput import capacity_for, empirical, prior, throughput_for


def _done(key, person, est, done_at, **kw):
    return Issue(key=key, summary=kw.pop("summary", "t"), issue_type="Task",
                 status_category="done", assignee=person,
                 original_estimate_days=est, done_at=done_at, **kw)


def test_prior_from_annual_figures():
    cfg = Config(annual_working_days=230.0, annual_vacation_days=24.0,
                 annual_overhead_days=30.0, sprint_length_days=10.0)
    # 10 * (230 - 24 - 30) / 230 = 7.652...
    assert abs(prior(cfg) - 7.652) < 0.01


def test_empirical_needs_min_sprints(make_bundle, make_sprints):
    past = make_sprints(start=date(2026, 5, 1), n=3, first_id=101)
    issues = [
        _done("T-1", "ada", 6.0, date(2026, 5, 5)),    # sprint 101
        _done("T-2", "ada", 4.0, date(2026, 5, 15)),   # sprint 102
        _done("T-3", "ada", 5.0, date(2026, 5, 25)),   # sprint 103
        _done("T-4", "ada", 9.0, date(2026, 5, 6),
              summary="On console", ),                  # overhead: excluded
    ]
    b = make_bundle(sprints=past + make_sprints(), issues=issues)
    assert empirical(b, "ada") == 5.0                   # mean(6, 4, 5)
    assert empirical(b, "grace") == 0.0                 # present, idle
    b_short = make_bundle(
        sprints=make_sprints(start=date(2026, 6, 20), n=2, first_id=101)
        + make_sprints(),
        issues=issues[:1])
    assert empirical(b_short, "ada") is None            # only 2 past sprints


def test_throughput_falls_back_to_prior(make_bundle):
    b = make_bundle()  # no past sprints at all
    assert throughput_for(b, "ada") == prior(b.config)


def test_capacity_subtracts_overhead_and_exceptions(make_bundle):
    oncall = Issue(key="T-2", summary="on call", issue_type="Task",
                   status_category="todo", assignee="ada", sprint_id=1,
                   remaining_estimate_days=2.0)
    b = make_bundle(issues=[oncall],
                    exceptions=[ExceptionRow("ada", 1, 3.0)])
    bks = buckets_for(b)
    demand = compile_demand(b, bks)
    sprint1 = next(bk for bk in bks if bk.id == "sprint:1")
    expected = prior(b.config) - 2.0 - 3.0
    assert abs(capacity_for(b, "ada", sprint1, demand) - expected) < 1e-9
