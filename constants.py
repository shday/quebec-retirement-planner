"""Statutory constants and planning defaults for the Quebec retirement planner.

All monetary amounts are in Canadian dollars (CAD).

Sources (accessed 2025-08-30 / 2026-09-01):
- CPP maximum retirement pension at age 65 ($1,433.00, new benefits January
  2025), OAS maximum (65-74) July-September 2025 ($734.95), OAS deferral
  (+0.6%/month, up to +36% at 70) and OAS repayment (clawback) for 2026
  income (threshold $95,323, 15% recovery rate):
  Canada.ca "Maximum benefit amounts and related figures - CPP 2025 and
  OAS, July to September 2025":
  https://www.canada.ca/content/dam/canada/employment-social-development/migration/documents/assets/portfolio/docs/en/statistics/quarterly_report/isp-card-july-sept-2025-en.pdf
- QPP maximum at age 65, 2025 ($1,395.25) and QPP/CPP alignment since
  January 2024 giving identical start-age factors (-0.6%/month before 65,
  +0.7%/month after 65):
  https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan
  https://www.manulifewealth.ca/clients/en/viewpoints/investor-education/when-to-start-taking-cpp-qpp-and-oas-benefits
- QPP deferral extended to age 72 (2026): +0.7%/month continues past 70 to a
  maximum +58.8% for a pension starting at 72; applying later is allowed but
  the amount stops increasing after 72 (accessed 2026-09-01):
  https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan/what-age-should-you-apply-your-retirement-pension
- RRIF minimum withdrawal factors - prescribed under the Income Tax
  Regulations (Canada) section 7308; ages 71+ table below, ages under 71 use
  the formula 1 / (90 - age):
  https://catax.tools/rrif-minimum-withdrawal-calculator/
  https://www.moneysense.ca/save/retirement/rrif-and-lif-withdrawal-rates/
- Federal and Quebec 2026 income tax brackets, credit amounts and phase-outs:
  DT Max "Tax brackets and rates (2026)" (federal first bracket 14% - the 2026
  federal budget cut the lowest rate from 14.5% to 14% - up to $58,523; Quebec
  14/19/24/25.75 up to $54,345; 16.5% Quebec abatement of the basic federal
  tax):
  https://support.drtax.ca/dtmax/eng/kb/dtmax/Government%20documentation/brackets_t326.htm
  https://www.wealthsimple.com/en-ca/tool/tax-calculator/quebec
- 2026 credit base amounts (federal credit rate 14% in 2026 because the
  lowest bracket rate dropped to 14%; Quebec credits at 14%): basic personal
  $16,452 federal (phased down above $181,440 to $14,829 at $258,482) and
  $18,952 Quebec; age amount (65+) $9,208 federal (15% phase-out above
  $46,432, gone by ~$107,819) and $3,986 Quebec; federal pension income amount
  $2,000; Quebec retirement income amount $3,541:
  https://www.taxtips.ca/nrcredits/tax-credits-2026.htm
  https://www.taxtips.ca/qctax/quebec-tax-credits-and-deductions.htm
- Quebec line-361 credits (age $3,986 / living alone $2,172 / retirement income
  = eligible pension income x 1.25, max $3,541): the amounts are summed and
  reduced by 18.75% of the portion of family income above $42,955 (2026,
  indexed from the 2025 form's $42,090), with no entitlement once that portion
  exceeds $66,025 (single; indexed from the 2025 form's $64,699). The
  mechanics are printed directly on the 2025 Schedule B form (TP-1.D.B-V, the
  latest published - the 2026 form is not yet released, so its amounts and
  thresholds are indexed from it):
  https://www.revenuquebec.ca/documents/en/formulaires/tp/2025-12/TP-1.D.B-V%282025-12%29.pdf
  https://www.revenuquebec.ca/en/citizens/income-tax-return/completing-your-income-tax-return/how-to-complete-your-income-tax-return/line-by-line-help/350-to-398-1-non-refundable-tax-credits/line-361/
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# QPP - Quebec Pension Plan
# ---------------------------------------------------------------------------
QPP_MAX_AT_65_2025 = 1_395.25          # maximum monthly retirement pension at 65, 2025
QPP_EARLY_REDUCTION_PER_MONTH = 0.006  # -0.6%/month for each month before 65 (max 36% at 60)
QPP_LATE_INCREASE_PER_MONTH = 0.007    # +0.7%/month for each month after 65 (max 58.8% at 72)
QPP_MIN_START_AGE = 60
QPP_MAX_START_AGE = 72                 # deferral extended from 70 to 72 in 2026; no increase after 72

# ---------------------------------------------------------------------------
# OAS - Old Age Security (federal, applies in Quebec)
# ---------------------------------------------------------------------------
OAS_MAX_2025 = 734.95                  # maximum monthly OAS, age 65-74, July-September 2025 (indexed quarterly)
OAS_DEFERRAL_PER_MONTH = 0.006         # +0.6%/month deferred past 65, up to +36% at 70
OAS_DEFERRAL_MAX_AGE = 70
OAS_CLAWBACK_RATE = 0.15               # 15% recovery of income above threshold
OAS_CLAWBACK_THRESHOLD = 95_323.0      # 2026 net-world-income threshold (CRA figure based on 2026 income)
OAS_CLAWBACK_UPPER = 152_062.0         # 2026 full-clawback income, ages 65-74 (informational)

# ---------------------------------------------------------------------------
# RRIF mandatory minimum withdrawal factors by age (ITR s. 7308)
# ---------------------------------------------------------------------------
RRIF_MIN_FACTORS: dict[int, float] = {
    71: 0.0528, 72: 0.0540, 73: 0.0553, 74: 0.0567, 75: 0.0582,
    76: 0.0598, 77: 0.0617, 78: 0.0636, 79: 0.0658, 80: 0.0682,
    81: 0.0708, 82: 0.0738, 83: 0.0771, 84: 0.0808, 85: 0.0851,
    86: 0.0899, 87: 0.0955, 88: 0.1021, 89: 0.1099, 90: 0.1192,
    91: 0.1306, 92: 0.1449, 93: 0.1634, 94: 0.1879, 95: 0.2000,
}
RRIF_CONVERSION_AGE = 71               # RRSP must become an RRIF by Dec 31 of the year you turn 71
RRIF_CONVERSION_MIN_AGE = 55           # earliest conversion the model supports (ITR s. 7308 minimum factors are 0 before 55)
RRIF_EARLY_FACTOR_FORMULA = "1 / (90 - age)"  # applies to ages under 71 (early conversion)


def rrif_min_factor(age: int) -> float:
    """Mandatory RRIF minimum withdrawal factor for a given age (fraction)."""
    if age < RRIF_CONVERSION_AGE:
        if age < 55:
            return 0.0
        return 1.0 / (90 - age)          # early-conversion formula, ITR s. 7308
    return RRIF_MIN_FACTORS[min(age, 95)]


# ---------------------------------------------------------------------------
# Income tax - federal + Quebec, 2026 (indexed annually from this base year)
# ---------------------------------------------------------------------------
TAX_YEAR = 2026                     # base year for all tax amounts below

# Federal brackets (tax on taxable income). 14% first rate = the 2026
# federal budget cut of the lowest rate from 14.5%.
FEDERAL_BRACKETS_2026: list[tuple[float, float]] = [
    (0.14, 58_523.0),
    (0.205, 117_045.0),
    (0.26, 181_440.0),
    (0.29, 258_482.0),
    (0.33, float("inf")),
]
FEDERAL_CREDIT_RATE = 0.14           # non-refundable credits are at the lowest bracket rate (14% in 2026)
FEDERAL_BPA_2026 = 16_452.0          # basic personal amount
FEDERAL_BPA_PHASE_START = 181_440.0  # BPA phased down above this taxable income
FEDERAL_BPA_PHASE_END = 258_482.0    # BPA reaches its minimum here
FEDERAL_BPA_MIN = 14_829.0           # minimum BPA (2025 value 14,538 indexed by the 2026 factor)
FEDERAL_AGE_AMOUNT_2026 = 9_208.0    # age amount, 65+
FEDERAL_AGE_PHASE_START = 46_432.0   # net income where the age amount starts phasing
FEDERAL_AGE_PHASE_RATE = 0.15        # 15% of net income above the start is clawed back
FEDERAL_PENSION_AMOUNT_MAX = 2_000.0  # pension income amount: lesser of eligible pension income or this
FEDERAL_AGE_AMOUNT_ZERO_AT = FEDERAL_AGE_PHASE_START + FEDERAL_AGE_AMOUNT_2026 / FEDERAL_AGE_PHASE_RATE  # ~107,819

# Quebec brackets (tax on taxable income).
QUEBEC_BRACKETS_2026: list[tuple[float, float]] = [
    (0.14, 54_345.0),
    (0.19, 108_680.0),
    (0.24, 132_245.0),
    (0.2575, float("inf")),
]
QUEBEC_CREDIT_RATE = 0.14            # Quebec non-refundable credits are at 14%
QUEBEC_BPA_2026 = 18_952.0           # basic personal amount ("montant personnel de base")
# Line-361 credits (TP-1.D.B-V Schedule B; 2026 amounts indexed from the 2025
# form, the latest published):
# - Age amount for a person 65+ (line 22 of the form): $3,986.
# - Amount for retirement income (work chart): eligible pension income x 1.25,
#   maximum $3,541 - RRIF/annuity/RPP only, NOT QPP/CPP/OAS.
# - The age + retirement (+ living-alone $2,172, not modeled) amounts are
#   summed (line 30), then reduced by 18.75% of the portion of family income
#   above $42,955 (lines 16/18/31); no entitlement once line 18 exceeds the
#   single cutoff $66,025 (indexed from the 2025 form's $64,699).
QUEBEC_AGE_AMOUNT_2026 = 3_986.0     # age amount for a person 65+ (line 361)
QUEBEC_LIVING_ALONE_2026 = 2_172.0   # person-living-alone amount (line 20); not modeled (no marital-status input)
QUEBEC_RETIREMENT_AMOUNT_2026 = 3_541.0  # retirement income amount cap (work chart line 9)
QUEBEC_RETIREMENT_MULTIPLIER = 1.25      # work chart: eligible pension income x 1.25, max 3,541
QUEBEC_CREDIT_PHASE_START = 42_955.0     # family income where the line-361 credits start phasing out (form line 16)
QUEBEC_CREDIT_PHASE_RATE = 0.1875        # form line 31: "Amount from line 18 x 18.75%"
QUEBEC_CREDIT_NO_ENTITLEMENT_SINGLE = 66_025.0  # form: no credits if line 18 exceeds this (single)
QUEBEC_ABATEMENT_RATE = 0.165         # Quebec abatement: 16.5% of the basic federal tax (federal tax on taxable income AFTER non-refundable credits; the credits come first on Schedule 1, so the abatement reduces their value for QC residents)
RRIF_PENSION_CREDIT_ELIGIBLE_AGE = 71  # RRSP/RRIF withdrawals qualify for the pension-income credits only once the RRSP is a RRIF


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
DEFAULT_RRIF_CONVERSION_AGE = None      # None = convert the RRSP to an RRIF at the retirement age (statutory deadline 71)

# Tax
# (No user tax inputs: income tax is modeled automatically from the 2026
# federal + Quebec brackets and credits above, indexed to inflation.)

# Monte Carlo
DEFAULT_MONTE_CARLO_SIMS = 1_000
DEFAULT_SEED = 42
