# HANDOFF — Quebec Retirement Planner

Quick-start brief for anyone (or any fresh AI session) picking up this project.
All the important decisions, model rules, and current state are here; the
README covers user-facing setup; this file covers the developer-facing picture.

## What this is

A **local Streamlit web app** for Quebec retirement planning. The user enters
inputs in the sidebar; the app computes a deterministic year-by-year projection
plus a seeded 1,000-simulation Monte Carlo; and the user **downloads CSVs**
(`projection.csv`, `summary.csv`, `montecarlo.csv` or one `.zip`) to import
manually into Google Sheets. There is deliberately **no Google API, no OAuth,
no accounts** — the user rejected auto-save to Google in favor of manual CSV
import. All amounts are CAD.

## How to run & test

```bash
source .venv/bin/activate        # Python 3.14.2; streamlit 1.62.0, plotly 7.0.0, pytest 9.1.1
streamlit run app.py             # opens http://localhost:8501
python -m pytest -q              # 43 tests, all passing
```

Dependencies: `requirements.txt` (streamlit, plotly) and
`requirements-dev.txt` (+ pytest).

## File map

| File | Role |
| --- | --- |
| `app.py` | Streamlit UI: sidebar inputs + an "editing plan" selector, three tabs (Your plan / Spouse's plan / Combined). Each plan tab shows the 5 metric cards, Plotly band chart (deterministic stacked bars by account + P5–P95 band), projection dataframe, Monte Carlo table, download buttons. Per-person inputs use unique widget keys (`{person}__field`) so both people's numbers persist; shared assumptions are entered once. The Combined tab is `household.py` output. No tax inputs — the tax section is an informational caption. |
| `projection.py` | The model. `PlanInputs` (frozen dataclass), `validate()`, `qpp_adjustment()`, `oas_adjustment()`, `income_fraction()`, `rrif_conversion_age()` (resolves the RRSP→RRIF conversion age: default = retirement age, deadline 71), `_solve_rrsp_gross()` (fixed-point gross-up against the real tax function), `step_year()` (single-year engine shared by deterministic + MC; returns a 12-tuple including tax paid, OAS clawback, RRIF minimum, marginal/effective rates, meltdown gross), `deterministic_projection()`, `monte_carlo()`, `build_result()`, `compute_all()`. Pure stdlib (no numpy). Single-person only — unchanged by the household feature. |
| `household.py` | Pure (stdlib) two-person combination of two independent plan results. `household_projection()` merges the two deterministic projections on a common calendar-year axis and sums balances/pension income/withdrawals/tax/income target; past a person's end age their balances carry forward at the last modeled value while they contribute no further income. `household_montecarlo()` sums the two plans' independent P5/P50/P95 bands (indicative, not a joint simulation). `total_series()`, `first_shortfall_year()` helpers. |
| `tax.py` | The income tax model (pure, stdlib): `scale()` (base-year → year indexation), `federal_bracket_tax()` / `quebec_bracket_tax()`, `federal_credits()` / `quebec_credits()` (basic personal, age 65+, pension-income; phase-outs), `income_tax()` (returns fed/QC payable after credits and the Quebec abatement), `oas_recovery()` (clawback), `marginal_burden_rate()` (numeric marginal of income tax + recovery), `eligible_pension_income()` (RRIF payments only, from the conversion age). Single-taxpayer only — unchanged by the household feature. |
| `constants.py` | Statutory constants with cited sources: RRIF minimum factors, QPP/OAS adjustment rules, 2025 pension maxima, 2026 federal/Quebec tax brackets, credits and phase-outs, planning defaults. |
| `export.py` | `projection_csv()`, `summary_csv()`, `montecarlo_csv()`, `zip_bytes()`, plus `household_projection_csv()`. Raw numeric cells (2 decimals, no thousands separators) so Google Sheets imports them as numbers. |
| `tests/` | `test_tax.py` (17 tests: brackets, credits/phase-outs, abatement, recovery, marginal rate, indexation), `test_projection.py` (model math, tax/clawback columns, exhaustion, validation, end-to-end), `test_household.py` (identical plans double columns; differing horizons align by calendar year with balance carry-forward; shortfall; MC sums), `test_export.py` (CSV layout/values, shortfall rows, zip contents, household CSV). |
| `README.md` | User setup, Google Sheets import steps, model explanation, sources. |
| `conftest.py` | Empty; makes project root importable for pytest. |

## The model (what `step_year` does each year)

Ages run `current_age → end_age`; `year_offset = age - current_age`;
`year = date.today().year + offset` (note: the machine clock is 2026).

1. **RRIF minimum** = `rrif_min_factor(age) × RRSP opening balance` from the
   conversion age onward (`rrif_conversion_age(p)`: the user's choice or the
   retirement age, capped at the statutory deadline of 71; the factor table is
   in `constants.py`, ITR s. 7308 — ages under 71 use `1/(90 − age)`).
2. **Contributions** (only while `age < retirement_age`): monthly × 12 ×
   `(1 + escalation)^offset`. RRSP contributions stop at the conversion age
   (RRSP is closed); from then the RRSP monthly amount is redirected to TFSA.
3. **Growth**: each balance × `(1 + annual_return)`.
4. **Pensions** (only in retirement years — a deliberate simplification): QPP
   = user's age-65 figure × `qpp_adjustment(start_age)` × `(1+inflation)^offset`
   × 12; OAS similarly with `oas_adjustment()` and optional clawback, plus the
   **+10% age-75 top-up** (`OAS_SUPPLEMENT_AT_75`) applied once `age ≥ 75`.
   Both start only at their start age and only at/after retirement age. The app's
   QPP input is **% of the maximum at 65** (default 85%); the model stores the
   derived monthly dollars in `qpp_monthly_at_65`.
5. **Income need** (retirement years): the monthly target declines linearly via
   `income_fraction(p, age)` from 1.0 at `retirement_age` to
   `end_income_ratio` (default 0.65) at `end_age`, inflation-indexed.
6. **Taxation** (automatic, no inputs — see `tax.py`): taxable income =
   `CPP + gross OAS + RRSP/RRIF withdrawal` (gross OAS is taxable even when
   clawed back). Tax = federal brackets (2026: 14/20.5/26/29/33%) + Quebec
   brackets (14/19/24/25.75%) on taxable income, minus non-refundable credits
   (basic personal $16,452 fed / $18,952 QC at 14%/14%; age 65+ $9,208 fed
   / $3,986 QC with phase-outs; pension-income $2,000 fed / $3,541 QC on RRIF
   withdrawals only) and the Quebec abatement (16.5% of the basic federal
   tax). All 2026 amounts are indexed by `(1+inflation)^(year − 2026)`.
7. **Withdrawals** (retirement years): non-registered first (untaxed in this
   model) → RRSP/RRIF grossed up by `_solve_rrsp_gross()` — a Newton-style
   fixed point on the *marginal burden rate* (income tax + OAS recovery) that
   solves `CPP + net OAS + gross − tax = after-tax need` (converges to
   <$0.01, clamped to the RRSP balance) — with the RRIF minimum as a **floor**
   on the RRIF withdrawal (if the minimum exceeds the need, the after-tax
   surplus is reinvested in TFSA) → TFSA last. **Monthly meltdown**
   (optional `monthly_meltdown`, today's CAD/month, inflation-indexed): in
   retirement years before QPP starts (`age < qpp_start_age`) the savings
   target is added to the after-tax need the RRIF solve targets
   (`after-tax need = spending + savings`), so the RRIF withdrawal is grossed
   up for tax and the savings are deposited in the TFSA via the surplus logic
   (spending is covered first). The row also reports `meltdown_gross`: the
   portion of that year's gross RRIF withdrawal that funds the meltdown (the
   spending-only gross is solved separately with the same tax function and
   clamps, then subtracted, so `withdrawal − meltdown_gross` equals the
   no-meltdown withdrawal). If accounts run dry, `shortfall` records the unmet gap
   for that year (first such year = the **exhaustion year**). If the need is
   already covered but an RRIF minimum exists (working past the conversion
   age, or pensions cover the target after tax), the minimum is still
   withdrawn and its after-tax amount goes to TFSA.
8. **Monte Carlo**: 1,000 sims, `random.Random(seed=42)`, lognormal annual
   returns `exp(ln(1+r) − 0.5σ² + σ·z) − 1`. Tracks per-year total balances
   (for the P5–P95 band), balance at retirement age, balance at end age, and
   success = never had `shortfall > 0`. Percentiles are nearest-rank.
9. **Detail columns** (each projection row): `tax_paid` (federal + Quebec
   income tax on taxable income), `oas_clawback` (gross OAS − net OAS),
   `rrif_min` (mandatory minimum RRSP/RRIF withdrawal, 0 before the
   conversion age),
   `marginal_rate` (marginal income-tax+recovery rate on the year's income),
   `effective_rate` = `(tax_paid + oas_clawback) / taxable`, and
   `meltdown_gross` (0 when the meltdown is off or after QPP starts).
   `step_year` returns a 12-tuple:
   `(balances, withdrawal, shortfall, cpp, oas, target_monthly, tax_paid,
   oas_clawback, rrif_min, marginal_rate, effective_rate, meltdown_gross)`.

## Key statutory values (all sourced in `constants.py`)

- QPP max at 65, 2025: **$1,395.25** (app input is % of max, default 85% →
  ~$1,185.96/mo). Start 60–72: −0.6%/month before 65, +0.7%/month after 65
  (CPP-aligned rates since Jan 2024) → factors 0.64 at 60, 1.0 at 65, 1.42 at
  70, 1.588 at 72. Since 2026, QPP deferral runs to 72 (max +58.8%); CPP still
  caps at 70.
- OAS max 65–74, 2025: **$734.95** (indexed quarterly); 75+ **$808.45** with the
  +10% top-up (Budget 2022) that the model applies from `OAS_SUPPLEMENT_AGE`.
  Defer to 70 = +36%.
  Clawback (ITA s. 180.2): 15% of net income above the threshold (2026:
  $95,323, based on 2026 income), capped at OAS. The model
  **indexes the threshold to inflation** each year and **solves the clawback
  and the RRSP/RRIF withdrawal together to a fixed point** (clawback → lower
  OAS → higher withdrawal → higher income → higher clawback). Income proxy =
  CPP + gross OAS + gross RRSP/RRIF withdrawal; ignores untaxed
  non-registered/TFSA drawdown and the real-world one-year assessment lag
  (documented approximation).
- RRIF minimum factors: 71→5.28%, 72→5.40%, 73→5.53% … 94→18.79%, 95+→20.00%
  (ITR s. 7308; ages < 71 use `1/(90 − age)`). The RRSP converts to an RRIF at
  the conversion age (default: retirement age, e.g. 59; deadline 71) — RRIF
  payments then qualify for the pension-income credits, and the minimums (and
  TFSA redirect of RRSP contributions) start from that age.
- Income tax, 2026 (all in `constants.py`, sourced to DT Max/TaxTips/
  Wealthsimple/Revenu Québec): federal brackets 14%→$58,523 (2026 budget cut
  from 14.5%), 20.5%→$117,045, 26%→$181,440, 29%→$258,482, 33%+; Quebec
  14%→$54,345, 19%→$108,680, 24%→$132,245, 25.75%+. Credit rate 14% federal
  (follows the lowest bracket) / 14% Quebec. BPA $16,452 fed (phased to
  $14,829 over $181,440–$258,482) / $18,952 QC. Age 65+ $9,208 fed (15%
  phase-out above $46,432, gone at ~$107,819) / $3,986 QC. Pension income
  $2,000 fed / $3,541 QC on RRIF withdrawals only. Quebec abatement 16.5% of
  the basic federal tax — i.e. of the federal tax AFTER non-refundable
  credits are deducted (credits come first on Schedule 1, so the abatement
  reduces the value of federal credits for QC residents; verified against
  TaxTips and calculqc.ca).
- Quebec line-361 credits — mechanics VERIFIED against the actual Schedule B
  form (TP-1.D.B-V 2025-12, downloaded and read 2026-09-01; the 2026 form is
  not yet released, so 2026 amounts are indexed from it): the age ($3,986)
  and retirement-income (eligible pension income × 1.25, max $3,541) amounts
  are summed, then reduced by **18.75% of (family income − $42,955)** (form
  lines 18/30/31); no entitlement once that excess exceeds $66,025 (single;
  indexed). The living-alone amount ($2,172) is intentionally not modeled (no
  marital-status input). "Family income" is proxied by the taxpayer's own
  taxable income.
- Defaults: return 5%, inflation 2.25%, volatility 5%, escalation 0%, income
  at end age 65% (linear decline), monthly meltdown $500/mo, target monthly
  income $5,000, 1,000 sims, seed 42. No tax default — tax is automatic.

## Locked-in decisions (do not silently change without asking)

- **Streamlit + Plotly** app, thin UI over pure functions.
- **CSV manual import** to Google Sheets — no Google integration by design.
- **RRSP → RRIF at the retirement age by default** (conversion age
  user-adjustable 55–71, capped at the statutory deadline of 71); the
  pension-income credits, RRIF minimums and RRSP-contribution redirect all
  start at the conversion age.
- **Monthly meltdown is optional and pre-QPP**:
  `monthly_meltdown` (today's CAD/month, inflation-indexed) funds a TFSA
  deposit from RRIF withdrawals in retirement years with `age < qpp_start_age`
  only; the RRIF withdrawal is grossed up for tax so the full target lands in
  the TFSA; default $500/mo (0 = off).
- **Quebec-specific**: QPP, OAS, RRSP/TFSA/RRIF terminology;
  bilingual labels, English primary.
- **Automatic progressive income tax** (no tax inputs): 2026 federal + Quebec
  brackets and credits (basic personal, age 65+, pension income), the Quebec
  abatement, and the OAS recovery — all indexed to the user's inflation
  assumption from 2026. Non-registered gains untaxed (all noted in summary.csv
  and README). Single-taxpayer approximations: Quebec "family income"
  phase-outs use the taxpayer's own income; the Quebec living-alone credit is
  not modeled; working years are not taxed.
- Pensions counted only from the retirement year onward.
- **Linear income decline**: retirement spending falls linearly from 100% at
  retirement to `end_income_ratio` (default 65%) at end age, in real dollars.
- TFSA room limits and GIS are **out of scope** (documented).
- `PlanInputs` is a **frozen dataclass** (hashable) because `app.py` caches
  `compute()` with `@st.cache_data`. Keep it hashable if you add fields.
- **Two fixed people (the couple), additive household** (chosen during
  planning): shared assumptions (return/inflation/volatility/escalation) are
  entered once; ages, accounts, pensions, meltdown and target income are
  per-person. Each plan runs the single-person model and is taxed as a single
  taxpayer; the **Combined** tab sums the two plans by calendar year
  (carry-forward of a passed person's balances). This is explicitly **not** a
  joint income-tax or joint-Monte-Carlo model.
- **Per-person inputs survive Streamlit widget-state pruning**: widget-key
  state is pruned whenever a person's widgets are not rendered, so `app.py`
  keeps the authoritative values in **non-widget** session-state dicts
  (`people_inputs`, `shared_inputs`). Each person's widgets are keyed
  `{pid}__{field}`, created **without** `value=`/`index=` (avoids the "default
  + Session State" warning), and re-seeded from the dicts via
  `_ensure_widget_key()` right before rendering. This is why switching the
  "Editing plan inputs" selector never loses either person's numbers.

## Verification status

- 64/64 pytest tests passing (17 tax unit tests + projection/household/export
  tests; includes
  exact bracket/credit/abatement math, the TP-1.D.B-V line-361 phase-out,
  exhaustion-year, RRIF-minimum (incl. early conversion), monthly meltdown
  (TFSA reinvestment, stop-at-QPP, clamping, indexing), linear
  income-decline, tax/clawback columns, MC seed reproducibility).
- New `test_household.py` (identical plans double each column; differing
  horizons align by calendar year with balance carry-forward past a person's
  end age; combined shortfall year; household MC sums; `total_series`) and a
  household-CSV export test. Total suite: **64 passing**.
- Streamlit `AppTest` smoke test: default run, widget change (QPP start 70),
  invalid-input path, plus switching the "Editing plan inputs" selector and
  changing one spouse's RRSP balance (the other person's plan is unaffected) —
  no exceptions, no "Session State" widget warnings.
- Real server boot: HTTP 200, `/_stcore/health` → `ok`.
- Behavioral sanity confirmed: ~$550/mo monthly meltdown on the defaults
  removes the effective-rate jump at QPP start (18.55% → ~15.6% at 72, RRIF
  balance at 72 ~$461k vs $665k) and cuts total retirement tax ~$28k;
  deferring QPP 65→70 raises success rate;
  clawback reduces OAS exactly by 15% of income above threshold; QPP@60/65/70
  show the expected portfolio-drawdown tradeoff on tight portfolios; the
  default scenario's marginal tax rate at retirement (~36%) matches the
  expected federal 20.5% (net of the 16.5% abatement) + Quebec 19% at the
  retirement-year income.

## Likely next steps / notes

- The user asked about **changing the AI model** running the session — that is
  a harness-level setting, not a code change; this file exists to make a fresh
  session/context fully self-sufficient.
- Possible future model changes: a **true joint (household) income-tax model**
  with pension-income splitting and shared credits — the two-person feature
  currently adds two independently-taxed single-taxpayer plans, so this would
  be the next step beyond it. Also on the list: employer pension (RPP/DB),
  spousal accounts (which would unlock pension-income splitting and the Quebec
  living-alone credit — $2,172 in 2026), capital-gains on non-registered, GIS,
  the 75+ OAS amount boost, or a different spend-down order. Any change should
  update `constants.py` (if statutory), the model
  (`tax.py`/`projection.py`), the tests, and README/HANDOFF together, and
  re-run `pytest`.
- `app.py` uses modern Streamlit API (`width="stretch"`, not deprecated
  `use_container_width`). Watch for Streamlit API deprecations on upgrades.
