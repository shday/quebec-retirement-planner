"""Progressive income tax for a single Quebec retiree: federal + Quebec.

The projection used to apply one flat "effective tax rate" to all taxable
income (RRSP/FERR withdrawals plus CPP (QPP) and OAS (PSV)). This module
replaces that with the statutory 2026 structure, indexed to inflation from the
2026 base year:

- Federal brackets (14% first rate after the 2026 budget cut, up to 33%)
  and Quebec brackets (14% to 25.75%).
- Non-refundable credits: basic personal amounts, age amount (65+), and the
  pension-income amounts (federal $2,000 / Quebec $3,541 on eligible pension
  income - FERR/RRIF withdrawals and annuities, NOT CPP/QPP/OAS; the Quebec
  amount is eligible income x 1.25, capped at $3,541, and the Quebec age +
  retirement amounts are summed and then reduced by 18.75% of family income
  above $42,955 per the TP-1.D.B-V Schedule B).
- The Quebec abatement: 16.5% of the basic federal tax (the federal tax on
  taxable income after non-refundable credits are deducted - the credits come
  first on Schedule 1), as applies to residents of Quebec.
- The OAS recovery tax (clawback, ITA s. 180.2) is computed here too so the
  withdrawal engine can solve the gross-up against the full marginal burden.

All amounts are CAD. All 2026 statutory values and their sources live in
constants.py; everything here is derived and pure (stdlib only), so the module
is unit-testable in isolation.

Single-taxpayer approximations (documented in README/HANDOFF):
- "Net family income" phase-outs (Quebec line-361 credits) use the taxpayer's
  own taxable income as a proxy for family income.
- The Quebec living-alone credit and non-registered income are not modeled.
"""

from __future__ import annotations

from constants import (
    FEDERAL_AGE_AMOUNT_2026,
    FEDERAL_AGE_PHASE_RATE,
    FEDERAL_AGE_PHASE_START,
    FEDERAL_BPA_2026,
    FEDERAL_BPA_MIN,
    FEDERAL_BPA_PHASE_END,
    FEDERAL_BPA_PHASE_START,
    FEDERAL_BRACKETS_2026,
    FEDERAL_CREDIT_RATE,
    FEDERAL_PENSION_AMOUNT_MAX,
    FERR_PENSION_CREDIT_ELIGIBLE_AGE,
    OAS_CLAWBACK_RATE,
    OAS_CLAWBACK_THRESHOLD,
    QUEBEC_ABATEMENT_RATE,
    QUEBEC_AGE_AMOUNT_2026,
    QUEBEC_BPA_2026,
    QUEBEC_BRACKETS_2026,
    QUEBEC_CREDIT_RATE,
    QUEBEC_CREDIT_NO_ENTITLEMENT_SINGLE,
    QUEBEC_CREDIT_PHASE_RATE,
    QUEBEC_CREDIT_PHASE_START,
    QUEBEC_RETIREMENT_AMOUNT_2026,
    QUEBEC_RETIREMENT_MULTIPLIER,
    TAX_YEAR,
)

_MARGINAL_STEP = 1_000.0  # income increment used for the numeric marginal rate


# ---------------------------------------------------------------------------
# Indexation
# ---------------------------------------------------------------------------
def scale(amount_base: float, inflation_rate: float, year: int) -> float:
    """Index a base-year statutory amount to a calendar year."""
    return amount_base * (1.0 + inflation_rate) ** (year - TAX_YEAR)


# ---------------------------------------------------------------------------
# Bracket tax on taxable income
# ---------------------------------------------------------------------------
def federal_bracket_tax(income: float, inflation_rate: float = 0.0, year: int = TAX_YEAR) -> float:
    """Federal tax on taxable income at the federal bracket rates (indexed)."""
    return _bracket_tax(income, FEDERAL_BRACKETS_2026, inflation_rate, year)


def quebec_bracket_tax(income: float, inflation_rate: float = 0.0, year: int = TAX_YEAR) -> float:
    """Quebec tax on taxable income at the Quebec bracket rates (indexed)."""
    return _bracket_tax(income, QUEBEC_BRACKETS_2026, inflation_rate, year)


def _bracket_tax(income: float, brackets: list[tuple[float, float]], inflation_rate: float, year: int) -> float:
    tax = 0.0
    prev = 0.0
    for rate, upper in brackets:
        upper_scaled = scale(upper, inflation_rate, year)
        if income <= prev:
            break
        tax += rate * (min(income, upper_scaled) - prev)
        prev = upper_scaled
    return max(0.0, tax)


# ---------------------------------------------------------------------------
# Non-refundable credits
# ---------------------------------------------------------------------------
def _clamp(value: float) -> float:
    return max(0.0, value)


def federal_credits(
    income: float,
    age: int,
    pension_income: float,
    inflation_rate: float,
    year: int,
) -> float:
    """Total federal non-refundable credits (dollars of credit)."""
    # Basic personal amount, phased down for high taxable income (RCGT Table I2).
    bpa = FEDERAL_BPA_2026
    if income > scale(FEDERAL_BPA_PHASE_START, inflation_rate, year):
        frac = (income - scale(FEDERAL_BPA_PHASE_START, inflation_rate, year)) / (
            scale(FEDERAL_BPA_PHASE_END, inflation_rate, year)
            - scale(FEDERAL_BPA_PHASE_START, inflation_rate, year)
        )
        # Phases linearly from the full amount down to the statutory minimum.
        bpa = FEDERAL_BPA_MIN + (FEDERAL_BPA_2026 - FEDERAL_BPA_MIN) * max(0.0, 1.0 - min(1.0, frac))
    credits = bpa

    # Age amount (65+): reduced by 15% of net income above the phase-in point.
    if age >= 65:
        age_amount = scale(FEDERAL_AGE_AMOUNT_2026, inflation_rate, year)
        excess = income - scale(FEDERAL_AGE_PHASE_START, inflation_rate, year)
        if excess > 0.0:
            age_amount = _clamp(age_amount - FEDERAL_AGE_PHASE_RATE * excess)
        credits += age_amount

    # Pension income amount: lesser of eligible pension income or the cap.
    # Eligible pension income = FERR withdrawals (age >= 71 in this model).
    if pension_income > 0.0:
        credits += min(pension_income, scale(FEDERAL_PENSION_AMOUNT_MAX, inflation_rate, year))

    return credits * FEDERAL_CREDIT_RATE


def quebec_credits(
    income: float,
    age: int,
    pension_income: float,
    inflation_rate: float,
    year: int,
) -> float:
    """Total Quebec non-refundable credits (dollars of credit)."""
    credits = scale(QUEBEC_BPA_2026, inflation_rate, year)

    # Line-361 amounts (age + retirement income; living-alone is not modeled -
    # the app has no marital-status input, so omitting it is conservative).
    # Per the TP-1.D.B-V Schedule B (Part B): sum the amounts, then reduce
    # the TOTAL by 18.75% of the portion of family income above $42,090.
    line361_total = 0.0
    if age >= 65:
        line361_total += scale(QUEBEC_AGE_AMOUNT_2026, inflation_rate, year)
    if pension_income > 0.0:
        # Work chart line 9: eligible pension income x 1.25, maximum $3,470.
        ret_amount = min(
            pension_income * QUEBEC_RETIREMENT_MULTIPLIER,
            scale(QUEBEC_RETIREMENT_AMOUNT_2026, inflation_rate, year),
        )
        line361_total += ret_amount

    if line361_total > 0.0:
        excess = income - scale(QUEBEC_CREDIT_PHASE_START, inflation_rate, year)
        if excess > 0.0:
            line361_total = max(0.0, line361_total - QUEBEC_CREDIT_PHASE_RATE * excess)
            # Not entitled to any of these amounts once line 18 of Schedule B
            # (income minus the threshold) exceeds the single cutoff (the
            # phase-out above normally zeroes the credits first).
            if excess > scale(QUEBEC_CREDIT_NO_ENTITLEMENT_SINGLE, inflation_rate, year):
                line361_total = 0.0
        credits += line361_total

    return credits * QUEBEC_CREDIT_RATE


# ---------------------------------------------------------------------------
# Full income tax
# ---------------------------------------------------------------------------
def income_tax(
    taxable_income: float,
    age: int,
    pension_income: float,
    inflation_rate: float,
    year: int,
) -> tuple[float, float]:
    """Federal and Quebec income tax payable after credits and the abatement.

    Returns (federal_payable, quebec_payable); both floored at zero.

    The Quebec abatement is 16.5% of the *basic federal tax*, i.e. of the
    federal tax computed AFTER the non-refundable credits are deducted (the
    credits come first in the Act and on Schedule 1; the abatement then
    effectively reduces the value of federal credits for Quebec residents).
    """
    fed_gross = federal_bracket_tax(taxable_income, inflation_rate, year)
    credits = federal_credits(taxable_income, age, pension_income, inflation_rate, year)
    basic_federal = max(0.0, fed_gross - credits)
    fed = max(0.0, basic_federal - QUEBEC_ABATEMENT_RATE * basic_federal)

    qc = max(
        0.0,
        quebec_bracket_tax(taxable_income, inflation_rate, year)
        - quebec_credits(taxable_income, age, pension_income, inflation_rate, year),
    )
    return fed, qc


# ---------------------------------------------------------------------------
# OAS recovery tax (clawback)
# ---------------------------------------------------------------------------
def oas_recovery(taxable_income: float, oas_gross: float, inflation_rate: float, year: int) -> float:
    """OAS recovery tax (ITA s. 180.2): 15% of income above the indexed
    threshold, capped at the gross OAS received."""
    threshold = scale(OAS_CLAWBACK_THRESHOLD, inflation_rate, year)
    excess = max(0.0, taxable_income - threshold)
    return min(oas_gross, OAS_CLAWBACK_RATE * excess)


# ---------------------------------------------------------------------------
# Marginal rate on additional taxable income
# ---------------------------------------------------------------------------
def total_tax_burden(
    taxable_income: float,
    age: int,
    pension_income: float,
    oas_gross: float,
    inflation_rate: float,
    year: int,
) -> float:
    """Income tax plus OAS recovery - the full burden of an extra taxable dollar."""
    fed, qc = income_tax(taxable_income, age, pension_income, inflation_rate, year)
    return fed + qc + oas_recovery(taxable_income, oas_gross, inflation_rate, year)


def marginal_burden_rate(
    taxable_income: float,
    age: int,
    pension_income: float,
    oas_gross: float,
    inflation_rate: float,
    year: int,
) -> float:
    """Numeric marginal rate of the total tax burden at a given income level."""
    low = max(0.0, taxable_income - _MARGINAL_STEP)
    high = taxable_income + _MARGINAL_STEP
    burden_low = total_tax_burden(low, age, pension_income, oas_gross, inflation_rate, year)
    burden_high = total_tax_burden(high, age, pension_income, oas_gross, inflation_rate, year)
    return max(0.0, min(0.95, (burden_high - burden_low) / (high - low)))


def eligible_pension_income(age: int, rrsp_gross: float, conv_age: int = FERR_PENSION_CREDIT_ELIGIBLE_AGE) -> float:
    """Portion of the RRSP/FERR withdrawal that counts for the pension-income
    credits: only FERR (RRIF) payments qualify, i.e. from the conversion age
    onward; lump-sum RRSP withdrawals (before conversion) and CPP/QPP/OAS do
    not."""
    if age >= conv_age:
        return max(0.0, rrsp_gross)
    return 0.0
