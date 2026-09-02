"""Unit tests for the progressive income tax model (federal + Quebec, 2026)."""

import pytest

from constants import (
    FEDERAL_AGE_AMOUNT_2026,
    FEDERAL_BPA_2026,
    OAS_CLAWBACK_THRESHOLD,
    QUEBEC_AGE_AMOUNT_2026,
    QUEBEC_BPA_2026,
    QUEBEC_RETIREMENT_AMOUNT_2026,
)
from tax import (
    eligible_pension_income,
    federal_bracket_tax,
    federal_credits,
    income_tax,
    marginal_burden_rate,
    oas_recovery,
    quebec_bracket_tax,
    quebec_credits,
    scale,
)


# ---------------------------------------------------------------------------
# Bracket tax on taxable income
# ---------------------------------------------------------------------------
def test_federal_bracket_tax_2026():
    # 14% first bracket (2026 budget cut from 14.5%; DT Max/Wealthsimple).
    assert federal_bracket_tax(58_523) == pytest.approx(58_523 * 0.14)
    assert federal_bracket_tax(60_000) == pytest.approx(58_523 * 0.14 + 1_477 * 0.205)
    assert federal_bracket_tax(117_045) == pytest.approx(58_523 * 0.14 + 58_522 * 0.205)
    assert federal_bracket_tax(258_482) == pytest.approx(59_275.11, abs=0.01)
    assert federal_bracket_tax(0.0) == 0.0


def test_quebec_bracket_tax_2026():
    assert quebec_bracket_tax(54_345) == pytest.approx(54_345 * 0.14)
    assert quebec_bracket_tax(60_000) == pytest.approx(54_345 * 0.14 + 5_655 * 0.19)
    assert quebec_bracket_tax(132_245) == pytest.approx(23_587.55, abs=0.01)
    assert quebec_bracket_tax(0.0) == 0.0


def test_bracket_thresholds_are_indexed_by_year():
    # 2027 at 2% indexation: the thresholds scale by 1.02 (like the credits).
    scaled = 58_523.0 * 1.02
    assert federal_bracket_tax(75_000, 0.02, 2027) == pytest.approx(
        0.14 * scaled + 0.205 * max(0.0, 75_000 - scaled)
    )
    # Base year (2026) with no inflation is unchanged.
    assert federal_bracket_tax(75_000, 0.0, 2026) == federal_bracket_tax(75_000)
    # Higher thresholds push income into lower brackets, so indexed tax on a
    # FIXED income is lower than the unindexed tax.
    assert federal_bracket_tax(75_000, 0.02, 2027) < federal_bracket_tax(75_000, 0.0, 2026)


# ---------------------------------------------------------------------------
# Federal non-refundable credits (14% credit rate in 2026)
# ---------------------------------------------------------------------------
def test_federal_basic_personal_amount():
    assert federal_credits(40_000, 60, 0.0, 0.0, 2026) == pytest.approx(FEDERAL_BPA_2026 * 0.14)
    # Phased down above $181,440 to $14,829 at $258,482.
    assert federal_credits(258_482, 60, 0.0, 0.0, 2026) == pytest.approx(14_829 * 0.14)
    # Midway through the phase-out range.
    mid = (181_440 + 258_482) / 2
    expected = (FEDERAL_BPA_2026 + (14_829 - FEDERAL_BPA_2026) * 0.5) * 0.14
    assert federal_credits(mid, 60, 0.0, 0.0, 2026) == pytest.approx(expected)


def test_federal_age_amount_phase_out():
    full = FEDERAL_AGE_AMOUNT_2026 * 0.14
    assert federal_credits(30_000, 65, 0.0, 0.0, 2026) == pytest.approx(FEDERAL_BPA_2026 * 0.14 + full)
    # 15% of net income above $46,432 is clawed back; zero at ~$107,819.
    mid = 60_000
    reduced = FEDERAL_AGE_AMOUNT_2026 - 0.15 * (mid - 46_432)
    assert federal_credits(mid, 65, 0.0, 0.0, 2026) == pytest.approx(FEDERAL_BPA_2026 * 0.14 + reduced * 0.14)
    assert federal_credits(107_819, 65, 0.0, 0.0, 2026) == pytest.approx(FEDERAL_BPA_2026 * 0.14)
    assert federal_credits(200_000, 65, 0.0, 0.0, 2026) < FEDERAL_BPA_2026 * 0.14  # age credit gone, BPA phasing


def test_federal_age_credit_requires_age_65():
    assert federal_credits(30_000, 64, 0.0, 0.0, 2026) == pytest.approx(FEDERAL_BPA_2026 * 0.14)
    assert federal_credits(30_000, 65, 0.0, 0.0, 2026) > federal_credits(30_000, 64, 0.0, 0.0, 2026)


def test_federal_pension_income_amount():
    # Lesser of eligible pension income or $2,000, at 14%.
    assert federal_credits(40_000, 60, 5_000, 0.0, 2026) == pytest.approx(
        FEDERAL_BPA_2026 * 0.14 + 2_000 * 0.14
    )
    assert federal_credits(40_000, 60, 500, 0.0, 2026) == pytest.approx(
        FEDERAL_BPA_2026 * 0.14 + 500 * 0.14
    )
    # No eligible pension income -> no credit.
    assert federal_credits(40_000, 60, 0.0, 0.0, 2026) == pytest.approx(FEDERAL_BPA_2026 * 0.14)


# ---------------------------------------------------------------------------
# Quebec non-refundable credits (14% credit rate)
# ---------------------------------------------------------------------------
def test_quebec_basic_personal_amount():
    assert quebec_credits(30_000, 60, 0.0, 0.0, 2026) == pytest.approx(QUEBEC_BPA_2026 * 0.14)


def test_quebec_age_and_retirement_credits_phase_out():
    # Full credits below the $42,955 reduction threshold (Schedule B line 16).
    assert quebec_credits(30_000, 65, 5_000, 0.0, 2026) == pytest.approx(
        (QUEBEC_BPA_2026 + QUEBEC_AGE_AMOUNT_2026 + QUEBEC_RETIREMENT_AMOUNT_2026) * 0.14
    )
    # The form sums the age + retirement amounts, then reduces the TOTAL by
    # 18.75% of (family income - 42,955). Everything phases out together by
    # 42,955 + (3,986 + 3,541) / 0.1875 = ~83,099.
    total = QUEBEC_AGE_AMOUNT_2026 + QUEBEC_RETIREMENT_AMOUNT_2026
    assert quebec_credits(83_099, 65, 5_000, 0.0, 2026) == pytest.approx(QUEBEC_BPA_2026 * 0.14, abs=1.0)
    assert quebec_credits(200_000, 65, 5_000, 0.0, 2026) == pytest.approx(QUEBEC_BPA_2026 * 0.14)


def test_quebec_retirement_credit_uses_1_25_multiplier():
    # Work chart line 9 of TP-1.D.B-V: eligible pension income x 1.25, max $3,541.
    small = quebec_credits(30_000, 65, 1_000, 0.0, 2026)
    assert small == pytest.approx((QUEBEC_BPA_2026 + QUEBEC_AGE_AMOUNT_2026 + 1_000 * 1.25) * 0.14)
    large = quebec_credits(30_000, 65, 5_000, 0.0, 2026)
    assert large == pytest.approx((QUEBEC_BPA_2026 + QUEBEC_AGE_AMOUNT_2026 + QUEBEC_RETIREMENT_AMOUNT_2026) * 0.14)


def test_quebec_retirement_credit_requires_eligible_income():
    assert quebec_credits(30_000, 65, 0.0, 0.0, 2026) == pytest.approx(
        (QUEBEC_BPA_2026 + QUEBEC_AGE_AMOUNT_2026) * 0.14
    )


# ---------------------------------------------------------------------------
# Full income tax: credits + Quebec abatement
# ---------------------------------------------------------------------------
def test_income_tax_floors_at_zero():
    fed, qc = income_tax(10_000, 60, 0.0, 0.0, 2026)
    assert fed == 0.0 and qc == 0.0  # below both basic personal amounts


def test_income_tax_applies_quebec_abatement():
    # $60k, age 60: no age/pension credits. The abatement is 16.5% of the
    # basic federal tax, i.e. of the bracket tax AFTER credits are deducted
    # (credits come first on Schedule 1), so it reduces the value of credits
    # for Quebec residents (TaxTips "Refundable Quebec Federal Tax Abatement").
    fed_gross = federal_bracket_tax(60_000, 0.0, 2026)
    credits = FEDERAL_BPA_2026 * 0.14
    basic = fed_gross - credits
    fed_expected = basic - 0.165 * basic
    qc_expected = quebec_bracket_tax(60_000, 0.0, 2026) - QUEBEC_BPA_2026 * 0.14
    fed, qc = income_tax(60_000, 60, 0.0, 0.0, 2026)
    assert fed == pytest.approx(fed_expected)
    assert qc == pytest.approx(qc_expected)
    assert fed + qc == pytest.approx(11_200.40, abs=0.01)


# ---------------------------------------------------------------------------
# OAS recovery tax
# ---------------------------------------------------------------------------
def test_oas_recovery():
    assert oas_recovery(50_000, 8_819.40, 0.0, 2026) == 0.0
    excess = 100_000 - OAS_CLAWBACK_THRESHOLD
    assert oas_recovery(100_000, 8_819.40, 0.0, 2026) == pytest.approx(0.15 * excess)
    # Capped at OAS received.
    assert oas_recovery(500_000, 8_819.40, 0.0, 2026) == pytest.approx(8_819.40)


# ---------------------------------------------------------------------------
# Marginal burden rate and indexation
# ---------------------------------------------------------------------------
def test_marginal_burden_rate_within_bracket():
    # Age 60, no age/pension credits, income $60k: federal 20.5% (net of the
    # 16.5% abatement) + Quebec 19% = 36.12%.
    rate = marginal_burden_rate(60_000, 60, 0.0, 0.0, 0.0, 2026)
    assert rate == pytest.approx(0.205 * 0.835 + 0.19, abs=0.001)


def test_marginal_burden_rate_never_negative_or_absurd():
    for income in (0.0, 5_000, 60_000, 300_000):
        rate = marginal_burden_rate(income, 70, 10_000, 8_819.40, 0.0, 2026)
        assert 0.0 <= rate <= 0.95


def test_scale_indexes_2026_amounts():
    assert scale(16_452, 0.0, 2026) == 16_452
    assert scale(16_452, 0.02, 2027) == pytest.approx(16_452 * 1.02)
    assert scale(16_452, 0.02, 2026) == 16_452


def test_eligible_pension_income_from_conversion_age():
    assert eligible_pension_income(60, 10_000) == 0.0   # default conversion at 71: pre-71 RRSP withdrawal not eligible
    assert eligible_pension_income(70, 10_000) == 0.0
    assert eligible_pension_income(71, 10_000) == 10_000  # RRIF withdrawal qualifies
    assert eligible_pension_income(72, 0.0) == 0.0
    # Early conversion: RRIF payments qualify from the conversion age.
    assert eligible_pension_income(60, 10_000, 60) == 10_000
    assert eligible_pension_income(70, 10_000, 65) == 10_000
    assert eligible_pension_income(64, 10_000, 65) == 0.0
