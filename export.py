"""Export projection results as CSV strings and a zip archive.

The CSVs are plain data (no formulas): monetary cells are raw numbers with two
decimals and no thousands separators, so Google Sheets (File -> Import ->
Upload) parses them as numbers. Each file maps naturally to one tab.
"""

from __future__ import annotations

import csv
import io
import zipfile

PROJECTION_HEADER = [
    "Age",
    "Year",
    "Income %",
    "Income target",
    "RRSP",
    "TFSA",
    "Non-registered",
    "Total",
    "Withdrawal",
    "RRIF minimum",
    "Shortfall",
    "Tax paid",
    "Marginal rate",
    "Effective rate",
    "QPP",
    "OAS",
    "OAS clawback",
]

_MONEY_QS = (5, 25, 50, 75, 95)


def _money(value: float) -> str:
    return f"{value:.2f}"


def projection_csv(result: dict) -> str:
    """Year-by-year projection: one row per year."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(PROJECTION_HEADER)
    for r in result["projection"]:
        w.writerow(
            [
                r["age"],
                r["year"],
                _money(r["income_pct"]),
                _money(r["income_target"]),
                _money(r["rrsp"]),
                _money(r["tfsa"]),
                _money(r["nonreg"]),
                _money(r["total"]),
                _money(r["withdrawal"]),
                _money(r["rrif_min"]),
                _money(r["shortfall"]),
                _money(r["tax_paid"]),
                _money(r["marginal_rate"] * 100.0),
                _money(r["effective_rate"] * 100.0),
                _money(r["cpp"]),
                _money(r["oas"]),
                _money(r["oas_clawback"]),
            ]
        )
    return buf.getvalue()


HOUSEHOLD_PROJECTION_HEADER = [
    "Year",
    "Your age",
    "Spouse's age",
    "RRSP",
    "TFSA",
    "Non-registered",
    "Total",
    "Income target",
    "Withdrawal",
    "RRIF minimum",
    "QPP",
    "OAS",
    "OAS clawback",
    "Tax paid",
    "Shortfall",
    "Meltdown",
]


def household_projection_csv(household_rows: list[dict]) -> str:
    """Household (combined two-person) projection: one row per calendar year."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HOUSEHOLD_PROJECTION_HEADER)
    for r in household_rows:
        w.writerow(
            [
                r["year"],
                "" if r["age_a"] is None else r["age_a"],
                "" if r["age_b"] is None else r["age_b"],
                _money(r["rrsp"]),
                _money(r["tfsa"]),
                _money(r["nonreg"]),
                _money(r["total"]),
                _money(r["income_target"]),
                _money(r["withdrawal"]),
                _money(r["rrif_min"]),
                _money(r["cpp"]),
                _money(r["oas"]),
                _money(r["oas_clawback"]),
                _money(r["tax_paid"]),
                _money(r["shortfall"]),
                _money(r["meltdown_gross"]),
            ]
        )
    return buf.getvalue()


def summary_csv(result: dict) -> str:
    """All inputs echoed back plus key results, as Item,Value rows."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Item", "Value"])
    for label, value in result["summary"]:
        w.writerow([label, value])
    return buf.getvalue()


def montecarlo_csv(result: dict) -> str:
    """Percentile summary of the Monte Carlo runs."""
    mc = result["montecarlo"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Metric", "P5", "P25", "P50", "P75", "P95"])
    w.writerow(
        ["Balance at retirement (CAD)"]
        + [_money(mc["retirement_balance"][q]) for q in _MONEY_QS]
    )
    w.writerow(
        ["Balance at end age (CAD)"] + [_money(mc["end_balance"][q]) for q in _MONEY_QS]
    )
    w.writerow(["Success rate: never ran out of money (%)", f"{mc['success_pct']:.2f}"])
    return buf.getvalue()


def zip_bytes(result: dict) -> bytes:
    """All three CSVs in one zip archive (BytesIO content)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("projection.csv", projection_csv(result))
        z.writestr("summary.csv", summary_csv(result))
        z.writestr("montecarlo.csv", montecarlo_csv(result))
    return buf.getvalue()
