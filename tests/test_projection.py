"""Tests for the deterministic projection model, Monte Carlo and validation."""

import pytest

from constants import OAS_CLAWBACK_THRESHOLD
from projection import (
    PlanInputs,
    build_result,
    compute_all,
    deterministic_projection,
    monte_carlo,
    oas_adjustment,
    qpp_adjustment,
    validate,
)


# ---------------------------------------------------------------------------
# Statutory adjustment factors
# ---------------------------------------------------------------------------
def test_qpp_adjustment_factors():
    # -0.6%/month x 60 months = 36% reduction at 60 (CPP/QPP aligned since 2024)
    assert qpp_adjustment(60) == pytest.approx(0.64)
    assert qpp_adjustment(65) == pytest.approx(1.0)
    # +0.7%/month x 60 months = 42% increase at 70
    assert qpp_adjustment(70) == pytest.approx(1.42)
    # QPP deferral extended to 72 (2026): +0.7%/month x 84 months = 58.8% at 72
    assert qpp_adjustment(72) == pytest.approx(1.588)


def test_oas_adjustment_factors():
    assert oas_adjustment(65) == pytest.approx(1.0)
    assert oas_adjustment(70) == pytest.approx(1.36)  # +0.6%/month x 60 months


# ---------------------------------------------------------------------------
# Deterministic model
# ---------------------------------------------------------------------------
def test_zero_growth_contributions_only():
    p = PlanInputs(
        current_age=30, retirement_age=40, end_age=40,
        rrsp_balance=100_000, rrsp_monthly=500,
        tfsa_balance=50_000, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0, volatility=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0, target_monthly_income=0.0,
    )
    rows = deterministic_projection(p)
    assert len(rows) == 11  # ages 30..40 inclusive
    last = rows[-1]
    assert last["rrsp"] == pytest.approx(100_000 + 500 * 12 * 10)
    assert last["tfsa"] == pytest.approx(50_000)
    assert last["total"] == pytest.approx(100_000 + 500 * 12 * 10 + 50_000)
    assert last["withdrawal"] == pytest.approx(0.0)
    assert last["shortfall"] == pytest.approx(0.0)


def test_inflation_indexed_withdrawal():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=66,
        rrsp_balance=0, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=1_000_000, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.02,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=4_000, end_income_ratio=1.0,  # isolate inflation, no decline
    )
    rows = deterministic_projection(p)
    assert rows[0]["withdrawal"] == pytest.approx(4_000 * 12)         # year 1, no inflation
    assert rows[1]["withdrawal"] == pytest.approx(4_000 * 12 * 1.02)  # year 2, +2%
    assert rows[1]["shortfall"] == pytest.approx(0.0)


def test_ferr_minimum_at_71_excess_to_tfsa():
    p = PlanInputs(
        current_age=71, retirement_age=71, end_age=71,
        rrsp_balance=100_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0, tax_rate=0.30,
    )
    row = deterministic_projection(p)[0]
    ferr_min = 0.0528 * 100_000  # ITR s. 7308 factor at 71
    assert row["rrsp"] == pytest.approx(100_000 - ferr_min)
    assert row["tfsa"] == pytest.approx(ferr_min * 0.70)  # after-tax surplus reinvested
    assert row["withdrawal"] == pytest.approx(ferr_min)
    assert row["shortfall"] == pytest.approx(0.0)


def test_rrsp_contributions_stop_and_redirect_at_71():
    p = PlanInputs(
        current_age=70, retirement_age=80, end_age=72,
        rrsp_balance=0, rrsp_monthly=100,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0, tax_rate=0.0,
    )
    rows = deterministic_projection(p)
    assert rows[0]["rrsp"] == pytest.approx(1_200)  # age 70: contribution to RRSP
    # age 71: RRSP closed -> contribution redirected to TFSA; FERR minimum withdrawn
    assert rows[1]["rrsp"] == pytest.approx(1_200 - 0.0528 * 1_200)
    assert rows[1]["tfsa"] == pytest.approx(1_200 + 0.0528 * 1_200)


def test_exhaustion_year_and_shortfall_amount():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=66,
        rrsp_balance=10_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=2_000, tax_rate=0.30,
    )
    res = build_result(p, deterministic_projection(p), monte_carlo(p, num_sims=20))
    short = next(r for r in res["projection"] if r["shortfall"] > 0)
    assert short["age"] == 65
    # All 10k withdrawn from RRSP at 30% tax -> 7k net toward a 24k need.
    assert short["withdrawal"] == pytest.approx(10_000)
    assert short["shortfall"] == pytest.approx(2_000 * 12 - 10_000 * 0.70)
    assert res["summary"][-3][0] == "Exhaustion year (deterministic)"
    assert res["summary"][-3][1] == short["year"]
    assert res["summary"][-2][1] == 0  # no fully covered retirement years


# ---------------------------------------------------------------------------
# Linear income decline
# ---------------------------------------------------------------------------
def test_linear_income_decline():
    p = PlanInputs(
        current_age=60, retirement_age=60, end_age=70,
        rrsp_balance=0, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=10_000_000, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=4_000, end_income_ratio=0.6,
    )
    by_age = {r["age"]: r for r in deterministic_projection(p)}
    assert by_age[60]["withdrawal"] == pytest.approx(4_000 * 12 * 1.0)   # 100% at retirement
    assert by_age[65]["withdrawal"] == pytest.approx(4_000 * 12 * 0.8)   # midpoint of decline
    assert by_age[70]["withdrawal"] == pytest.approx(4_000 * 12 * 0.6)   # 60% at end age
    assert by_age[70]["shortfall"] == pytest.approx(0.0)


def test_decline_only_in_retirement():
    p = PlanInputs(
        current_age=40, retirement_age=65, end_age=66,
        rrsp_balance=0, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=1_000_000, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=4_000, end_income_ratio=0.6,
    )
    by_age = {r["age"]: r for r in deterministic_projection(p)}
    assert by_age[40]["withdrawal"] == pytest.approx(0.0)   # working year: no retirement draw
    assert by_age[64]["withdrawal"] == pytest.approx(0.0)
    assert by_age[40]["income_pct"] == pytest.approx(0.0)   # no retirement target before retirement
    assert by_age[40]["income_target"] == pytest.approx(0.0)
    assert by_age[65]["income_pct"] == pytest.approx(100.0)
    assert by_age[66]["income_pct"] == pytest.approx(60.0)  # end age -> 60%


def test_rows_carry_income_pct_and_target():
    p = PlanInputs(
        current_age=60, retirement_age=65, end_age=70,
        rrsp_balance=0, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=10_000_000, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=4_000, end_income_ratio=0.6,
    )
    by_age = {r["age"]: r for r in deterministic_projection(p)}
    assert by_age[60]["income_pct"] == pytest.approx(0.0)      # working
    assert by_age[60]["income_target"] == pytest.approx(0.0)
    assert by_age[65]["income_target"] == pytest.approx(4_000 * 1.0)
    assert by_age[70]["income_target"] == pytest.approx(4_000 * 0.6)


# ---------------------------------------------------------------------------
# Detail columns: tax paid, FERR minimum, OAS clawback
# ---------------------------------------------------------------------------
def test_tax_paid_on_rrsp_withdrawal():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=65,
        rrsp_balance=100_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=2_000, end_income_ratio=1.0, tax_rate=0.30,
    )
    row = deterministic_projection(p)[0]
    gross = 2_000 * 12 / 0.70  # net need grossed up at 30% tax
    assert row["withdrawal"] == pytest.approx(gross)
    assert row["tax_paid"] == pytest.approx(gross * 0.30)
    assert row["ferr_min"] == pytest.approx(0.0)  # before 71
    assert row["oas_clawback"] == pytest.approx(0.0)
    assert row["shortfall"] == pytest.approx(0.0)


def test_ferr_minimum_and_tax_column_at_71():
    p = PlanInputs(
        current_age=71, retirement_age=71, end_age=71,
        rrsp_balance=100_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0, tax_rate=0.30,
    )
    row = deterministic_projection(p)[0]
    ferr_min = 0.0528 * 100_000
    assert row["ferr_min"] == pytest.approx(ferr_min)
    assert row["withdrawal"] == pytest.approx(ferr_min)
    assert row["tax_paid"] == pytest.approx(ferr_min * 0.30)
    assert row["oas_clawback"] == pytest.approx(0.0)


def test_oas_clawback_column():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=65,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        target_monthly_income=8_000, end_income_ratio=1.0,
        qpp_monthly_at_65=1_200, oas_monthly=734.95,
        qpp_start_age=65, oas_start_age=65,
        oas_clawback=True, tax_rate=0.30,
    )
    row = deterministic_projection(p)[0]
    oas_gross = 734.95 * 12
    cpp = 1_200 * 12
    # Mirror the model's fixed-point estimate: the clawback reduces OAS, which
    # raises the RRSP/FERR withdrawal (and income), which raises the clawback.
    oas_est = oas_gross
    expected_clawback = 0.0
    for _ in range(5):
        gap = max(0.0, 8_000 * 12 - (cpp + oas_est) * 0.70)
        rrsp = gap / 0.70 if gap > 0 else 0.0
        excess = cpp + oas_gross + rrsp - OAS_CLAWBACK_THRESHOLD
        expected_clawback = min(oas_gross, 0.15 * max(0.0, excess))
        oas_est = oas_gross - expected_clawback
    assert expected_clawback > 0  # scenario must actually trigger a clawback
    assert row["oas_clawback"] == pytest.approx(expected_clawback)
    assert row["oas"] == pytest.approx(oas_gross - expected_clawback)


def test_oas_clawback_threshold_indexed_to_inflation():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=67,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.02,
        target_monthly_income=8_000, end_income_ratio=1.0,
        qpp_monthly_at_65=1_200, oas_monthly=734.95,
        qpp_start_age=65, oas_start_age=65,
        oas_clawback=True, tax_rate=0.30,
    )
    rows = deterministic_projection(p)
    c65 = next(r for r in rows if r["age"] == 65)
    c66 = next(r for r in rows if r["age"] == 66)
    assert c65["oas_clawback"] > 0 and c66["oas_clawback"] > 0
    # Both income and the threshold inflate by the same factor, so the clawback
    # scales (approximately) exactly with inflation.
    assert c66["oas_clawback"] == pytest.approx(c65["oas_clawback"] * 1.02)


def test_pensions_are_taxable():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=65,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        target_monthly_income=4_000, end_income_ratio=1.0,
        qpp_monthly_at_65=1_000, oas_monthly=0.0,
        qpp_start_age=65, oas_start_age=65,
        tax_rate=0.30,
    )
    row = deterministic_projection(p)[0]
    cpp = 1_000 * 12  # 12,000/yr — fully taxable
    # after-tax gap = target − pensions×(1−tax); grossed up from accounts
    gross = (4_000 * 12 - cpp * 0.70) / 0.70
    assert row["withdrawal"] == pytest.approx(gross)
    # tax paid covers the pension income AND the withdrawal
    assert row["tax_paid"] == pytest.approx((cpp + gross) * 0.30)
    assert row["shortfall"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------
def test_monte_carlo_reproducible_with_seed():
    p = PlanInputs()
    a = monte_carlo(p, num_sims=300)
    b = monte_carlo(p, num_sims=300)
    assert a == b


def test_monte_carlo_success_and_percentile_order():
    p = PlanInputs()
    mc = monte_carlo(p, num_sims=200)
    assert 0 <= mc["success_pct"] <= 100
    rb = mc["retirement_balance"]
    assert rb[5] <= rb[50] <= rb[95]
    assert len(mc["years"]) == p.end_age - p.current_age + 1
    assert len(mc["total_p5"]) == len(mc["years"]) == len(mc["total_p95"])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validation_errors():
    assert validate(PlanInputs(current_age=65, retirement_age=65, end_age=95))  # retire <= current
    assert validate(PlanInputs(current_age=40, retirement_age=65, end_age=65))  # end <= retire
    assert validate(PlanInputs(qpp_start_age=59))
    assert validate(PlanInputs(qpp_start_age=73))  # 60-72 is the statutory range since 2026
    assert validate(PlanInputs(oas_start_age=66))
    assert validate(PlanInputs(tax_rate=1.5))
    assert validate(PlanInputs(rrsp_balance=-1))
    assert validate(PlanInputs(annual_return=-0.1))
    assert validate(PlanInputs(end_income_ratio=-0.1))
    assert validate(PlanInputs(end_income_ratio=1.5))


def test_defaults_are_valid_and_run_end_to_end():
    p = PlanInputs()
    assert validate(p) == []
    res = compute_all(p)
    assert len(res["projection"]) == p.end_age - p.current_age + 1
    assert len(res["summary"]) > 20
    assert 0 <= res["montecarlo"]["success_pct"] <= 100
