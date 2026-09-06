"""Tests for the household (two-person) combination module."""

from dataclasses import replace

import pytest

import household as HH
from projection import PlanInputs, compute_all

SIM = 25  # small Monte Carlo sample keeps the tests fast


def _run(p: PlanInputs) -> dict:
    return compute_all(replace(p, num_sims=SIM))


def test_identical_plans_double_each_column():
    p = PlanInputs(num_sims=SIM)
    res = _run(p)
    single = res["projection"]
    hh = HH.household_projection(single, single)
    # Same horizons -> same number of household years as a single plan.
    assert len(hh) == len(single)
    for hr, sr in zip(hh, single):
        assert hr["year"] == sr["year"]
        assert hr["total"] == 2 * sr["total"]
        assert hr["rrsp"] == 2 * sr["rrsp"]
        assert hr["tfsa"] == 2 * sr["tfsa"]
        assert hr["cpp"] == 2 * sr["cpp"]
        assert hr["tax_paid"] == 2 * sr["tax_paid"]
        assert hr["withdrawal"] == 2 * sr["withdrawal"]


def test_differing_horizons_align_by_calendar_year_and_carry_forward():
    pa = PlanInputs(current_age=60, retirement_age=65, end_age=75, num_sims=SIM)  # 16 years
    pb = PlanInputs(current_age=55, retirement_age=60, end_age=88, num_sims=SIM)  # 34 years
    ra = _run(pa)["projection"]
    rb = _run(pb)["projection"]

    hh = HH.household_projection(ra, rb)
    # Household spans the later of the two end years.
    assert hh[-1]["year"] == rb[-1]["year"]
    assert hh[0]["year"] == ra[0]["year"] == rb[0]["year"]

    # For a shared year where both are alive, totals equal the per-plan sums.
    shared = [r for r in hh if r["age_a"] is not None and r["age_b"] is not None]
    for hr in shared:
        ra_row = next(r for r in ra if r["year"] == hr["year"])
        rb_row = next(r for r in rb if r["year"] == hr["year"])
        assert hr["total"] == pytest.approx(ra_row["total"] + rb_row["total"])
        assert hr["cpp"] == pytest.approx(ra_row["cpp"] + rb_row["cpp"])

    # Final household year is past A's horizon: A's balances are carried
    # forward at constant value while A contributes no income/tax.
    last = hh[-1]
    rb_last = rb[-1]
    ra_last = ra[-1]
    assert last["age_a"] is None            # A is past its modeled end age
    assert last["age_b"] == rb_last["age"]  # B still alive at its own end age
    assert last["rrsp"] == ra_last["rrsp"] + rb_last["rrsp"]  # A held constant
    assert last["cpp"] == rb_last["cpp"]    # A contributes no pension income
    assert last["tax_paid"] == rb_last["tax_paid"]


def test_first_shortfall_year():
    pa = PlanInputs(current_age=60, retirement_age=65, end_age=75, num_sims=SIM)
    pb = PlanInputs(current_age=55, retirement_age=60, end_age=88, num_sims=SIM)
    hh = HH.household_projection(_run(pa)["projection"], _run(pb)["projection"])
    years = [r["year"] for r in hh if r["shortfall"] > 1e-9]
    expected = years[0] if years else None
    assert HH.first_shortfall_year(hh) == expected


def test_total_series_carries_final_balance():
    ra = _run(PlanInputs(current_age=60, retirement_age=65, end_age=75, num_sims=SIM))["projection"]
    years = list(range(ra[0]["year"], ra[0]["year"] + 20))  # past A's horizon
    series = HH.total_series(ra, years)
    assert len(series) == len(years)
    assert series[-1] == ra[-1]["total"]  # carried forward constant


def test_household_montecarlo_sums_identical_plans():
    p = PlanInputs(num_sims=SIM)
    res = _run(p)
    mc = res["montecarlo"]
    hh = HH.household_montecarlo(mc, mc)
    assert hh["years"] == mc["years"]
    for key in ("total_p5", "total_p50", "total_p95"):
        for a, b in zip(hh[key], mc[key]):
            assert a == 2 * b
    # percentiles stay ordered
    assert all(p5 <= p50 <= p95 for p5, p50, p95 in zip(hh["total_p5"], hh["total_p50"], hh["total_p95"]))
