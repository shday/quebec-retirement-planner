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
python -m pytest -q              # 16 tests, all passing
```

Dependencies: `requirements.txt` (streamlit, plotly) and
`requirements-dev.txt` (+ pytest).

## File map

| File | Role |
| --- | --- |
| `app.py` | Streamlit UI: sidebar inputs, 5 metric cards, Plotly band chart (deterministic stacked bars by account + P5–P95 band), projection dataframe, Monte Carlo table, 4 download buttons. Thin glue only. |
| `projection.py` | The model. `PlanInputs` (frozen dataclass), `validate()`, `qpp_adjustment()`, `oas_adjustment()`, `income_fraction()`, `step_year()` (single-year engine shared by deterministic + MC; returns a 9-tuple including tax paid, OAS clawback, FERR minimum), `deterministic_projection()`, `monte_carlo()`, `build_result()`, `compute_all()`. Pure stdlib (no numpy). |
| `constants.py` | Statutory constants with cited sources: FERR (RRIF) minimum factors, QPP/OAS adjustment rules, 2025 maxima, planning defaults. |
| `export.py` | `projection_csv()`, `summary_csv()`, `montecarlo_csv()`, `zip_bytes()`. Raw numeric cells (2 decimals, no thousands separators) so Google Sheets imports them as numbers. |
| `tests/` | `test_projection.py` (11 tests: factors, zero-growth, inflation indexing, FERR minimum, RRSP-close-at-71, exhaustion, MC reproducibility/percentile order, validation, end-to-end), `test_export.py` (5 tests: CSV layout/values, shortfall rows, zip contents). |
| `README.md` | User setup, Google Sheets import steps, model explanation, sources. |
| `conftest.py` | Empty; makes project root importable for pytest. |

## The model (what `step_year` does each year)

Ages run `current_age → end_age`; `year_offset = age - current_age`;
`year = date.today().year + offset` (note: the machine clock is 2026).

1. **FERR minimum** = `ferr_min_factor(age) × RRSP opening balance` when
   `age >= 71` (factor table in `constants.py`, ITR s. 7308).
2. **Contributions** (only while `age < retirement_age`): monthly × 12 ×
   `(1 + escalation)^offset`. RRSP contributions stop at 71 (RRSP is closed);
   from 71 the RRSP monthly amount is redirected to TFSA.
3. **Growth**: each balance × `(1 + annual_return)`.
4. **Pensions** (only in retirement years — a deliberate simplification): QPP
   = user's age-65 figure × `qpp_adjustment(start_age)` × `(1+inflation)^offset`
   × 12; OAS similarly with `oas_adjustment()` and optional clawback. Both
   start only at their start age and only at/after retirement age.
5. **Income need** (retirement years): the monthly target declines linearly via
   `income_fraction(p, age)` from 1.0 at `retirement_age` to
   `end_income_ratio` (default 0.6) at `end_age`, inflation-indexed.
6. **Taxation**: CPP (RPC) and OAS (PSV) are **fully taxable** at the flat
   `tax_rate`, so the after-tax income gap from accounts is
   `max(0, target × 12 − (CPP + OAS) × (1 − tax_rate))`.
7. **Withdrawals** (if gap > 0): non-registered first (untaxed in this model)
   → RRSP/FERR grossed up at flat `tax_rate`, with the FERR minimum as a
   **floor** on the FERR withdrawal (if the minimum exceeds the need, the
   after-tax surplus is reinvested in TFSA) → TFSA last. If accounts run dry,
   `shortfall` records the unmet gap for that year (first such year = the
   **exhaustion year**). If gap ≤ 0 but a FERR minimum exists (working past
   71, or pensions cover the target after tax), the minimum is still withdrawn
   and its after-tax amount goes to TFSA.
8. **Monte Carlo**: 1,000 sims, `random.Random(seed=42)`, lognormal annual
   returns `exp(ln(1+r) − 0.5σ² + σ·z) − 1`. Tracks per-year total balances
   (for the P5–P95 band), balance at retirement age, balance at end age, and
   success = never had `shortfall > 0`. Percentiles are nearest-rank.
9. **Detail columns** (each projection row): `tax_paid` (flat rate × all
   taxable income: CPP + OAS + gross RRSP/FERR withdrawal), `oas_clawback`
   (gross OAS − net OAS), and `ferr_min` (mandatory minimum RRSP/FERR
   withdrawal, 0 before 71). `step_year` returns a 9-tuple:
   `(balances, withdrawal, shortfall, cpp, oas, target_monthly, tax_paid,
   oas_clawback, ferr_min)`.

## Key statutory values (all sourced in `constants.py`)

- QPP max at 65, 2025: **$1,395.25** (user should use their own Retraite
  Québec figure). Start 60–72: −0.6%/month before 65, +0.7%/month after 65
  (CPP-aligned rates since Jan 2024) → factors 0.64 at 60, 1.0 at 65, 1.42 at
  70, 1.588 at 72. Since 2026, QPP deferral runs to 72 (max +58.8%); CPP still
  caps at 70.
- OAS max 65–74, 2025: **$734.95** (indexed quarterly). Defer to 70 = +36%.
  Clawback (ITA s. 180.2): 15% of net income above the threshold (2025:
  $93,454, ages 65–74; fully clawed by ~$151,959), capped at OAS. The model
  **indexes the threshold to inflation** each year and **iterates the estimate
  to a fixed point** (clawback → lower OAS → higher RRSP/FERR withdrawal →
  higher income → higher clawback). Income proxy = CPP + gross OAS + estimated
  gross RRSP/FERR withdrawal; ignores untaxed non-registered/TFSA drawdown and
  the real-world one-year assessment lag (documented approximation).
- FERR minimum factors: 71→5.28%, 72→5.40%, 73→5.53% … 94→18.79%, 95+→20.00%
  (ITR s. 7308; ages < 71 use `1/(90 − age)`).
- Defaults: return 7%, inflation 2.5%, volatility 10%, escalation 0%, flat
  tax 30% (combined QC+fed effective), income at end age 60% (linear decline),
  1,000 sims, seed 42.

## Locked-in decisions (do not silently change without asking)

- **Streamlit + Plotly** app, thin UI over pure functions.
- **CSV manual import** to Google Sheets — no Google integration by design.
- **Quebec-specific**: RPC (QPP), PSV (OAS), REER/CELI/FERR terminology;
  bilingual labels, English primary.
- **Flat effective tax rate** on all taxable income — RRSP/FERR withdrawals
  plus CPP (RPC) and OAS (PSV), both fully taxable in Canada; non-registered
  gains untaxed (all noted in summary.csv and README).
- Pensions counted only from the retirement year onward.
- **Linear income decline**: retirement spending falls linearly from 100% at
  retirement to `end_income_ratio` (default 60%) at end age, in real dollars.
- TFSA room limits and GIS are **out of scope** (documented).
- `PlanInputs` is a **frozen dataclass** (hashable) because `app.py` caches
  `compute()` with `@st.cache_data`. Keep it hashable if you add fields.

## Verification status

- 22/22 pytest tests passing (model math + CSV export; includes exact
  exhaustion-year, FERR-minimum, linear income-decline, tax/clawback column,
  and MC seed reproducibility cases).
- Streamlit `AppTest` smoke test: default run, widget change (QPP start 70),
  and invalid-input path — no exceptions.
- Real server boot: HTTP 200, `/_stcore/health` → `ok`.
- Behavioral sanity confirmed: deferring QPP 65→70 raises success rate;
  clawback reduces OAS exactly by 15% of income above threshold; QPP@60/65/70
  show the expected portfolio-drawdown tradeoff on tight portfolios.

## Likely next steps / notes

- The user asked about **changing the AI model** running the session — that is
  a harness-level setting, not a code change; this file exists to make a fresh
  session/context fully self-sufficient.
- Possible future model changes: employer pension (RPP/DB), spousal accounts,
  tax brackets instead of flat rate, capital-gains on non-registered, GIS, or
  a different spend-down order. Any change should update `constants.py` (if
  statutory), `projection.py`, the tests, and README together, and re-run
  `pytest`.
- `app.py` uses modern Streamlit API (`width="stretch"`, not deprecated
  `use_container_width`). Watch for Streamlit API deprecations on upgrades.
