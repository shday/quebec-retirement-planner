"""Household (two-person) combination of two independent retirement plans.

The single-plan engine in ``projection.py`` models one taxpayer at a time and
taxes that person as a *single* taxpayer (federal + Quebec, see tax.py) — a
documented approximation. This module deliberately does NOT introduce a joint
income-tax model. Instead it builds the household "picture" the user asked for
by running each person's plan independently and **adding the two plans
together on a common calendar-year axis**:

- Each person's deterministic projection contributes its account balances,
  pension income, withdrawals and tax in every calendar year it covers.
- If one plan ends before the other (a person passes their modeled life
  expectancy), that person's *balances* are carried forward at their final,
  constant nominal value for the remaining household years (the estate is
  still owned by the household) while they contribute no further income, tax
  or withdrawals. This matches the app's "the projection stops at the end age"
  simplification.
- The Monte Carlo band is the **indicative sum** of the two plans' independent
  P5/P50/P95 percentile trajectories (each final percentile carried forward).
  This is NOT a joint simulation with correlated draws, so it is approximate.

Everything here is pure and stdlib-only so it is unit-testable in isolation.
"""

from __future__ import annotations

# Flow columns whose values are simply summed across the two plans (zero for a
# person past their modeled end age). Income target, pension income, tax, etc.
FLOW_SUM_KEYS = (
    "income_target",
    "withdrawal",
    "rrif_min",
    "shortfall",
    "tax_paid",
    "cpp",           # QPP (the single-plan engine labels the column "cpp")
    "oas",
    "oas_clawback",
    "meltdown_gross",
)

# Balance columns whose values are summed, and carried forward (constant) for a
# person past their end age.
BAL_KEYS = ("rrsp", "tfsa", "nonreg")


def _rows_by_year(rows: list[dict]) -> dict[int, dict]:
    return {r["year"]: r for r in rows}


def _contributor(by_year: dict[int, dict], final: dict):
    """Return a callable that yields a plan's contribution for a given year.

    For a year the plan covers, its own row is used. For a later year (past the
    plan's end age) balances are carried forward at the final nominal value and
    all flow columns are zero. The returned dict is meant to be read, not
    mutated.
    """

    def state(year: int) -> dict:
        row = by_year.get(year)
        if row is not None:
            return row
        c = {"age": None, **{k: final[k] for k in BAL_KEYS}}
        c["total"] = sum(final[k] for k in BAL_KEYS)
        for k in FLOW_SUM_KEYS:
            c[k] = 0.0
        return c

    return state


def household_projection(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    """Combine two deterministic projections into a household row per calendar
    year, from the current year to the later of the two plans' end years.

    Each combined row has: year, age_a/age_b (None once a person is past their
    end age), summed rrsp/tfsa/nonreg/total, and summed flow columns
    (income_target, withdrawal, rrif_min, shortfall, tax_paid, cpp, oas,
    oas_clawback, meltdown_gross).
    """
    by_a = _rows_by_year(rows_a)
    by_b = _rows_by_year(rows_b)
    a = _contributor(by_a, rows_a[-1])
    b = _contributor(by_b, rows_b[-1])

    start_year = max(rows_a[0]["year"], rows_b[0]["year"])
    end_year = max(rows_a[-1]["year"], rows_b[-1]["year"])

    combined: list[dict] = []
    for year in range(start_year, end_year + 1):
        ca = a(year)
        cb = b(year)
        row: dict = {
            "year": year,
            "age_a": ca["age"],
            "age_b": cb["age"],
        }
        for k in BAL_KEYS:
            row[k] = ca[k] + cb[k]
        row["total"] = row["rrsp"] + row["tfsa"] + row["nonreg"]
        for k in FLOW_SUM_KEYS:
            row[k] = ca[k] + cb[k]
        combined.append(row)
    return combined


def household_montecarlo(mc_a: dict, mc_b: dict) -> dict:
    """Indicative household Monte Carlo band: sum the two plans' independent
    P5/P50/P95 totals on a common calendar-year axis (final percentile carried
    forward past each plan's end age).

    Note this is the sum of two independent runs, not a joint simulation, so it
    is indicative only.
    """
    y_a = mc_a["years"]
    y_b = mc_b["years"]
    start_year = max(y_a[0], y_b[0])
    end_year = max(y_a[-1], y_b[-1])
    years = list(range(start_year, end_year + 1))

    def series(mc: dict, key: str) -> list[float]:
        vals = mc[key]
        first = mc["years"][0]
        by_year = {mc["years"][i]: vals[i] for i in range(len(vals))}
        final = vals[-1]
        return [by_year.get(y, final) for y in years]

    out = {"years": years}
    for q in ("p5", "p50", "p95"):
        key = f"total_{q}"
        sa = series(mc_a, key)
        sb = series(mc_b, key)
        out[key] = [va + vb for va, vb in zip(sa, sb)]
    return out


def total_series(rows: list[dict], years: list[int]) -> list[float]:
    """Per-plan deterministic total balance on an explicit year axis, with the
    final balance carried forward past the plan's end age (for stacked charts).
    """
    by_year = _rows_by_year(rows)
    final = rows[-1]["total"]
    return [by_year.get(y, {"total": final})["total"] for y in years]


def first_shortfall_year(household_rows: list[dict]) -> int | None:
    """First calendar year any combined shortfall exceeds epsilon, else None."""
    for row in household_rows:
        if row["shortfall"] > 1e-9:
            return row["year"]
    return None
