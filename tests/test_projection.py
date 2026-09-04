"""Tests for the deterministic projection model, Monte Carlo and validation."""

import pytest

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
from tax import eligible_pension_income, income_tax, oas_recovery


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


def test_rrif_minimum_at_71_excess_to_tfsa():
    p = PlanInputs(
        current_age=71, retirement_age=71, end_age=71,
        rrsp_balance=100_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,
    )
    row = deterministic_projection(p)[0]
    rrif_min = 0.0528 * 100_000  # ITR s. 7308 factor at 71
    assert row["rrsp"] == pytest.approx(100_000 - rrif_min)
    # Income is only the $5,280 minimum, well below the basic personal
    # amounts, so no tax is owed and the full amount is reinvested.
    assert row["tfsa"] == pytest.approx(rrif_min)
    assert row["withdrawal"] == pytest.approx(rrif_min)
    assert row["tax_paid"] == pytest.approx(0.0)
    assert row["shortfall"] == pytest.approx(0.0)


def test_rrsp_contributions_stop_and_redirect_at_71():
    p = PlanInputs(
        current_age=70, retirement_age=80, end_age=72,
        rrsp_balance=0, rrsp_monthly=100,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,
    )
    rows = deterministic_projection(p)
    assert rows[0]["rrsp"] == pytest.approx(1_200)  # age 70: contribution to RRSP
    # age 71: RRSP closed -> contribution redirected to TFSA; RRIF minimum
    # withdrawn (tax-free, below the basic personal amounts) and reinvested.
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
        target_monthly_income=2_000,
    )
    res = build_result(p, deterministic_projection(p), monte_carlo(p, num_sims=20))
    short = next(r for r in res["projection"] if r["shortfall"] > 0)
    assert short["age"] == 65
    # All 10k withdrawn from the RRSP; the income is below the basic personal
    # amounts so no tax is owed and the whole 10k covers the 24k need.
    assert short["withdrawal"] == pytest.approx(10_000)
    assert short["tax_paid"] == pytest.approx(0.0)
    assert short["shortfall"] == pytest.approx(2_000 * 12 - 10_000)
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
# Detail columns: tax paid, RRIF minimum, OAS clawback
# ---------------------------------------------------------------------------
def test_tax_paid_on_rrsp_withdrawal():
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=65,
        rrsp_balance=100_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=2_000, end_income_ratio=1.0,
        rrif_conversion_age=71,  # keep this a pre-conversion RRSP scenario
    )
    row = deterministic_projection(p)[0]
    gross = row["withdrawal"]
    # The gross withdrawal is solved so its after-tax proceeds cover the
    # $24,000 need exactly, with tax from the real progressive model.
    assert gross - row["tax_paid"] == pytest.approx(2_000 * 12, abs=0.02)
    assert row["tax_paid"] == pytest.approx(
        sum(income_tax(gross, 65, eligible_pension_income(65, gross, 71), 0.0, row["year"]))
    )
    assert row["rrif_min"] == pytest.approx(0.0)  # before 71
    assert row["oas_clawback"] == pytest.approx(0.0)
    assert row["shortfall"] == pytest.approx(0.0)
    assert 0.0 < row["marginal_rate"] < 0.95
    assert row["effective_rate"] == pytest.approx(row["tax_paid"] / gross)


def test_rrif_minimum_and_tax_column_at_71():
    p = PlanInputs(
        current_age=71, retirement_age=71, end_age=71,
        rrsp_balance=100_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,
    )
    row = deterministic_projection(p)[0]
    rrif_min = 0.0528 * 100_000
    assert row["rrif_min"] == pytest.approx(rrif_min)
    assert row["withdrawal"] == pytest.approx(rrif_min)
    # $5,280 of income is below the basic personal amounts: no tax.
    assert row["tax_paid"] == pytest.approx(0.0)
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
        oas_clawback=True, rrif_conversion_age=71,  # keep this a pre-conversion RRSP scenario
    )
    row = deterministic_projection(p)[0]
    oas_gross = 734.95 * 12
    cpp = 1_200 * 12
    # The model's defining equations: the clawback is 15% of taxable income
    # above the indexed threshold (capped at OAS), and the after-tax cash
    # identity holds exactly.
    taxable = cpp + oas_gross + row["withdrawal"]
    expected_clawback = oas_recovery(taxable, oas_gross, 0.0, row["year"])
    assert expected_clawback > 0  # scenario must actually trigger a clawback
    assert row["oas_clawback"] == pytest.approx(expected_clawback)
    assert row["oas"] == pytest.approx(oas_gross - expected_clawback)
    assert row["tax_paid"] == pytest.approx(
        sum(income_tax(taxable, 65, eligible_pension_income(65, row["withdrawal"]), 0.0, row["year"]))
    )
    after_tax = cpp + row["oas"] + row["withdrawal"] - row["tax_paid"]
    assert after_tax == pytest.approx(8_000 * 12, abs=0.02)


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
        oas_clawback=True,
    )
    rows = deterministic_projection(p)
    c65 = next(r for r in rows if r["age"] == 65)
    c66 = next(r for r in rows if r["age"] == 66)
    assert c65["oas_clawback"] > 0 and c66["oas_clawback"] > 0
    # Both income and the threshold inflate by the same factor, so the clawback
    # scales (approximately) exactly with inflation.
    assert c66["oas_clawback"] == pytest.approx(c65["oas_clawback"] * 1.02)


def test_oas_age_75_supplement():
    # +10% OAS top-up from age 75 (Budget 2022): $734.95 x 1.10 = $808.45/mo.
    p = PlanInputs(
        current_age=65, retirement_age=65, end_age=76,
        rrsp_balance=0, rrsp_monthly=0,
        tfsa_balance=1_000_000, tfsa_monthly=0,  # TFSA covers any income gap
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        target_monthly_income=1_000, end_income_ratio=1.0,
        qpp_monthly_at_65=0.0, oas_monthly=734.95,
        qpp_start_age=65, oas_start_age=65,
        oas_clawback=False,
    )
    by_age = {r["age"]: r for r in deterministic_projection(p)}
    assert by_age[65]["oas"] == pytest.approx(734.95 * 12)
    assert by_age[74]["oas"] == pytest.approx(734.95 * 12)
    assert by_age[75]["oas"] == pytest.approx(734.95 * 12 * 1.10)
    assert by_age[76]["oas"] == pytest.approx(734.95 * 12 * 1.10)


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
        rrif_conversion_age=71,  # keep this a pre-conversion RRSP scenario
    )
    row = deterministic_projection(p)[0]
    cpp = 1_000 * 12  # 12,000/yr — fully taxable
    gross = row["withdrawal"]
    # After-tax cash identity: CPP + RRSP after tax cover the $48,000 need.
    assert cpp + gross - row["tax_paid"] == pytest.approx(4_000 * 12, abs=0.02)
    # Tax is the real progressive tax on CPP + the withdrawal (age 65 credits apply).
    assert row["tax_paid"] == pytest.approx(
        sum(income_tax(cpp + gross, 65, eligible_pension_income(65, gross, 71), 0.0, row["year"]))
    )
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
    assert validate(PlanInputs(rrif_conversion_age=54))
    assert validate(PlanInputs(rrif_conversion_age=72))
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


def test_new_tax_columns_and_summary():
    p = PlanInputs()
    res = compute_all(p)
    first_ret = next(r for r in res["projection"] if r["age"] == p.retirement_age)
    # Every retirement row carries a marginal and effective rate.
    for r in res["projection"]:
        assert 0.0 <= r["marginal_rate"] <= 0.95
        assert 0.0 <= r["effective_rate"] <= 0.95
    labels = [s[0] for s in res["summary"]]
    assert "Marginal tax rate at retirement, first year (%)" in labels
    assert "Effective tax rate at retirement, first year (%)" in labels
    assert "Tax model" in labels
    # The reported marginal/effective rates match the retirement row.
    assert next(s[1] for s in res["summary"] if s[0] == "Marginal tax rate at retirement, first year (%)") == pytest.approx(
        first_ret["marginal_rate"] * 100.0, abs=0.01
    )


# ---------------------------------------------------------------------------
# RRSP -> RRIF conversion age
# ---------------------------------------------------------------------------
def test_rrif_conversion_age_resolution():
    from projection import rrif_conversion_age as resolve
    # Default: convert at the retirement age.
    assert resolve(PlanInputs(retirement_age=60)) == 60
    assert resolve(PlanInputs(retirement_age=59)) == 59
    # Cannot defer past the statutory deadline of 71.
    assert resolve(PlanInputs(retirement_age=80)) == 71
    # An explicit choice is honored.
    assert resolve(PlanInputs(retirement_age=65, rrif_conversion_age=60)) == 60
    assert resolve(PlanInputs(retirement_age=65, rrif_conversion_age=71)) == 71


def test_conversion_at_retirement_starts_rrif_minimum_and_credits():
    p = PlanInputs(
        current_age=59, retirement_age=60, end_age=61,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,
    )
    rows = deterministic_projection(p)
    r60 = next(r for r in rows if r["age"] == 60)
    rrif_min = 1_000_000 / 30.0  # 1/(90-60) x balance at the conversion age
    assert r60["rrif_min"] == pytest.approx(rrif_min)
    # No income need, so the minimum is withdrawn and reinvested after tax;
    # from the conversion age the RRIF payments also earn the pension-income
    # credits (federal + Quebec), so the tax is exactly income_tax(...).
    assert r60["withdrawal"] == pytest.approx(rrif_min)
    assert r60["tax_paid"] == pytest.approx(
        sum(income_tax(rrif_min, 60, eligible_pension_income(60, rrif_min, 60), 0.0, r60["year"]))
    )


def test_contributions_redirect_at_conversion_age():
    p = PlanInputs(
        current_age=58, retirement_age=67, end_age=69,
        rrsp_balance=0, rrsp_monthly=100,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0, rrif_conversion_age=60,
    )
    rows = deterministic_projection(p)
    by_age = {r["age"]: r for r in rows}
    assert by_age[58]["rrsp"] == pytest.approx(1_200)   # contribution to RRSP before conversion
    assert by_age[59]["rrsp"] == pytest.approx(2_400)
    # Age 60 = conversion: the RRSP is closed, so the monthly contribution is
    # redirected to the TFSA, and the RRIF minimum (1/30 of the balance) is
    # withdrawn and reinvested (tax-free here).
    rrif_min = 2_400 / 30.0
    assert by_age[60]["rrsp"] == pytest.approx(2_400 - rrif_min)
    assert by_age[60]["tfsa"] == pytest.approx(1_200 + rrif_min)
    # Contributions keep flowing to the TFSA after the conversion.
    assert by_age[61]["tfsa"] > by_age[60]["tfsa"]


def test_default_scenario_converts_at_retirement():
    p = PlanInputs()
    res = build_result(p, deterministic_projection(p), monte_carlo(p, num_sims=20))
    conv_line = next(s for s in res["summary"] if s[0].startswith("RRIF conversion year"))
    assert conv_line[0] == f"RRIF conversion year (RRSP converted at {p.retirement_age})"
    assert conv_line[1] == p.retirement_age


# ---------------------------------------------------------------------------
# Monthly meltdown: monthly TFSA savings funded from RRIF withdrawals, pre-QPP
# ---------------------------------------------------------------------------
def test_monthly_meltdown_deposited_in_tfsa_after_tax():
    # No income need: the RRIF withdrawal is grossed up so the full monthly
    # savings target lands in the TFSA after tax.
    p = PlanInputs(
        current_age=64, retirement_age=65, end_age=66,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,  # no income need: isolate the savings
        rrif_conversion_age=71,      # age 65 < 71 -> no mandatory minimum
        monthly_meltdown=5_000,  # 60,000/yr deposited into the TFSA
    )
    row = next(r for r in deterministic_projection(p) if r["age"] == 65)
    assert row["withdrawal"] > 60_000  # grossed up for the tax on the withdrawal
    assert row["tfsa"] == pytest.approx(60_000, abs=0.5)  # the after-tax deposit
    assert row["shortfall"] == pytest.approx(0.0)


def test_monthly_meltdown_add_on_top_of_need():
    p = PlanInputs(
        current_age=64, retirement_age=65, end_age=66,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=2_000,  # 24,000/yr after-tax need
        rrif_conversion_age=71,
        monthly_meltdown=1_000,   # 12,000/yr into the TFSA
    )
    row = next(r for r in deterministic_projection(p) if r["age"] == 65)
    # The RRIF withdrawal nets the spending need PLUS the savings.
    assert row["withdrawal"] - row["tax_paid"] == pytest.approx(2_000 * 12 + 12_000, abs=0.1)
    assert row["tfsa"] == pytest.approx(12_000, abs=0.5)
    assert row["shortfall"] == pytest.approx(0.0)


def test_monthly_meltdown_stop_at_qpp_start():
    # Savings apply only while age < qpp_start_age. With no spending need and a
    # late conversion (no mandatory minimum until 71), the withdrawal equals the
    # savings deposit exactly, so the boundary is easy to see.
    def run(qpp_start):
        p = PlanInputs(
            current_age=59, retirement_age=60, end_age=71,
            rrsp_balance=300_000, rrsp_monthly=0,
            tfsa_balance=0, tfsa_monthly=0,
            nonreg_balance=0, nonreg_monthly=0,
            annual_return=0.0, inflation_rate=0.0,
            qpp_monthly_at_65=0.0, oas_monthly=0.0,
            target_monthly_income=0.0,
            rrif_conversion_age=71,  # no minimum until 71
            qpp_start_age=qpp_start,
            monthly_meltdown=500,  # 6,000/yr
        )
        return {r["age"]: r for r in deterministic_projection(p)}

    qpp70 = run(70)
    qpp72 = run(72)
    # Both save in the years before QPP starts.
    assert qpp70[69]["withdrawal"] == pytest.approx(6_000)
    assert qpp72[69]["withdrawal"] == pytest.approx(6_000)
    # At 70: savings stop if QPP starts at 70, but continue if it starts at 72.
    assert qpp70[70]["withdrawal"] == pytest.approx(0.0)
    assert qpp72[70]["withdrawal"] == pytest.approx(6_000)


def test_monthly_meltdown_is_inflation_indexed():
    p = PlanInputs(
        current_age=64, retirement_age=65, end_age=67,
        rrsp_balance=1_000_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.02,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,
        rrif_conversion_age=71,
        monthly_meltdown=1_000,  # 12,000/yr, indexed
    )
    by_age = {r["age"]: r for r in deterministic_projection(p)}
    assert by_age[65]["withdrawal"] == pytest.approx(12_000 * 1.02)        # offset 1
    assert by_age[66]["withdrawal"] == pytest.approx(12_000 * 1.02 ** 2)   # offset 2


def test_monthly_meltdown_clamped_by_balance():
    p = PlanInputs(
        current_age=64, retirement_age=65, end_age=66,
        rrsp_balance=5_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=0.0,
        rrif_conversion_age=71,
        monthly_meltdown=5_000,  # wants 60,000/yr, balance is only 5,000
    )
    row = next(r for r in deterministic_projection(p) if r["age"] == 65)
    assert row["withdrawal"] == pytest.approx(5_000)
    assert row["rrsp"] == pytest.approx(0.0)
    assert row["tfsa"] == pytest.approx(5_000 - row["tax_paid"])


def test_monthly_meltdown_headline_scenario():
    # The default scenario's jump at QPP start (eff 15.89% @71 -> 18.55% @72)
    # disappears once the RRIF is small enough that the minimum stops binding.
    base = compute_all(PlanInputs())
    melt = compute_all(PlanInputs(monthly_meltdown=550))
    b72 = next(r for r in base["projection"] if r["age"] == 72)
    m72 = next(r for r in melt["projection"] if r["age"] == 72)
    assert b72["effective_rate"] > 0.17  # sanity: the base scenario really jumps
    assert m72["effective_rate"] < b72["effective_rate"]
    assert m72["effective_rate"] < 0.17
    assert m72["rrsp"] < b72["rrsp"]
    # The mandatory minimum no longer binds at 72 with the meltdown.
    assert m72["withdrawal"] > m72["rrif_min"]
    # Total income tax over retirement falls.
    tax_base = sum(r["tax_paid"] for r in base["projection"])
    tax_melt = sum(r["tax_paid"] for r in melt["projection"])
    assert tax_melt < tax_base


# ---------------------------------------------------------------------------
# After-tax netting bugs (regression)
# ---------------------------------------------------------------------------
def test_no_phantom_tfsa_deposit_once_pensions_start():
    # 3% return, all else default: once QPP/OAS start (age 72) the RRIF
    # withdrawal is income-driven (it still exceeds the RRIF minimum because
    # pensions do not fully cover the need). Pensions must be netted AFTER their
    # own income tax; netting them gross used to create a phantom "surplus"
    # equal to the pension tax that was reinvested in the TFSA every year.
    p = PlanInputs(annual_return=0.03)
    rows = deterministic_projection(p)
    by_age = {r["age"]: r for r in rows}
    # No surplus reinvestment is genuine here, so the TFSA never grows.
    for age in range(p.retirement_age, p.end_age + 1):
        assert by_age[age]["tfsa"] == pytest.approx(0.0, abs=1.0)


def test_no_withdrawal_jump_when_rrsp_depletes_with_meltdown():
    # 3% + monthly meltdown 500: the meltdown shrinks the RRIF so it is fully
    # depleted around age 79. When the RRSP hits zero (rrsp_gross == 0) the
    # pension income must still be netted against the income need before drawing
    # the TFSA. Previously the netting was skipped that year, so the whole need
    # came from the TFSA on top of the pensions - a sudden ~69k withdrawal at
    # age 80 pushing income far above target.
    p = PlanInputs(annual_return=0.03, monthly_meltdown=500)
    rows = deterministic_projection(p)
    by_age = {r["age"]: r for r in rows}
    # The RRSP is gone by 80.
    assert by_age[80]["rrsp"] == pytest.approx(0.0)
    # Withdrawals stay smooth and near the after-tax income gap, never the full
    # need (~69k/yr in today's $ + inflation). No shortfalls either.
    for age in range(79, p.end_age + 1):
        assert by_age[age]["withdrawal"] < 25_000
        assert by_age[age]["shortfall"] == pytest.approx(0.0)
    # And depletion is smooth (no big year-over-year jump after the RRSP is gone).
    assert by_age[81]["withdrawal"] <= by_age[80]["withdrawal"]
