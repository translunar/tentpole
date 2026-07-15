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


def test_empirical_returns_none_with_no_past_sprints_and_zero_minimum(make_bundle):
    # min_sprints_for_empirical <= 0 means len(past) >= threshold is always
    # true, so with no past sprints per_sprint is empty -- must not crash.
    b = make_bundle(config=Config(min_sprints_for_empirical=0,
                                  team=["ada", "grace"]))
    assert empirical(b, "ada") is None


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


def test_effective_throughput_prior_based_loses_recurring(make_bundle):
    from tentpole.model import Config
    from tentpole.throughput import effective_throughput_for
    # No past sprints -> prior-based. Recurring burden is subtracted.
    b = make_bundle(config=Config(team=["ada"], recurring_days={"ada": 2.0}))
    assert abs(effective_throughput_for(b, "ada")
               - (prior(b.config) - 2.0)) < 1e-9


def test_effective_throughput_empirical_based_keeps_recurring(make_bundle,
                                                              make_sprints):
    from tentpole.model import Config
    from tentpole.throughput import effective_throughput_for
    # THE double-count regression test (spec §4, §11): a person whose
    # throughput is empirical already has the recurring burden baked into
    # the measurement, so it must NOT be subtracted again.
    past = make_sprints(start=date(2026, 5, 1), n=3, first_id=101)
    issues = [_done("T-1", "ada", 6.0, date(2026, 5, 5)),
              _done("T-2", "ada", 4.0, date(2026, 5, 15)),
              _done("T-3", "ada", 5.0, date(2026, 5, 25))]
    b = make_bundle(sprints=past + make_sprints(), issues=issues,
                    config=Config(team=["ada"], recurring_days={"ada": 2.0}))
    assert empirical(b, "ada") == 5.0
    assert effective_throughput_for(b, "ada") == 5.0   # NOT 3.0


def test_effective_throughput_not_clamped(make_bundle):
    from tentpole.model import Config
    from tentpole.throughput import effective_throughput_for
    # Recurring burden > prior -> non-positive, deliberately unclamped.
    b = make_bundle(config=Config(team=["ada"], recurring_days={"ada": 999.0}))
    assert effective_throughput_for(b, "ada") < 0


def test_capacity_for_uses_effective_throughput(make_bundle):
    from tentpole.model import Config
    b = make_bundle(config=Config(team=["ada"], recurring_days={"ada": 2.0}))
    bks = buckets_for(b)
    sprint1 = next(bk for bk in bks if bk.id == "sprint:1")
    # prior-based, recurring 2.0, no overhead/exceptions on the sprint.
    assert abs(capacity_for(b, "ada", sprint1, [])
               - (prior(b.config) - 2.0)) < 1e-9
