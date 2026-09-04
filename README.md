# Quebec Retirement Planner (Streamlit)

A local web app for **Quebec** retirement planning. Enter your numbers in the
sidebar, review a year-by-year projection (deterministic + Monte Carlo range),
and download CSVs to import into **Google Sheets** manually.

- Accounts: **RRSP**, **TFSA**, non-registered
- Pensions: **QPP**, **OAS** — with statutory start-age adjustments
- Tax: automatic progressive income tax — federal + Quebec 2026 brackets with
  basic personal, age 65+ and pension-income credits, the Quebec abatement,
  and the OAS recovery tax (indexed to inflation)
- RRSP converts to a **RRIF** at the chosen conversion age (default: retirement age; statutory deadline 71) with mandatory minimum withdrawals (ITR s. 7308)
- Monte Carlo: 1,000 simulations, fixed seed, with a P5–P95 band chart
- **No Google API, no OAuth, no accounts** — everything runs locally; the CSVs
  are yours to upload wherever you like.

> Informational planning estimates only — **not financial advice**.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # or: .venv\Scripts\activate on Windows
pip install -r requirements.txt
streamlit run app.py
```

Your browser opens `http://localhost:8501`.

## Importing into Google Sheets

1. Click **Download projection.csv** (and optionally `summary.csv` and
   `montecarlo.csv`, or the combined `.zip`).
2. In Google Sheets: **File → Import → Upload** → select the CSV →
   **Insert new sheet(s)**. Each file becomes its own tab.
3. Numeric cells are detected automatically (raw numbers, no `$`). Optional:
   select balance columns → **Format → Number → Currency**.

## What the model does

Each year from your current age to your end age:

- **Working years** (`age < retirement age`): monthly contributions (escalated)
  are added to each account, then all balances grow at the assumed return.
- **Retirement years**: pensions are paid once started — QPP (adjusted for
  start age, index-linked) and OAS (deferred +36% if started at 70, +10% from
  age 75, optional clawback). The **income target declines linearly** from 100% at the
  retirement age down to the "income at end age" percentage at your end age
  (in today's dollars, then inflation-indexed). QPP and OAS are
  **fully taxable**; the remaining after-tax income need is withdrawn from
  **non-registered → RRSP/RRIF (tax-grossed-up) → TFSA**, with the RRSP/RRIF
  gross-up solved against the real progressive tax function.
- **Tax (automatic)**: income tax is computed each year from the **2026
  federal brackets (14%–33%)** and **Quebec brackets (14%–25.75%)**, indexed
  to your inflation assumption from 2026, minus non-refundable credits (basic
  personal amounts, age 65+ amounts, pension-income amounts on RRIF
  withdrawals) and the **Quebec abatement** (16.5% of the basic federal tax).
  The OAS recovery tax is applied separately. There are no tax inputs — the
  model does it all; the projection shows the resulting **marginal** and
  **effective** tax rates each year.
- **From the conversion age**: the RRSP is treated as an RRIF. The
  mandatory minimum withdrawal (ITR s. 7308 factor × opening balance — the
  early-conversion factor 1/(90−age) below 71) is a floor on the RRSP/RRIF
  withdrawal; if the minimum exceeds the income need, the after-tax surplus is
  reinvested in the TFSA (simplification). RRIF payments are also eligible
  pension income, so the pension-income tax credits apply from the conversion
  age.
- **Monthly meltdown (optional)**: a monthly amount (today's dollars,
  inflation-indexed) is deposited into the TFSA from retirement up to — but
  not including — the QPP start age. It is funded by RRIF withdrawals that are
  grossed up for tax (the savings land in the TFSA after tax), shrinking the
  RRIF so the mandatory minimums stop forcing extra taxable income once QPP/OAS
  cover most of the need (e.g., the default scenario's effective-rate jump at
  QPP start drops from 18.55% to ~15.6% with ~$550/month of savings).
- If accounts run out before your end age, the first shortfall year is flagged
  as the **exhaustion year**.

The **Monte Carlo** runs the same logic 1,000 times with annual returns drawn
from a lognormal distribution around your expected return and volatility, then
reports P5/P25/P50/P75/P95 balances and the **success rate** (never ran out of
money).

## Projection columns

`projection.csv` (and the app's projection table) has one row per year:

| Column | Meaning |
| --- | --- |
| Age, Year | Calendar year for each age |
| Income % | Retirement income target as a % of the retirement-age target (declines linearly) |
| Income target | Monthly income target for that year, inflation-indexed (CAD) |
| RRSP, TFSA, Non-registered | End-of-year account balances (CAD) |
| Total | Sum of the three accounts |
| Withdrawal | Gross cash withdrawn from accounts during the year (CAD) |
| RRIF minimum | Mandatory minimum RRSP/RRIF withdrawal for the year (0 before the conversion age) |
| Shortfall | Income need that could not be covered (0 if fully funded) |
| Tax paid | Federal + Quebec income tax on taxable income — QPP + gross OAS + RRSP/RRIF withdrawals (progressive brackets, credits, abatement); non-registered and TFSA untaxed |
| Marginal rate | Marginal income-tax + OAS-recovery rate on the year's taxable income (%) |
| Effective rate | (Tax paid + OAS clawback) ÷ taxable income (%) |
| QPP, OAS | Pension income for the year (OAS is net of clawback) |
| OAS clawback | Amount OAS was reduced by the recovery tax (0 if no clawback) |

## Inputs & where to get your real figures

| Input | Default | Source |
| --- | --- | --- |
| Target monthly income at retirement | $4,000 | Your own lifestyle estimate |
| Income at end age (% of retirement) | 60% (linear decline) | Your own assumption |
| QPP at 65 | 85% of maximum (≈$1,185.96/mo, 2025 max $1,395.25) | [Retraite Québec — your statement pension ÷ the maximum](https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan) |
| OAS monthly at 65 | $734.95 (2025 max, 65–74; $808.45 at 75+) | [Service Canada / your OAS statement](https://www.canada.ca/en/services/benefits/publicpensions/cpp/old-age-security.html) |
| RRSP → RRIF conversion age | At retirement (deadline 71) | Your own plan (early conversion earns the pension-income credits sooner) |
| Monthly meltdown | $0/mo (off) | Optional: save into the TFSA before QPP starts (funded by grossed-up RRIF withdrawals) |
| Income tax | Automatic (no inputs) | 2026 federal + Quebec brackets/credits, indexed to inflation |
| Return / inflation / volatility | 7% / 2.5% / 10% | Your own assumptions |

QPP start age 60–72 uses the statutory adjustment shared with CPP since the
January 2024 alignment: **−0.6%/month** before 65, **+0.7%/month** after 65 —
since 2026 the deferral runs to 72 (maximum **+58.8%**; CPP still caps at 70).
OAS can start at 65 or be deferred to 70 for **+36%**, and gets an automatic
**+10% top-up from age 75** (Budget 2022) on top of that.

## Simplifications & scope

- **Progressive income tax (automatic)**: 2026 federal (14%–33%) and Quebec
  (14%–25.75%) brackets on taxable income = QPP + gross OAS +
  RRSP/RRIF withdrawals; minus the basic personal amounts, age 65+ amounts,
  pension-income amounts (on RRIF withdrawals only) and the Quebec abatement
  (16.5% of the basic federal tax — the federal tax after non-refundable
  credits are deducted, which reduces the value of federal credits for Quebec
  residents). All amounts are indexed to your inflation
  assumption from the 2026 base year. The Quebec age ($3,986) and
  retirement-income (eligible income × 1.25, max $3,541) credits are summed
  and reduced by 18.75% of family income above $42,955, exactly as on the
  TP-1.D.B-V Schedule B form. Single-taxpayer approximations: "net family
  income" phase-outs use your own taxable income, and the Quebec living-alone
  credit ($2,172) is not modeled (no marital-status input; conservative). The
  RRSP/RRIF gross-up is solved against the real tax function (brackets,
  credits and the OAS recovery together) by a fixed-point iteration. Working
  years are not taxed (contributions only).
- **OAS clawback (ITA s. 180.2)**: 15% of net income above the threshold,
  capped at OAS received. The model indexes the threshold (2026: $95,323,
  based on 2026 income) to inflation each year and solves the clawback and the RRSP/RRIF
  withdrawal together to a fixed point (the clawback reduces OAS, raising the
  withdrawal and income). The income proxy uses CPP + gross OAS + the gross
  RRSP/RRIF withdrawal; it ignores untaxed non-registered/TFSA drawdown, and
  the real-world clawback is assessed on the previous year's income.
- Non-registered account gains are untaxed by default (capital-gains modeling
  is a future change). TFSA withdrawals are tax-free.
- Pensions are counted only from the retirement year onward.
- The income decline is linear in real (today's) dollars and one inflation rate
  is applied to all years (no healthcare-specific escalation).
- RRSP contributions stop at the conversion age (redirected to TFSA); TFSA room limits and
  GIS are not modeled.
- Published per-age pension maximums can differ slightly from factor-based
  estimates because of the CPP/QPP enhancement phase-in — always prefer your
  own figures from Retraite Québec / Service Canada.

## Sources

- [Canada.ca — Maximum benefit amounts and related figures, CPP 2025 and OAS July–September 2025](https://www.canada.ca/content/dam/canada/employment-social-development/migration/documents/assets/portfolio/docs/en/statistics/quarterly_report/isp-card-july-sept-2025-en.pdf)
- [Retraite Québec — Québec Pension Plan](https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan)
- [Manulife — When to start taking CPP/QPP and OAS](https://www.manulifewealth.ca/clients/en/viewpoints/investor-education/when-to-start-taking-cpp-qpp-and-oas-benefits)
- [RRIF minimum withdrawal factors — ITR s. 7308](https://catax.tools/rrif-minimum-withdrawal-calculator/) and [MoneySense](https://www.moneysense.ca/save/retirement/rrif-and-lif-withdrawal-rates/)
- OAS repayment (clawback) 2026 threshold: [Wealthsimple](https://www.wealthsimple.com/en-ca/learn/oas-clawback-explained)
- Federal/Quebec 2026 tax brackets, credits and abatement: [DT Max — Tax brackets and rates (2026)](https://support.drtax.ca/dtmax/eng/kb/dtmax/Government%20documentation/brackets_t326.htm), [TaxTips — 2026 Non-Refundable Credits](https://www.taxtips.ca/nrcredits/tax-credits-2026.htm), [TaxTips — Quebec credits & indexation](https://www.taxtips.ca/qctax/quebec-tax-credits-and-deductions.htm), [Wealthsimple — 2026 Quebec tax calculator](https://www.wealthsimple.com/en-ca/tool/tax-calculator/quebec), [Revenu Québec — Line 361](https://www.revenuquebec.ca/en/citizens/income-tax-return/completing-your-income-tax-return/how-to-complete-your-income-tax-return/line-by-line-help/350-to-398-1-non-refundable-tax-credits/line-361/), [Revenu Québec — Schedule B (TP-1.D.B-V)](https://www.revenuquebec.ca/documents/en/formulaires/tp/2025-12/TP-1.D.B-V%282025-12%29.pdf)

## Project layout

```
app.py            Streamlit UI (sidebar inputs, results, downloads)
projection.py     Deterministic model + seeded Monte Carlo (pure, testable)
tax.py            Progressive federal + Quebec income tax model (pure, testable)
export.py         Projection → CSV strings / zip bytes
constants.py      Statutory constants (RRIF minimums, QPP/OAS factors, tax 2026, defaults)
tests/            pytest suite (tax, model, export)
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```
