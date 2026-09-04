"""Deterministic and Monte Carlo retirement projection for Quebec (QPP/OAS/RRSP/TFSA/RRIF).

The model is deliberately simple and transparent:
- Three accounts: RRSP (RRSP, pre-tax), TFSA (TFSA, tax-free), non-registered.
- Pensions (only during retirement years): QPP and OAS, both
  inflation-indexed from today, with statutory start-age adjustments, the
  +10% OAS top-up from age 75, and an optional OAS clawback approximation.
- RRSP converts to an RRIF at the chosen conversion age (default: the
  retirement age; statutory deadline 71) with mandatory minimum withdrawals
  (Income Tax Regulations s. 7308); any after-tax surplus from a minimum that
  exceeds the income need is reinvested in the TFSA (simplification).
- An optional monthly TFSA savings target (today's dollars, inflation-indexed)
  is funded from RRIF withdrawals each retirement year before QPP starts
  (a "meltdown" that shrinks the RRIF); the savings are deposited in the TFSA
  after tax.
- Withdrawals come from non-registered first, then RRSP/RRIF (grossed up for
  tax), then TFSA.
- Income tax is modeled automatically from the 2026 federal + Quebec
  progressive brackets and non-refundable credits (see tax.py): the RRSP/RRIF
  gross-up is solved against the real tax function (brackets, basic personal,
  age 65+ and pension-income credits, the Quebec abatement, and the OAS
  recovery tax), indexed to inflation from 2026.
- Retirement income needs decline linearly from 100% at the retirement age to
  a configurable percentage at the end age (in today's dollars), with
  inflation applied on top.
- Monte Carlo samples annual lognormal returns around the expected return and
  volatility, with a fixed seed for reproducibility.

This is an informational planning tool, not financial advice. Tax and
non-registered-tax simplifications are documented in the README and echoed in
the summary CSV.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date

from constants import (
    DEFAULT_ANNUAL_RETURN,
    DEFAULT_CONTRIBUTION_ESCALATION,
    DEFAULT_CURRENT_AGE,
    DEFAULT_END_AGE,
    DEFAULT_END_INCOME_RATIO,
    DEFAULT_MONTHLY_MELTDOWN,
    DEFAULT_RRIF_CONVERSION_AGE,
    DEFAULT_INFLATION,
    DEFAULT_MONTE_CARLO_SIMS,
    DEFAULT_NONREG_BALANCE,
    DEFAULT_NONREG_MONTHLY,
    DEFAULT_OAS_CLAWBACK,
    DEFAULT_OAS_START_AGE,
    DEFAULT_QPP_PCT_OF_MAX,
    DEFAULT_QPP_START_AGE,
    DEFAULT_RETIREMENT_AGE,
    DEFAULT_RRSP_BALANCE,
    DEFAULT_RRSP_MONTHLY,
    DEFAULT_SEED,
    DEFAULT_TARGET_MONTHLY_INCOME,
    DEFAULT_TFSA_BALANCE,
    DEFAULT_TFSA_MONTHLY,
    DEFAULT_VOLATILITY,
    RRIF_CONVERSION_AGE,
    RRIF_CONVERSION_MIN_AGE,
    OAS_MAX_2025,
    OAS_DEFERRAL_MAX_AGE,
    OAS_DEFERRAL_PER_MONTH,
    OAS_SUPPLEMENT_AGE,
    OAS_SUPPLEMENT_AT_75,
    QPP_EARLY_REDUCTION_PER_MONTH,
    QPP_LATE_INCREASE_PER_MONTH,
    QPP_MAX_AT_65_2025,
    QPP_MAX_START_AGE,
    QPP_MIN_START_AGE,
    rrif_min_factor,
)
from tax import (
    eligible_pension_income,
    income_tax,
    marginal_burden_rate,
    oas_recovery,
)

MONEY_EPS = 1e-9
SHORTFALL_EPS = 0.05  # sub-cent residuals from the tax solve are treated as fully covered


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanInputs:
    """All planning inputs. Monetary amounts in CAD, rates as fractions."""

    # Personal
    current_age: int = DEFAULT_CURRENT_AGE
    retirement_age: int = DEFAULT_RETIREMENT_AGE
    end_age: int = DEFAULT_END_AGE                  # life expectancy

    # Accounts (balance + monthly contribution until retirement)
    rrsp_balance: float = DEFAULT_RRSP_BALANCE
    rrsp_monthly: float = DEFAULT_RRSP_MONTHLY
    tfsa_balance: float = DEFAULT_TFSA_BALANCE
    tfsa_monthly: float = DEFAULT_TFSA_MONTHLY
    nonreg_balance: float = DEFAULT_NONREG_BALANCE
    nonreg_monthly: float = DEFAULT_NONREG_MONTHLY

    # Assumptions
    annual_return: float = DEFAULT_ANNUAL_RETURN
    inflation_rate: float = DEFAULT_INFLATION
    volatility: float = DEFAULT_VOLATILITY
    contribution_escalation: float = DEFAULT_CONTRIBUTION_ESCALATION

    # Retirement income
    target_monthly_income: float = DEFAULT_TARGET_MONTHLY_INCOME   # today's dollars
    end_income_ratio: float = DEFAULT_END_INCOME_RATIO             # income at end age, fraction of retirement income
    qpp_monthly_at_65: float = QPP_MAX_AT_65_2025 * DEFAULT_QPP_PCT_OF_MAX  # user's age-65 estimate (default 85% of the maximum)
    qpp_start_age: int = DEFAULT_QPP_START_AGE
    oas_monthly: float = OAS_MAX_2025                              # today's dollars, at 65
    oas_start_age: int = DEFAULT_OAS_START_AGE
    oas_clawback: bool = DEFAULT_OAS_CLAWBACK
    rrif_conversion_age: int | None = DEFAULT_RRIF_CONVERSION_AGE  # None = convert RRSP to RRIF at retirement age (deadline 71)
    monthly_meltdown: float = DEFAULT_MONTHLY_MELTDOWN      # monthly TFSA savings funded from RRIF withdrawals (meltdown), today's dollars; applies from retirement until QPP starts

    # Monte Carlo
    num_sims: int = DEFAULT_MONTE_CARLO_SIMS
    seed: int = DEFAULT_SEED

    # Income tax is fully automatic: progressive federal + Quebec brackets
    # and credits (2026, indexed to inflation) - see tax.py. No tax inputs.


def validate(p: PlanInputs) -> list[str]:
    """Return a list of human-readable input errors (empty if valid)."""
    errs: list[str] = []
    if not 18 <= p.current_age <= 100:
        errs.append("Current age must be between 18 and 100.")
    if p.retirement_age <= p.current_age:
        errs.append("Retirement age must be greater than current age.")
    if p.end_age <= p.retirement_age:
        errs.append("End age must be greater than retirement age.")
    if p.end_age > 110:
        errs.append("End age must be at most 110.")
    for label, v in (
        ("RRSP balance", p.rrsp_balance),
        ("RRSP monthly contribution", p.rrsp_monthly),
        ("TFSA balance", p.tfsa_balance),
        ("TFSA monthly contribution", p.tfsa_monthly),
        ("Non-registered balance", p.nonreg_balance),
        ("Non-registered monthly contribution", p.nonreg_monthly),
        ("Target monthly income", p.target_monthly_income),
        ("QPP monthly at 65", p.qpp_monthly_at_65),
        ("OAS monthly", p.oas_monthly),
        ("Monthly meltdown", p.monthly_meltdown),
    ):
        if v < 0:
            errs.append(f"{label} cannot be negative.")
    for label, v in (
        ("Annual return", p.annual_return),
        ("Inflation", p.inflation_rate),
        ("Volatility", p.volatility),
        ("Contribution escalation", p.contribution_escalation),
    ):
        if not 0 <= v < 1:
            errs.append(f"{label} must be between 0% and 100%.")
    if not 0 <= p.end_income_ratio <= 1:
        errs.append("Income at end age must be between 0% and 100% of retirement income.")
    if not QPP_MIN_START_AGE <= p.qpp_start_age <= QPP_MAX_START_AGE:
        errs.append(f"QPP start age must be between {QPP_MIN_START_AGE} and {QPP_MAX_START_AGE}.")
    if p.oas_start_age not in (65, OAS_DEFERRAL_MAX_AGE):
        errs.append("OAS start age must be 65 or 70.")
    if p.rrif_conversion_age is not None and not RRIF_CONVERSION_MIN_AGE <= p.rrif_conversion_age <= RRIF_CONVERSION_AGE:
        errs.append(f"RRIF conversion age must be between {RRIF_CONVERSION_MIN_AGE} and {RRIF_CONVERSION_AGE}.")
    return errs


def rrif_conversion_age(p: PlanInputs) -> int:
    """The age the RRSP becomes a RRIF: the user's chosen conversion age
    or the retirement age when None, capped at the statutory deadline of 71
    (you cannot defer past Dec 31 of the year you turn 71)."""
    age = p.retirement_age if p.rrif_conversion_age is None else p.rrif_conversion_age
    return min(age, RRIF_CONVERSION_AGE)


# ---------------------------------------------------------------------------
# Statutory adjustments
# ---------------------------------------------------------------------------
def qpp_adjustment(start_age: int) -> float:
    """QPP monthly factor for a given start age relative to the age-65 amount.

    -0.6%/month before 65 (36% max at 60), +0.7%/month after 65; the monthly
    rates match CPP since the January 2024 alignment, but QPP deferral now runs
    to 72 (max +58.8%) while CPP still caps at 70.
    """
    if start_age < 65:
        return 1.0 - QPP_EARLY_REDUCTION_PER_MONTH * (65 - start_age) * 12.0
    if start_age > 65:
        return 1.0 + QPP_LATE_INCREASE_PER_MONTH * (start_age - 65) * 12.0
    return 1.0


def oas_adjustment(start_age: int) -> float:
    """OAS monthly factor: +0.6%/month deferred past 65, +36% max at 70."""
    if start_age >= OAS_DEFERRAL_MAX_AGE:
        return 1.0 + OAS_DEFERRAL_PER_MONTH * (OAS_DEFERRAL_MAX_AGE - 65) * 12.0
    return 1.0


def income_fraction(p: PlanInputs, age: int) -> float:
    """Fraction of the retirement income target for a given age.

    Declines linearly from 1.0 at the retirement age down to end_income_ratio
    at the end age (both in today's, pre-inflation dollars).
    """
    if age <= p.retirement_age:
        return 1.0
    span = p.end_age - p.retirement_age  # >= 1 (validated)
    progress = (age - p.retirement_age) / span
    return 1.0 - progress * (1.0 - p.end_income_ratio)


# ---------------------------------------------------------------------------
# Single-year engine (shared by deterministic and Monte Carlo paths)
# ---------------------------------------------------------------------------
def _solve_rrsp_gross(
    p: PlanInputs,
    age: int,
    conv_age: int,
    cpp_income: float,
    oas_gross: float,
    after_tax_need: float,
    rrsp_available: float,
    year: int,
) -> float:
    """Solve the gross RRSP/RRIF withdrawal whose after-tax proceeds (net of
    income tax and the OAS recovery tax it triggers) cover after_tax_need.

    The after-tax cash identity is::

        cpp + (oas_gross - oas_recovery) + gross - income_tax = after_tax_need

    Solved by a Newton-style fixed point on the marginal burden rate (income
    tax + OAS recovery), clamped to [0, rrsp_available]. The function is
    monotone in ``gross``, so the iteration converges quickly.
    """
    gross = 0.0
    for _ in range(12):
        taxable = cpp_income + oas_gross + gross
        pension_income = eligible_pension_income(age, gross, conv_age)
        fed, qc = income_tax(taxable, age, pension_income, p.inflation_rate, year)
        recovery = oas_recovery(taxable, oas_gross, p.inflation_rate, year)
        after_tax = cpp_income + (oas_gross - recovery) + gross - (fed + qc)
        err = after_tax_need - after_tax
        if abs(err) < 0.01:
            break
        rate = marginal_burden_rate(taxable, age, pension_income, oas_gross, p.inflation_rate, year)
        step = err / max(1.0 - rate, 1e-6)
        gross = max(0.0, min(rrsp_available, gross + step))
    return gross


def step_year(
    p: PlanInputs,
    age: int,
    balances: tuple[float, float, float],
    annual_return: float,
    year_offset: int,
    year: int,
) -> tuple[tuple[float, float, float], float, float, float, float, float, float, float, float, float, float]:
    """Advance one year for a given age.

    Returns (new_balances, withdrawal, shortfall, cpp_income, oas_income,
    target_monthly, tax_paid, oas_clawback, rrif_min, marginal_rate,
    effective_rate) where balances is (rrsp, tfsa, nonreg) at the end of the
    previous year, withdrawal is gross cash leaving the accounts during the
    year, target_monthly is the inflation-indexed monthly income target
    (already reduced by the linear income decline), tax_paid is the federal +
    Quebec income tax on all taxable income (CPP + gross OAS + RRSP/RRIF
    withdrawals - both pensions are fully taxable), oas_clawback is the OAS
    recovery tax amount, rrif_min is the mandatory minimum RRSP/RRIF
    withdrawal (0 before the conversion age), marginal_rate is the marginal
    income-tax+recovery rate on the settled income (used to gross up the
    withdrawal) and effective_rate is (tax_paid + oas_clawback) / taxable
    income.
    """
    rrsp, tfsa, nonreg = balances
    working = age < p.retirement_age
    conv_age = rrif_conversion_age(p)
    infl = (1.0 + p.inflation_rate) ** year_offset

    # RRIF minimum is a percentage of the balance at the previous year-end,
    # from the conversion age onward (early conversion uses 1/(90-age)).
    rrif_min = rrif_min_factor(age) * rrsp if age >= conv_age else 0.0

    # Contributions (only while working; the RRSP closes at the conversion age).
    if working:
        esc = (1.0 + p.contribution_escalation) ** year_offset
        rrsp_contrib = p.rrsp_monthly * 12.0 * esc
        if age < conv_age:
            rrsp += rrsp_contrib
        else:
            tfsa += rrsp_contrib  # redirected to TFSA once the RRSP is closed (simplification)
        tfsa += p.tfsa_monthly * 12.0 * esc
        nonreg += p.nonreg_monthly * 12.0 * esc

    # Growth on balances after contributions.
    rrsp *= 1.0 + annual_return
    tfsa *= 1.0 + annual_return
    nonreg *= 1.0 + annual_return

    # Inflation-indexed monthly income target, reduced by the linear decline.
    target_monthly = p.target_monthly_income * income_fraction(p, age) * infl

    # Pensions during retirement years only, indexed from today.
    cpp_income = oas_gross = 0.0
    if not working:
        if age >= p.qpp_start_age:
            cpp_income = p.qpp_monthly_at_65 * qpp_adjustment(p.qpp_start_age) * infl * 12.0
        if age >= p.oas_start_age:
            oas_gross = p.oas_monthly * oas_adjustment(p.oas_start_age) * infl * 12.0
            if age >= OAS_SUPPLEMENT_AGE:
                oas_gross *= OAS_SUPPLEMENT_AT_75  # +10% top-up from age 75 (Budget 2022)

    # After-tax income need from all sources (retirement years only).
    need = target_monthly * 12.0 if not working else 0.0

    # 1. Non-registered first (untaxed in this model; also absent from the
    #    taxable-income proxy below - documented approximation).
    withdrawal = 0.0
    take = min(nonreg, need)
    nonreg -= take
    withdrawal += take
    remaining = need - take

    # 2. RRSP/RRIF: solve the gross-up against the real tax function. The RRIF
    #    minimum is a floor on the withdrawal, even when there is no income gap.
    #    An optional monthly TFSA savings target (funded from RRIF withdrawals,
    #    in today's dollars, inflation-indexed) is added to the after-tax need
    #    each retirement year before QPP starts; the resulting after-tax
    #    surplus is deposited in the TFSA in step 4 (spending is covered
    #    first).
    savings = (
        p.monthly_meltdown * 12.0 * infl
        if (not working and age < p.qpp_start_age)
        else 0.0
    )
    rrsp_gross = 0.0
    if rrsp > MONEY_EPS and (remaining > MONEY_EPS or rrif_min > MONEY_EPS or savings > MONEY_EPS):
        rrsp_after_tax_need = remaining + savings
        solved = (
            _solve_rrsp_gross(p, age, conv_age, cpp_income, oas_gross, rrsp_after_tax_need, rrsp, year)
            if rrsp_after_tax_need > MONEY_EPS
            else 0.0
        )
        rrsp_gross = min(rrsp, max(solved, rrif_min))
        rrsp -= rrsp_gross
        withdrawal += rrsp_gross

    # 3. Income tax + OAS recovery on the settled taxable income (gross OAS is
    #    taxable even when clawed back; the recovery is assessed separately).
    taxable = cpp_income + oas_gross + rrsp_gross
    pension_income = eligible_pension_income(age, rrsp_gross, conv_age)
    fed, qc = income_tax(taxable, age, pension_income, p.inflation_rate, year)
    tax_paid = fed + qc
    oas_clawback = oas_recovery(taxable, oas_gross, p.inflation_rate, year) if (not working and p.oas_clawback) else 0.0
    oas_income = oas_gross - oas_clawback
    marginal_rate = marginal_burden_rate(taxable, age, pension_income, oas_gross, p.inflation_rate, year)
    effective_rate = (tax_paid + oas_clawback) / taxable if taxable > MONEY_EPS else 0.0

    # 4. After-tax accounting: pensions + RRSP/RRIF after tax cover the need;
    #    any surplus from the RRSP/RRIF withdrawal (e.g. the minimum exceeded
    #    the need) is reinvested in the TFSA; TFSA covers the rest.
    shortfall = 0.0
    if not working:
        # Net pension income (after the income tax attributable to it) against
        # the need whether or not an RRSP/RRIF withdrawal happened this year.
        # (Doing this only inside the rrsp_gross>0 branch would skip it once the
        # RRSP is fully depleted, causing the TFSA to cover the whole need on
        # top of the pensions - a sudden withdrawal/income jump at depletion.)
        tax_on_pensions = sum(income_tax(cpp_income + oas_gross, age, 0.0, p.inflation_rate, year))
        rrsp_net = rrsp_gross - (tax_paid - tax_on_pensions) if rrsp_gross > MONEY_EPS else 0.0
        # Compare on a consistent after-tax basis: rrsp_net is the withdrawal's
        # after-tax value (gross minus the incremental tax the withdrawal adds
        # on top of pensions), so pensions must be netted of their own income
        # tax too (tax_on_pensions), not counted gross. Counting pensions gross
        # would understate need_from_rrsp and thus overstate the surplus
        # reinvested in the TFSA by exactly the tax on the pensions (a phantom
        # TFSA deposit once pensions start).
        pensions_after_tax = (cpp_income + oas_income) - tax_on_pensions
        need_from_rrsp = max(0.0, remaining - pensions_after_tax)
        surplus = rrsp_net - need_from_rrsp
        if surplus > MONEY_EPS:
            tfsa += surplus
        remaining = max(0.0, remaining - (pensions_after_tax + rrsp_net))
    else:
        if rrsp_gross > MONEY_EPS:
            # Working year: no retirement income need, so any RRSP/RRIF
            # withdrawal (e.g. a mandatory minimum once the RRSP is closed) is
            # after-tax surplus reinvested in the TFSA. Pensions are zero while
            # working, so tax_on_pensions is 0 and rrsp_net is gross - tax.
            rrsp_net = rrsp_gross - tax_paid
            tfsa += rrsp_net
        remaining = 0.0
    if not working and remaining > MONEY_EPS:
        # 3. TFSA last (tax-free).
        take = min(tfsa, remaining)
        tfsa -= take
        withdrawal += take
        remaining -= take
        shortfall = max(0.0, remaining)
    if shortfall < SHORTFALL_EPS:
        shortfall = 0.0

    return (
        (rrsp, tfsa, nonreg),
        withdrawal,
        shortfall,
        cpp_income,
        oas_income,
        target_monthly,
        tax_paid,
        oas_clawback,
        rrif_min,
        marginal_rate,
        effective_rate,
    )


# ---------------------------------------------------------------------------
# Deterministic projection
# ---------------------------------------------------------------------------
def deterministic_projection(p: PlanInputs) -> list[dict]:
    """Year-by-year projection at the expected return (one row per year)."""
    start_year = date.today().year
    rows: list[dict] = []
    balances = (p.rrsp_balance, p.tfsa_balance, p.nonreg_balance)
    for offset, age in enumerate(range(p.current_age, p.end_age + 1)):
        (
            balances,
            withdrawal,
            shortfall,
            cpp,
            oas,
            target_monthly,
            tax_paid,
            oas_clawback,
            rrif_min,
            marginal_rate,
            effective_rate,
        ) = step_year(p, age, balances, p.annual_return, offset, start_year + offset)
        working = age < p.retirement_age
        rows.append(
            {
                "age": age,
                "year": start_year + offset,
                "income_pct": 0.0 if working else income_fraction(p, age) * 100.0,
                "income_target": 0.0 if working else target_monthly,
                "rrsp": balances[0],
                "tfsa": balances[1],
                "nonreg": balances[2],
                "total": balances[0] + balances[1] + balances[2],
                "withdrawal": withdrawal,
                "rrif_min": rrif_min,
                "shortfall": shortfall,
                "tax_paid": tax_paid,
                "marginal_rate": marginal_rate,
                "effective_rate": effective_rate,
                "cpp": cpp,
                "oas": oas,
                "oas_clawback": oas_clawback,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------
def _percentiles(values: list[float], qs: tuple[int, ...] = (5, 25, 50, 75, 95)) -> dict[int, float]:
    """Nearest-rank percentiles of a sample."""
    if not values:
        return {q: 0.0 for q in qs}
    s = sorted(values)
    n = len(s)
    return {q: s[max(0, min(n - 1, math.ceil(q / 100.0 * n) - 1))] for q in qs}


def monte_carlo(p: PlanInputs, num_sims: int | None = None, seed: int | None = None) -> dict:
    """Run the projection under random annual returns and summarize percentiles.

    Returns a dict with success_pct, retirement/end-balance percentiles and
    per-year P5/P50/P95 totals (for the band chart).
    """
    num_sims = num_sims or p.num_sims
    rng = random.Random(p.seed if seed is None else seed)
    mu = math.log(1.0 + p.annual_return)
    sigma = p.volatility
    years = list(range(p.current_age, p.end_age + 1))
    start_year = date.today().year

    year_totals: dict[int, list[float]] = {off: [] for off in range(len(years))}
    retirement_balances: list[float] = []
    end_balances: list[float] = []
    success = 0

    for _ in range(num_sims):
        balances = (p.rrsp_balance, p.tfsa_balance, p.nonreg_balance)
        failed = False
        for offset, age in enumerate(years):
            # Lognormal annual return with mean p.annual_return and std p.volatility.
            r = math.exp(mu - 0.5 * sigma * sigma + sigma * rng.gauss(0.0, 1.0)) - 1.0
            balances, _wd, shortfall, _cpp, _oas, _target, _tax, _claw, _rrif, _marg, _eff = step_year(
                p, age, balances, r, offset, start_year + offset
            )
            year_totals[offset].append(balances[0] + balances[1] + balances[2])
            if shortfall > MONEY_EPS:
                failed = True
            if age == p.retirement_age:
                retirement_balances.append(balances[0] + balances[1] + balances[2])
        end_balances.append(balances[0] + balances[1] + balances[2])
        if not failed:
            success += 1

    total_pcts = {off: _percentiles(year_totals[off], (5, 50, 95)) for off in range(len(years))}
    return {
        "success_pct": success / num_sims * 100.0,
        "retirement_balance": _percentiles(retirement_balances),
        "end_balance": _percentiles(end_balances),
        "years": [start_year + off for off in range(len(years))],
        "total_p5": [total_pcts[off][5] for off in range(len(years))],
        "total_p50": [total_pcts[off][50] for off in range(len(years))],
        "total_p95": [total_pcts[off][95] for off in range(len(years))],
    }


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------
def _fmt_pct(x: float) -> str:
    return f"{x * 100.0:.2f}"


def build_result(p: PlanInputs, rows: list[dict], mc: dict) -> dict:
    """Combine inputs, summary, projection rows and Monte Carlo into one dict."""
    exhaustion_year = None
    for row in rows:
        if row["shortfall"] > MONEY_EPS:
            exhaustion_year = row["year"]
            break
    if exhaustion_year is not None:
        # The exhaustion year is the first year income could not be fully met,
        # so fully-covered years stop the year before.
        years_of_coverage = exhaustion_year - (p.retirement_age + date.today().year - p.current_age)
    else:
        years_of_coverage = p.end_age - p.retirement_age + 1

    det_ret = next(r["total"] for r in rows if r["age"] == p.retirement_age)
    det_end = rows[-1]["total"]
    qpp_first_year = p.qpp_monthly_at_65 * qpp_adjustment(p.qpp_start_age) * (1.0 + p.inflation_rate) ** max(0, p.qpp_start_age - p.current_age)
    oas_first_year = p.oas_monthly * oas_adjustment(p.oas_start_age) * (1.0 + p.inflation_rate) ** max(0, p.oas_start_age - p.current_age)
    ret_row = next(r for r in rows if r["age"] == p.retirement_age)
    marginal_at_retirement = round(ret_row["marginal_rate"] * 100.0, 2)
    effective_at_retirement = round(ret_row["effective_rate"] * 100.0, 2)

    summary = [
        # Inputs
        ("Current age", p.current_age),
        ("Retirement age", p.retirement_age),
        ("End age (life expectancy)", p.end_age),
        ("RRSP balance (CAD)", p.rrsp_balance),
        ("RRSP monthly contribution (CAD)", p.rrsp_monthly),
        ("TFSA balance (CAD)", p.tfsa_balance),
        ("TFSA monthly contribution (CAD)", p.tfsa_monthly),
        ("Non-registered balance (CAD)", p.nonreg_balance),
        ("Non-registered monthly contribution (CAD)", p.nonreg_monthly),
        ("Monthly meltdown (CAD)", p.monthly_meltdown),
        ("Annual return (%)", _fmt_pct(p.annual_return)),
        ("Inflation (%)", _fmt_pct(p.inflation_rate)),
        ("Return volatility, Monte Carlo (%)", _fmt_pct(p.volatility)),
        ("Contribution escalation (%)", _fmt_pct(p.contribution_escalation)),
        ("Target monthly income at retirement (today's CAD)", p.target_monthly_income),
        ("Income at end age (% of retirement income)", _fmt_pct(p.end_income_ratio)),
        ("QPP at 65 (% of maximum)", round(p.qpp_monthly_at_65 / QPP_MAX_AT_65_2025 * 100.0, 2)),
        ("QPP monthly at 65 (today's CAD)", p.qpp_monthly_at_65),
        ("QPP start age", p.qpp_start_age),
        ("QPP monthly at start age, first year (CAD)", round(qpp_first_year, 2)),
        ("OAS monthly at 65 (today's CAD)", p.oas_monthly),
        ("OAS start age", p.oas_start_age),
        ("OAS monthly at start age, first year (CAD)", round(oas_first_year, 2)),
        ("OAS clawback applied", "Yes" if p.oas_clawback else "No"),
        ("Tax model", "Progressive federal + Quebec brackets, 2026, indexed to inflation"),
        ("Marginal tax rate at retirement, first year (%)", marginal_at_retirement),
        ("Effective tax rate at retirement, first year (%)", effective_at_retirement),
        ("Monte Carlo simulations", p.num_sims),
        ("Monte Carlo seed", p.seed),
        # Results
        ("Balance at retirement, deterministic (CAD)", round(det_ret, 2)),
        ("Balance at end age, deterministic (CAD)", round(det_end, 2)),
        ("Balance at retirement, median of Monte Carlo (CAD)", round(mc["retirement_balance"][50], 2)),
        ("Balance at retirement, P5 of Monte Carlo (CAD)", round(mc["retirement_balance"][5], 2)),
        ("Balance at retirement, P95 of Monte Carlo (CAD)", round(mc["retirement_balance"][95], 2)),
        ("Balance at end age, median of Monte Carlo (CAD)", round(mc["end_balance"][50], 2)),
        ("Success rate: never ran out of money (%)", round(mc["success_pct"], 2)),
        ("Exhaustion year (deterministic)", exhaustion_year if exhaustion_year is not None else "None"),
        ("Years of income coverage", years_of_coverage),
        (
            f"RRIF conversion year (RRSP converted at {rrif_conversion_age(p)})",
            rrif_conversion_age(p) if p.end_age >= rrif_conversion_age(p) else "N/A (plan ends before conversion)",
        ),
    ]
    return {
        "inputs": {
            "current_age": p.current_age,
            "retirement_age": p.retirement_age,
            "end_age": p.end_age,
        },
        "summary": summary,
        "projection": rows,
        "montecarlo": mc,
    }


def compute_all(p: PlanInputs) -> dict:
    """Validate and compute the full result (deterministic + Monte Carlo)."""
    errs = validate(p)
    if errs:
        raise ValueError("; ".join(errs))
    return build_result(p, deterministic_projection(p), monte_carlo(p))
