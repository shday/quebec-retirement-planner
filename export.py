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
    "FERR minimum",
    "Shortfall",
    "Tax paid",
    "CPP (RPC)",
    "OAS (PSV)",
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
                _money(r["ferr_min"]),
                _money(r["shortfall"]),
                _money(r["tax_paid"]),
                _money(r["cpp"]),
                _money(r["oas"]),
                _money(r["oas_clawback"]),
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
