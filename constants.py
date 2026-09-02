"""Statutory constants and planning defaults for the Quebec retirement planner.

All monetary amounts are in Canadian dollars (CAD).

Sources (accessed 2025-08-30):
- CPP maximum retirement pension at age 65 ($1,433.00, new benefits January
  2025), OAS maximum (65-74) July-September 2025 ($734.95), OAS deferral
  (+0.6%/month, up to +36% at 70) and OAS repayment (clawback) range
  ($93,454-$151,959 for ages 65-74, 15% recovery rate):
  Canada.ca "Maximum benefit amounts and related figures - CPP 2025 and
  OAS, July to September 2025":
  https://www.canada.ca/content/dam/canada/employment-social-development/migration/documents/assets/portfolio/docs/en/statistics/quarterly_report/isp-card-july-sept-2025-en.pdf
- QPP (RPC) maximum at age 65, 2025 ($1,395.25) and QPP/CPP alignment since
  January 2024 giving identical start-age factors (-0.6%/month before 65,
  +0.7%/month after 65):
  https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan
  https://www.manulifewealth.ca/clients/en/viewpoints/investor-education/when-to-start-taking-cpp-qpp-and-oas-benefits
- QPP deferral extended to age 72 (2026): +0.7%/month continues past 70 to a
  maximum +58.8% for a pension starting at 72; applying later is allowed but
  the amount stops increasing after 72 (accessed 2026-09-01):
  https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan/what-age-should-you-apply-your-retirement-pension
- FERR (RRIF) minimum withdrawal factors - prescribed under the Income Tax
  Regulations (Canada) section 7308; ages 71+ table below, ages under 71 use
  the formula 1 / (90 - age):
  https://catax.tools/rrif-minimum-withdrawal-calculator/
  https://www.moneysense.ca/save/retirement/rrif-and-lif-withdrawal-rates/
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# QPP (RPC) - Quebec Pension Plan
# ---------------------------------------------------------------------------
QPP_MAX_AT_65_2025 = 1_395.25          # maximum monthly retirement pension at 65, 2025
QPP_EARLY_REDUCTION_PER_MONTH = 0.006  # -0.6%/month for each month before 65 (max 36% at 60)
QPP_LATE_INCREASE_PER_MONTH = 0.007    # +0.7%/month for each month after 65 (max 58.8% at 72)
QPP_MIN_START_AGE = 60
QPP_MAX_START_AGE = 72                 # deferral extended from 70 to 72 in 2026; no increase after 72

# ---------------------------------------------------------------------------
# OAS (PSV) - Old Age Security (federal, applies in Quebec)
# ---------------------------------------------------------------------------
OAS_MAX_2025 = 734.95                  # maximum monthly OAS, age 65-74, July-September 2025 (indexed quarterly)
OAS_DEFERRAL_PER_MONTH = 0.006         # +0.6%/month deferred past 65, up to +36% at 70
OAS_DEFERRAL_MAX_AGE = 70
OAS_CLAWBACK_RATE = 0.15               # 15% recovery of income above threshold
OAS_CLAWBACK_THRESHOLD = 93_454.0      # 2025 net-world-income threshold, ages 65-74
OAS_CLAWBACK_UPPER = 151_959.0         # 2025 full-clawback income, ages 65-74 (informational)

# ---------------------------------------------------------------------------
# FERR (RRIF) mandatory minimum withdrawal factors by age (ITR s. 7308)
# ---------------------------------------------------------------------------
FERR_MIN_FACTORS: dict[int, float] = {
    71: 0.0528, 72: 0.0540, 73: 0.0553, 74: 0.0567, 75: 0.0582,
    76: 0.0598, 77: 0.0617, 78: 0.0636, 79: 0.0658, 80: 0.0682,
    81: 0.0708, 82: 0.0738, 83: 0.0771, 84: 0.0808, 85: 0.0851,
    86: 0.0899, 87: 0.0955, 88: 0.1021, 89: 0.1099, 90: 0.1192,
    91: 0.1306, 92: 0.1449, 93: 0.1634, 94: 0.1879, 95: 0.2000,
}
FERR_CONVERSION_AGE = 71               # RRSP must become a FERR by Dec 31 of the year you turn 71
FERR_EARLY_FACTOR_FORMULA = "1 / (90 - age)"  # applies to ages under 71 (early conversion)


def ferr_min_factor(age: int) -> float:
    """Mandatory FERR minimum withdrawal factor for a given age (fraction)."""
    if age < FERR_CONVERSION_AGE:
        if age < 55:
            return 0.0
        return 1.0 / (90 - age)          # early-conversion formula, ITR s. 7308
    return FERR_MIN_FACTORS[min(age, 95)]


# ---------------------------------------------------------------------------
# Planning defaults (user-adjustable in the app)
# ---------------------------------------------------------------------------
# Personal
DEFAULT_CURRENT_AGE = 58
DEFAULT_RETIREMENT_AGE = 59
DEFAULT_END_AGE = 88                    # life expectancy

# Accounts (current balance + monthly contribution until retirement)
DEFAULT_RRSP_BALANCE = 1_000_000
DEFAULT_RRSP_MONTHLY = 0
DEFAULT_TFSA_BALANCE = 0
DEFAULT_TFSA_MONTHLY = 0
DEFAULT_NONREG_BALANCE = 0
DEFAULT_NONREG_MONTHLY = 0

# Assumptions
DEFAULT_ANNUAL_RETURN = 0.05           # nominal, before inflation
DEFAULT_INFLATION = 0.0225
DEFAULT_VOLATILITY = 0.05               # annual std dev of returns, Monte Carlo
DEFAULT_CONTRIBUTION_ESCALATION = 0.0   # annual growth of monthly contributions

# Retirement income
DEFAULT_TARGET_MONTHLY_INCOME = 4_750  # today's CAD
DEFAULT_END_INCOME_RATIO = 0.65         # income at end age, as a fraction of income at retirement
DEFAULT_QPP_START_AGE = 72
DEFAULT_OAS_START_AGE = 70
DEFAULT_OAS_CLAWBACK = True

# Tax
DEFAULT_TAX_RATE = 0.30                 # flat combined Quebec + federal effective rate on FERR/RRSP withdrawals

# Monte Carlo
DEFAULT_MONTE_CARLO_SIMS = 1_000
DEFAULT_SEED = 42
