"""Quebec Retirement Planner - Streamlit web app.

Run with:  streamlit run app.py

Enter your numbers in the sidebar, review the deterministic and Monte Carlo
projection, and download CSVs to import into Google Sheets
(File -> Import -> Upload, one tab per file).
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

import constants as C
import export
from projection import PlanInputs, build_result, deterministic_projection, monte_carlo, validate

st.set_page_config(page_title="Quebec Retirement Planner", page_icon="🍁", layout="wide")

st.title("🍁 Quebec Retirement Planner")
st.caption(
    "RPC (QPP) · PSV (OAS) · REER (RRSP) · CELI (TFSA) · FERR (RRIF) — amounts in CAD. "
    "Informational estimates only, not financial advice. "
    "This app computes locally; nothing is uploaded anywhere."
)


# ---------------------------------------------------------------------------
# Inputs (sidebar)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("👤 Personal")
    current_age = st.number_input("Current age", 18, 100, C.DEFAULT_CURRENT_AGE, step=1)
    retirement_age = st.number_input("Retirement age", 18, 100, C.DEFAULT_RETIREMENT_AGE, step=1)
    end_age = st.number_input("End age (life expectancy)", 19, 110, C.DEFAULT_END_AGE, step=1)

    st.header("💰 Accounts")
    st.caption("Current balance + monthly contribution until retirement")
    rrsp_balance = st.number_input("RRSP (REER) balance (CAD)", 0, 20_000_000, C.DEFAULT_RRSP_BALANCE, step=5_000, format="%d")
    rrsp_monthly = st.number_input("RRSP (REER) monthly contribution (CAD)", 0, 100_000, C.DEFAULT_RRSP_MONTHLY, step=50, format="%d")
    tfsa_balance = st.number_input("TFSA (CELI) balance (CAD)", 0, 20_000_000, C.DEFAULT_TFSA_BALANCE, step=5_000, format="%d")
    tfsa_monthly = st.number_input("TFSA (CELI) monthly contribution (CAD)", 0, 100_000, C.DEFAULT_TFSA_MONTHLY, step=50, format="%d")
    nonreg_balance = st.number_input("Non-registered balance (CAD)", 0, 20_000_000, C.DEFAULT_NONREG_BALANCE, step=5_000, format="%d")
    nonreg_monthly = st.number_input("Non-registered monthly contribution (CAD)", 0, 100_000, C.DEFAULT_NONREG_MONTHLY, step=50, format="%d")

    st.header("📈 Assumptions")
    annual_return = st.number_input("Annual return (%)", 0.0, 20.0, C.DEFAULT_ANNUAL_RETURN * 100, step=0.5, format="%.2f")
    inflation = st.number_input("Inflation (%)", 0.0, 10.0, C.DEFAULT_INFLATION * 100, step=0.25, format="%.2f")
    volatility = st.number_input("Return volatility, Monte Carlo (%)", 0.0, 30.0, C.DEFAULT_VOLATILITY * 100, step=0.5, format="%.2f")
    escalation = st.number_input("Contribution escalation (%/yr)", 0.0, 10.0, C.DEFAULT_CONTRIBUTION_ESCALATION * 100, step=0.5, format="%.2f")

    st.header("🏖️ Retirement income")
    target_income = st.number_input("Target monthly income at retirement (today's CAD)", 0, 100_000, C.DEFAULT_TARGET_MONTHLY_INCOME, step=250, format="%d")
    end_income_ratio = st.slider(
        "Income at end age (% of retirement income)",
        0, 100, int(C.DEFAULT_END_INCOME_RATIO * 100), step=5,
    )
    st.caption("Income needs decline linearly from retirement to end age.")
    st.caption("Pensions are indexed to inflation from today.")
    qpp_monthly = st.number_input("QPP (RPC) monthly at 65 (today's CAD)", 0.0, 5_000.0, C.QPP_MAX_AT_65_2025, step=25.0, format="%.2f")
    st.caption(f"2025 maximum: {C.QPP_MAX_AT_65_2025:,.2f} — use your own figure from Retraite Québec.")
    qpp_start = st.select_slider(
        "QPP (RPC) start age",
        options=range(C.QPP_MIN_START_AGE, C.QPP_MAX_START_AGE + 1),
        value=max(C.QPP_MIN_START_AGE, min(C.DEFAULT_QPP_START_AGE, C.QPP_MAX_START_AGE)),
    )
    oas_monthly = st.number_input("OAS (PSV) monthly at 65 (today's CAD)", 0.0, 3_000.0, C.OAS_MAX_2025, step=10.0, format="%.2f")
    st.caption(f"2025 maximum (65-74): {C.OAS_MAX_2025:,.2f} — use your own figure from Service Canada.")
    oas_options = (65, C.OAS_DEFERRAL_MAX_AGE)  # statutory choices
    oas_index = oas_options.index(C.DEFAULT_OAS_START_AGE) if C.DEFAULT_OAS_START_AGE in oas_options else 0
    oas_start = st.radio("OAS (PSV) start age", options=oas_options, index=oas_index, horizontal=True)
    oas_clawback = st.checkbox("Apply OAS (PSV) clawback (15% above ~$93,454/yr)", value=C.DEFAULT_OAS_CLAWBACK)

    st.header("🧾 Tax")
    tax_rate = st.number_input(
        "Effective tax rate on taxable income (%)",
        0.0, 60.0, C.DEFAULT_TAX_RATE * 100, step=1.0, format="%.1f",
    )
    st.caption("Flat combined Quebec + federal rate; applies to RRSP/FERR withdrawals and to CPP (RPC) + OAS (PSV), which are fully taxable.")

    st.header("🎲 Monte Carlo")
    st.caption(f"{C.DEFAULT_MONTE_CARLO_SIMS} simulations, fixed seed {C.DEFAULT_SEED}.")


# ---------------------------------------------------------------------------
# Validate + compute
# ---------------------------------------------------------------------------
p = PlanInputs(
    current_age=int(current_age),
    retirement_age=int(retirement_age),
    end_age=int(end_age),
    rrsp_balance=float(rrsp_balance),
    rrsp_monthly=float(rrsp_monthly),
    tfsa_balance=float(tfsa_balance),
    tfsa_monthly=float(tfsa_monthly),
    nonreg_balance=float(nonreg_balance),
    nonreg_monthly=float(nonreg_monthly),
    annual_return=annual_return / 100.0,
    inflation_rate=inflation / 100.0,
    volatility=volatility / 100.0,
    contribution_escalation=escalation / 100.0,
    target_monthly_income=float(target_income),
    end_income_ratio=end_income_ratio / 100.0,
    qpp_monthly_at_65=float(qpp_monthly),
    qpp_start_age=int(qpp_start),
    oas_monthly=float(oas_monthly),
    oas_start_age=int(oas_start),
    oas_clawback=bool(oas_clawback),
    tax_rate=tax_rate / 100.0,
)

errors = validate(p)
if errors:
    for err in errors:
        st.error(err)
    st.stop()


@st.cache_data(show_spinner=False)
def compute(inp: PlanInputs) -> dict:
    return build_result(inp, deterministic_projection(inp), monte_carlo(inp))


result = compute(p)
rows = result["projection"]
mc = result["montecarlo"]
summary = dict(result["summary"])

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
det_retirement_balance = next(r["total"] for r in rows if r["age"] == p.retirement_age)
c1.metric("Median balance at retirement (MC)", f"${mc['retirement_balance'][50]:,.0f}")
c2.metric("Success rate (never ran out)", f"{mc['success_pct']:.1f}%")
c3.metric("Balance at retirement (deterministic)", f"${det_retirement_balance:,.0f}")
c4.metric("Exhaustion year", summary["Exhaustion year (deterministic)"])
c5.metric("FERR conversion year", "71" if p.end_age >= 71 else "N/A")

st.divider()

# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
fig = go.Figure()
years = mc["years"]
fig.add_trace(
    go.Scatter(
        x=years, y=mc["total_p95"], mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    )
)
fig.add_trace(
    go.Scatter(
        x=years, y=mc["total_p5"], mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(31,119,180,0.20)",
        name="P5-P95 range (Monte Carlo)",
    )
)
fig.add_trace(
    go.Scatter(
        x=years, y=mc["total_p50"], mode="lines", name="Median (Monte Carlo)",
        line=dict(dash="dot"),
    )
)
det_rrsp = [r["rrsp"] for r in rows]
det_tfsa = [r["tfsa"] for r in rows]
det_nonreg = [r["nonreg"] for r in rows]
fig.add_trace(
    go.Bar(
        x=years, y=det_rrsp, name="RRSP (REER)",
        marker_color="#2ca02c", opacity=0.85,
    )
)
fig.add_trace(
    go.Bar(
        x=years, y=det_tfsa, name="TFSA (CELI)",
        marker_color="#ff7f0e", opacity=0.85,
    )
)
fig.add_trace(
    go.Bar(
        x=years, y=det_nonreg, name="Non-registered",
        marker_color="#9467bd", opacity=0.85,
    )
)
fig.update_layout(
    title="Total portfolio balance by year",
    xaxis_title="Year",
    yaxis_title="CAD",
    barmode="stack",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=60, b=30),
)
st.plotly_chart(fig, width="stretch")

st.divider()

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
st.subheader("Year-by-year projection")
display_rows = [
    {
        "Age": r["age"],
        "Year": r["year"],
        "Income %": round(r["income_pct"], 1),
        "Income target": round(r["income_target"], 0),
        "RRSP": round(r["rrsp"], 0),
        "TFSA": round(r["tfsa"], 0),
        "Non-registered": round(r["nonreg"], 0),
        "Total": round(r["total"], 0),
        "Withdrawal": round(r["withdrawal"], 0),
        "FERR minimum": round(r["ferr_min"], 0),
        "Shortfall": round(r["shortfall"], 0),
        "Tax paid": round(r["tax_paid"], 0),
        "CPP (RPC)": round(r["cpp"], 0),
        "OAS (PSV)": round(r["oas"], 0),
        "OAS clawback": round(r["oas_clawback"], 0),
    }
    for r in rows
]
st.dataframe(display_rows, hide_index=True, width="stretch", height=440)

mc_col, key_col = st.columns([2, 3])
with mc_col:
    st.subheader("Monte Carlo summary")
    mc_rows = [
        {
            "Metric": "Balance at retirement (CAD)",
            **{f"P{q}": round(mc["retirement_balance"][q], 0) for q in (5, 25, 50, 75, 95)},
        },
        {
            "Metric": "Balance at end age (CAD)",
            **{f"P{q}": round(mc["end_balance"][q], 0) for q in (5, 25, 50, 75, 95)},
        },
        {"Metric": "Success rate (%)", "P50": round(mc["success_pct"], 2)},
    ]
    st.dataframe(mc_rows, hide_index=True, width="stretch")

with key_col:
    st.subheader("Key figures")
    key_rows = [
        {
            "Item": label,
            "Value": (
                f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
            ),
        }
        for label, value in result["summary"]
        if label
        in {
            "Balance at retirement, median of Monte Carlo (CAD)",
            "Balance at retirement, deterministic (CAD)",
            "Success rate: never ran out of money (%)",
            "Exhaustion year (deterministic)",
            "Years of income coverage",
            "QPP (RPC) monthly at start age, first year (CAD)",
            "OAS (PSV) monthly at start age, first year (CAD)",
        }
    ]
    st.dataframe(key_rows, hide_index=True, width="stretch")

st.divider()

# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------
st.subheader("💾 Download CSVs for Google Sheets")
st.info(
    "In Google Sheets: **File → Import → Upload** → pick each CSV → "
    "**Insert new sheet(s)**. Each file becomes its own tab and numeric cells "
    "are detected automatically. Optional: select balance columns → "
    "**Format → Number → Currency**."
)
d1, d2, d3, d4 = st.columns(4)
d1.download_button(
    "Download projection.csv",
    export.projection_csv(result),
    file_name="projection.csv",
    mime="text/csv",
    width="stretch",
)
d2.download_button(
    "Download summary.csv",
    export.summary_csv(result),
    file_name="summary.csv",
    mime="text/csv",
    width="stretch",
)
d3.download_button(
    "Download montecarlo.csv",
    export.montecarlo_csv(result),
    file_name="montecarlo.csv",
    mime="text/csv",
    width="stretch",
)
d4.download_button(
    "Download all (.zip)",
    export.zip_bytes(result),
    file_name="retirement_plan_csv.zip",
    mime="application/zip",
    width="stretch",
)
