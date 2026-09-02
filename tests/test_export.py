"""Tests for CSV/zip export: headers, raw numeric cells, and consistency
with the projection results."""

import csv
import io
import zipfile

import pytest

from export import montecarlo_csv, projection_csv, summary_csv, zip_bytes
from projection import PlanInputs, compute_all


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


def test_projection_csv_headers_rows_and_raw_numbers():
    res = compute_all(PlanInputs())
    rows = _rows(projection_csv(res))
    assert rows[0] == [
        "Age", "Year", "Income %", "Income target", "RRSP", "TFSA",
        "Non-registered", "Total", "Withdrawal", "FERR minimum", "Shortfall",
        "Tax paid", "Marginal rate", "Effective rate", "CPP (RPC)",
        "OAS (PSV)", "OAS clawback",
    ]
    assert len(rows) == len(res["projection"]) + 1
    first = rows[1]
    assert int(first[0]) == res["projection"][0]["age"]
    # Raw numeric cells: no thousands separators, parseable as floats.
    for cell in first[2:]:
        assert "," not in cell
        float(cell)
    # Values match the projection exactly (2-decimal rounding).
    p0 = res["projection"][0]
    assert float(first[2]) == pytest.approx(p0["income_pct"])
    assert float(first[3]) == pytest.approx(p0["income_target"])
    assert float(first[4]) == pytest.approx(p0["rrsp"])
    assert float(first[5]) == pytest.approx(p0["tfsa"])
    assert float(first[7]) == pytest.approx(p0["total"])
    assert float(first[8]) == pytest.approx(p0["withdrawal"])
    assert float(first[9]) == pytest.approx(p0["ferr_min"])
    assert float(first[10]) == pytest.approx(p0["shortfall"])
    assert float(first[11]) == pytest.approx(p0["tax_paid"])
    assert float(first[12]) == pytest.approx(p0["marginal_rate"] * 100)
    assert float(first[13]) == pytest.approx(p0["effective_rate"] * 100)
    assert float(first[14]) == pytest.approx(p0["cpp"])
    assert float(first[16]) == pytest.approx(p0["oas_clawback"])


def test_projection_csv_reports_shortfall_rows():
    p = PlanInputs(
        current_age=64, retirement_age=65, end_age=67,
        rrsp_balance=10_000, rrsp_monthly=0,
        tfsa_balance=0, tfsa_monthly=0,
        nonreg_balance=0, nonreg_monthly=0,
        annual_return=0.0, inflation_rate=0.0,
        qpp_monthly_at_65=0.0, oas_monthly=0.0,
        target_monthly_income=2_000,
    )
    res = compute_all(p)
    rows = _rows(projection_csv(res))
    short_rows = [r for r in rows[1:] if float(r[10]) > 0]
    assert short_rows, "expected at least one shortfall row"
    # The $10k RRSP withdrawal is below the basic personal amounts (no tax),
    # so it covers $10k of the $24k need.
    assert float(short_rows[0][10]) == pytest.approx(2_000 * 12 - 10_000)


def test_summary_csv_layout():
    res = compute_all(PlanInputs())
    rows = _rows(summary_csv(res))
    assert rows[0] == ["Item", "Value"]
    assert len(rows) == len(res["summary"]) + 1
    labels = [r[0] for r in rows[1:]]
    assert "Exhaustion year (deterministic)" in labels
    assert "Success rate: never ran out of money (%)" in labels
    # Every summary value is a scalar (string or number), CSV-friendly.
    for _, value in res["summary"]:
        assert not isinstance(value, (list, dict))


def test_montecarlo_csv_layout():
    res = compute_all(PlanInputs())
    rows = _rows(montecarlo_csv(res))
    assert rows[0] == ["Metric", "P5", "P25", "P50", "P75", "P95"]
    assert len(rows) == 4
    assert float(rows[1][1]) <= float(rows[1][3]) <= float(rows[1][5])  # P5 <= P50 <= P95
    assert float(rows[2][1]) <= float(rows[2][3]) <= float(rows[2][5])
    assert 0 <= float(rows[3][1]) <= 100  # success rate


def test_zip_contains_three_identical_csvs():
    res = compute_all(PlanInputs())
    data = zip_bytes(res)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert sorted(z.namelist()) == ["montecarlo.csv", "projection.csv", "summary.csv"]
        assert z.read("projection.csv").decode("utf-8") == projection_csv(res)
        assert z.read("summary.csv").decode("utf-8") == summary_csv(res)
        assert z.read("montecarlo.csv").decode("utf-8") == montecarlo_csv(res)
