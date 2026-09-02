# Quebec Retirement Planner (Streamlit)

A local web app for **Quebec** retirement planning. Enter your numbers in the
sidebar, review a year-by-year projection (deterministic + Monte Carlo range),
and download CSVs to import into **Google Sheets** manually.

- Accounts: **REER (RRSP)**, **CELI (TFSA)**, non-registered
- Pensions: **RPC (QPP)**, **PSV (OAS)** — with statutory start-age adjustments
- Tax: flat effective rate on REER/FERR withdrawals (Quebec + federal combined)
- RRSP converts to a **FERR** at 71 with mandatory minimum withdrawals (ITR s. 7308)
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
  start age, index-linked) and OAS (deferred +36% if started at 70, optional
  clawback). The **income target declines linearly** from 100% at the
  retirement age down to the "income at end age" percentage at your end age
  (in today's dollars, then inflation-indexed). CPP (RPC) and OAS (PSV) are
  **fully taxable**, so only their after-tax value counts toward the target;
  the remaining after-tax gap is withdrawn from
  **non-registered → REER/FERR (tax-grossed-up) → CELI**.
- **Age 71+**: the RRSP is treated as a FERR. The mandatory minimum withdrawal
  (ITR s. 7308 factor × opening balance) is a floor on the REER/FERR
  withdrawal; if the minimum exceeds the income need, the after-tax surplus is
  reinvested in the TFSA (simplification).
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
| FERR minimum | Mandatory minimum RRSP/FERR withdrawal for the year (0 before 71) |
| Shortfall | Income need that could not be covered (0 if fully funded) |
| Tax paid | Income tax on all taxable income — CPP (RPC) + OAS (PSV) + RRSP/FERR withdrawals (flat effective rate); non-registered and TFSA untaxed |
| CPP (RPC), OAS (PSV) | Pension income for the year (OAS is net of clawback) |
| OAS clawback | Amount OAS was reduced by the recovery tax (0 if no clawback) |

## Inputs & where to get your real figures

| Input | Default | Source |
| --- | --- | --- |
| Target monthly income at retirement | $4,000 | Your own lifestyle estimate |
| Income at end age (% of retirement) | 60% (linear decline) | Your own assumption |
| QPP (RPC) monthly at 65 | $1,395.25 (2025 max) | [Retraite Québec — use your own statement figure](https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan) |
| OAS (PSV) monthly at 65 | $734.95 (2025 max, 65–74) | [Service Canada / your OAS statement](https://www.canada.ca/en/services/benefits/publicpensions/cpp/old-age-security.html) |
| Tax rate on taxable income | 30% effective (combined QC+fed) | Set your own marginal/effective rate |
| Return / inflation / volatility | 7% / 2.5% / 10% | Your own assumptions |

QPP start age 60–72 uses the statutory adjustment shared with CPP since the
January 2024 alignment: **−0.6%/month** before 65, **+0.7%/month** after 65 —
since 2026 the deferral runs to 72 (maximum **+58.8%**; CPP still caps at 70).
OAS can start at 65 or be deferred to 70 for **+36%**.

## Simplifications & scope

- **Flat effective tax rate** on all taxable income — RRSP/FERR withdrawals
  plus CPP (RPC) and OAS (PSV), both of which are fully taxable in Canada; no
  marginal brackets, no provincial breakdown. Non-registered account gains are
  untaxed by default. TFSA withdrawals are tax-free.
- OAS clawback (ITA s. 180.2): 15% of net income above the threshold, capped
  at OAS received. The model indexes the threshold (2025: $93,454, ages
  65–74) to inflation each year and iterates the estimate to a fixed point
  (the clawback reduces OAS, raising the RRSP/FERR withdrawal and income).
  The income proxy uses CPP + gross OAS + the estimated gross RRSP/FERR
  withdrawal; it ignores untaxed non-registered/TFSA drawdown, and the
  real-world clawback is assessed on the previous year's income.
- Pensions are counted only from the retirement year onward.
- The income decline is linear in real (today's) dollars and one inflation rate
  is applied to all years (no healthcare-specific escalation).
- RRSP contributions stop at 71 (redirected to TFSA); TFSA room limits and
  GIS are not modeled.
- Published per-age pension maximums can differ slightly from factor-based
  estimates because of the CPP/QPP enhancement phase-in — always prefer your
  own figures from Retraite Québec / Service Canada.

## Sources

- [Canada.ca — Maximum benefit amounts and related figures, CPP 2025 and OAS July–September 2025](https://www.canada.ca/content/dam/canada/employment-social-development/migration/documents/assets/portfolio/docs/en/statistics/quarterly_report/isp-card-july-sept-2025-en.pdf)
- [Retraite Québec — Québec Pension Plan](https://www.retraitequebec.gouv.qc.ca/en/citizens/retirement-planning/applying-your-retirement-pension/retirement-pension-quebec-pension-plan)
- [Manulife — When to start taking CPP/QPP and OAS](https://www.manulifewealth.ca/clients/en/viewpoints/investor-education/when-to-start-taking-cpp-qpp-and-oas-benefits)
- [FERR (RRIF) minimum withdrawal factors — ITR s. 7308](https://catax.tools/rrif-minimum-withdrawal-calculator/) and [MoneySense](https://www.moneysense.ca/save/retirement/rrif-and-lif-withdrawal-rates/)
- OAS repayment (clawback) 2025 threshold: [Wealthsimple](https://www.wealthsimple.com/en-ca/learn/oas-clawback-explained)

## Project layout

```
app.py            Streamlit UI (sidebar inputs, results, downloads)
projection.py     Deterministic model + seeded Monte Carlo (pure, testable)
export.py         Projection → CSV strings / zip bytes
constants.py      Statutory constants (FERR minimums, QPP/OAS factors, defaults)
tests/            pytest suite (model + export)
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```
