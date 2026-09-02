"""Deterministic and Monte Carlo retirement projection for Quebec (RPC/PSV/REER/CELI/FERR).

The model is deliberately simple and transparent:
- Three accounts: RRSP (REER, pre-tax), TFSA (CELI, tax-free), non-registered.
- Pensions (only during retirement years): QPP (RPC) and OAS (PSV), both
  inflation-indexed from today, with statutory start-age adjustments and an
  optional OAS clawback approximation.
- RRSP converts to a FERR at 71 with mandatory minimum withdrawals
  (Income Tax Regulations s. 7308); any after-tax surplus from a minimum that
  exceeds the income need is reinvested in the TFSA (simplification).
- Withdrawals come from non-registered first, then RRSP/FERR (grossed up for
  tax at a flat effective rate), then TFSA.
- Retirement income needs decline linearly from 100% at the retirement age to
  a configurable percentage at the end age (in today's dollars), with
  inflation applied on top.
- Monte Carlo samples annual lognormal returns around the expected return and
  volatility, with a fixed seed for reproducibility.

This is an informational planning tool, not financial advice. Flat-tax and
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
    DEFAULT_INFLATION,
    DEFAULT_MONTE_CARLO_SIMS,
    DEFAULT_NONREG_BALANCE,
    DEFAULT_NONREG_MONTHLY,
    DEFAULT_OAS_CLAWBACK,
    DEFAULT_OAS_START_AGE,
    DEFAULT_QPP_START_AGE,
    DEFAULT_RETIREMENT_AGE,
    DEFAULT_RRSP_BALANCE,
    DEFAULT_RRSP_MONTHLY,
    DEFAULT_SEED,
    DEFAULT_TARGET_MONTHLY_INCOME,
    DEFAULT_TAX_RATE,
    DEFAULT_TFSA_BALANCE,
    DEFAULT_TFSA_MONTHLY,
    DEFAULT_VOLATILITY,
    FERR_CONVERSION_AGE,
    OAS_CLAWBACK_RATE,
    OAS_CLAWBACK_THRESHOLD,
    OAS_MAX_2025,
    OAS_DEFERRAL_MAX_AGE,
    OAS_DEFERRAL_PER_MONTH,
    QPP_EARLY_REDUCTION_PER_MONTH,
    QPP_LATE_INCREASE_PER_MONTH,
    QPP_MAX_AT_65_2025,
    QPP_MAX_START_AGE,
    QPP_MIN_START_AGE,
    ferr_min_factor,
)

MONEY_EPS = 1e-9


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
    qpp_monthly_at_65: float = QPP_MAX_AT_65_2025                  # user's age-65 estimate
    qpp_start_age: int = DEFAULT_QPP_START_AGE
    oas_monthly: float = OAS_MAX_2025                              # today's dollars, at 65
    oas_start_age: int = DEFAULT_OAS_START_AGE
    oas_clawback: bool = DEFAULT_OAS_CLAWBACK

    # Tax
    tax_rate: float = DEFAULT_TAX_RATE                             # flat effective rate on taxable income (RRSP/FERR + CPP + OAS)

    # Monte Carlo
    num_sims: int = DEFAULT_MONTE_CARLO_SIMS
    seed: int = DEFAULT_SEED


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
    ):
        if v < 0:
            errs.append(f"{label} cannot be negative.")
    for label, v in (
        ("Annual return", p.annual_return),
        ("Inflation", p.inflation_rate),
        ("Volatility", p.volatility),
        ("Contribution escalation", p.contribution_escalation),
        ("Tax rate", p.tax_rate),
    ):
        if not 0 <= v < 1:
            errs.append(f"{label} must be between 0% and 100%.")
    if not 0 <= p.end_income_ratio <= 1:
        errs.append("Income at end age must be between 0% and 100% of retirement income.")
    if not QPP_MIN_START_AGE <= p.qpp_start_age <= QPP_MAX_START_AGE:
        errs.append(f"QPP start age must be between {QPP_MIN_START_AGE} and {QPP_MAX_START_AGE}.")
    if p.oas_start_age not in (65, OAS_DEFERRAL_MAX_AGE):
        errs.append("OAS start age must be 65 or 70.")
    return errs


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
def _oas_after_clawback(
    p: PlanInputs,
    cpp_income: float,
    oas_gross: float,
    target_monthly: float,
    infl: float,
) -> tuple[float, float]:
    """Apply the OAS recovery tax (ITA s. 180.2); return (net_oas, clawback_amount).

    The recovery tax is 15% of net income above an inflation-indexed
    threshold, capped at the OAS received. Because the clawback reduces OAS,
    which raises the RRSP/FERR withdrawal (and with it income), the estimate
    is iterated to a fixed point.

    Approximation: income is proxied by CPP + gross OAS + the gross RRSP/FERR
    withdrawal needed to fund the after-tax target; untaxed non-registered and
    TFSA drawdowns are ignored, and the real-world clawback is assessed on the
    previous year's income.
    """
    if not p.oas_clawback:
        return oas_gross, 0.0
    threshold = OAS_CLAWBACK_THRESHOLD * infl  # threshold is indexed annually
    target_annual = target_monthly * 12.0
    oas_est = oas_gross
    clawback = 0.0
    for _ in range(5):
        pensions_received = cpp_income + oas_est
        gap_est = max(0.0, target_annual - pensions_received * (1.0 - p.tax_rate))
        rrsp_est = gap_est / (1.0 - p.tax_rate) if gap_est > 0.0 else 0.0
        taxable_income = cpp_income + oas_gross + rrsp_est  # gross OAS is part of net income
        excess = max(0.0, taxable_income - threshold)
        clawback = min(oas_gross, OAS_CLAWBACK_RATE * excess)
        oas_est = oas_gross - clawback
    return oas_est, clawback


def step_year(
    p: PlanInputs,
    age: int,
    balances: tuple[float, float, float],
    annual_return: float,
    year_offset: int,
) -> tuple[tuple[float, float, float], float, float, float, float, float, float, float, float]:
    """Advance one year for a given age.

    Returns (new_balances, withdrawal, shortfall, cpp_income, oas_income,
    target_monthly, tax_paid, oas_clawback, ferr_min) where balances is
    (rrsp, tfsa, nonreg) at the end of the previous year, withdrawal is gross
    cash leaving the accounts during the year, target_monthly is the
    inflation-indexed monthly income target (already reduced by the linear
    income decline), tax_paid is the flat-rate income tax on all taxable
    income (CPP + OAS + RRSP/FERR withdrawals — both pensions are fully
    taxable), oas_clawback is the amount OAS was reduced by, and ferr_min is
    the mandatory minimum RRSP/FERR withdrawal (0 before 71).
    """
    rrsp, tfsa, nonreg = balances
    working = age < p.retirement_age
    infl = (1.0 + p.inflation_rate) ** year_offset

    # FERR minimum is a percentage of the balance at the previous year-end.
    ferr_min = ferr_min_factor(age) * rrsp if age >= FERR_CONVERSION_AGE else 0.0

    # Contributions (only while working; RRSP closes at 71).
    if working:
        esc = (1.0 + p.contribution_escalation) ** year_offset
        rrsp_contrib = p.rrsp_monthly * 12.0 * esc
        if age < FERR_CONVERSION_AGE:
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
    cpp_income = oas_income = oas_clawback = 0.0
    if not working:
        if age >= p.qpp_start_age:
            cpp_income = p.qpp_monthly_at_65 * qpp_adjustment(p.qpp_start_age) * infl * 12.0
        if age >= p.oas_start_age:
            oas_gross = p.oas_monthly * oas_adjustment(p.oas_start_age) * infl * 12.0
            oas_income, oas_clawback = _oas_after_clawback(p, cpp_income, oas_gross, target_monthly, infl)

    # After-tax income gap: CPP and OAS are fully taxable at the flat rate, so
    # only their after-tax value covers the target; the rest comes from accounts.
    gap = 0.0
    if not working:
        pensions_after_tax = (cpp_income + oas_income) * (1.0 - p.tax_rate)
        gap = max(0.0, target_monthly * 12.0 - pensions_after_tax)

    withdrawal = 0.0
    shortfall = 0.0
    rrsp_gross = 0.0
    if gap > MONEY_EPS:
        # 1. Non-registered first (untaxed in this simplified model).
        take = min(nonreg, gap)
        nonreg -= take
        withdrawal += take
        gap -= take
        # 2. RRSP/FERR — gross up for tax; FERR minimum is a floor on the withdrawal.
        if gap > MONEY_EPS and rrsp > MONEY_EPS:
            gross_needed = gap / (1.0 - p.tax_rate)
            gross = min(rrsp, max(gross_needed, ferr_min))
            rrsp -= gross
            withdrawal += gross
            rrsp_gross += gross
            gap -= gross * (1.0 - p.tax_rate)
            if gap < 0.0:  # FERR minimum exceeded the need: reinvest the after-tax surplus
                tfsa += -gap
                gap = 0.0
        # 3. TFSA last (tax-free).
        if gap > MONEY_EPS:
            take = min(tfsa, gap)
            tfsa -= take
            withdrawal += take
            gap -= take
        shortfall = max(0.0, gap)
    elif ferr_min > MONEY_EPS:
        # No income gap (working past 71, or pensions cover the target), but the
        # FERR minimum is mandatory: withdraw it, reinvest the after-tax amount.
        gross = min(ferr_min, rrsp)
        rrsp -= gross
        withdrawal += gross
        rrsp_gross += gross
        tfsa += gross * (1.0 - p.tax_rate)

    # Income tax: flat rate on all taxable income — CPP + OAS + RRSP/FERR
    # withdrawals (both pensions are fully taxable in Canada).
    tax_paid = (cpp_income + oas_income + rrsp_gross) * p.tax_rate
    return (
        (rrsp, tfsa, nonreg),
        withdrawal,
        shortfall,
        cpp_income,
        oas_income,
        target_monthly,
        tax_paid,
        oas_clawback,
        ferr_min,
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
            ferr_min,
        ) = step_year(p, age, balances, p.annual_return, offset)
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
                "ferr_min": ferr_min,
                "shortfall": shortfall,
                "tax_paid": tax_paid,
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
            balances, _wd, shortfall, _cpp, _oas, _target, _tax, _claw, _ferr = step_year(p, age, balances, r, offset)
            year_totals[offset].append(balances[0] + balances[1] + balances[2])
            if shortfall > MONEY_EPS:
                failed = True
            if age == p.retirement_age:
                retirement_balances.append(balances[0] + balances[1] + balances[2])
        end_balances.append(balances[0] + balances[1] + balances[2])
        if not failed:
            success += 1

    start_year = date.today().year
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

    summary = [
        # Inputs
        ("Current age", p.current_age),
        ("Retirement age", p.retirement_age),
        ("End age (life expectancy)", p.end_age),
        ("RRSP (REER) balance (CAD)", p.rrsp_balance),
        ("RRSP (REER) monthly contribution (CAD)", p.rrsp_monthly),
        ("TFSA (CELI) balance (CAD)", p.tfsa_balance),
        ("TFSA (CELI) monthly contribution (CAD)", p.tfsa_monthly),
        ("Non-registered balance (CAD)", p.nonreg_balance),
        ("Non-registered monthly contribution (CAD)", p.nonreg_monthly),
        ("Annual return (%)", _fmt_pct(p.annual_return)),
        ("Inflation (%)", _fmt_pct(p.inflation_rate)),
        ("Return volatility, Monte Carlo (%)", _fmt_pct(p.volatility)),
        ("Contribution escalation (%)", _fmt_pct(p.contribution_escalation)),
        ("Target monthly income at retirement (today's CAD)", p.target_monthly_income),
        ("Income at end age (% of retirement income)", _fmt_pct(p.end_income_ratio)),
        ("QPP (RPC) monthly at 65 (today's CAD)", p.qpp_monthly_at_65),
        ("QPP (RPC) start age", p.qpp_start_age),
        ("QPP (RPC) monthly at start age, first year (CAD)", round(qpp_first_year, 2)),
        ("OAS (PSV) monthly at 65 (today's CAD)", p.oas_monthly),
        ("OAS (PSV) start age", p.oas_start_age),
        ("OAS (PSV) monthly at start age, first year (CAD)", round(oas_first_year, 2)),
        ("OAS (PSV) clawback applied", "Yes" if p.oas_clawback else "No"),
        ("Effective tax rate on taxable income (%)", _fmt_pct(p.tax_rate)),
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
            "FERR conversion year (RRSP converted at 71)",
            71 if p.end_age >= FERR_CONVERSION_AGE else "N/A (plan ends before 71)",
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
