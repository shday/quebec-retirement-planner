"""Quebec Retirement Planner - Streamlit web app.

Run with:  streamlit run app.py

Plan and model a couple's retirement here. Enter each person's numbers in the
sidebar (shared assumptions are entered once and applied to both), review each
person's deterministic and Monte Carlo projection on its own tab, and see a
household "combined" tab that adds the two plans together by calendar year.
Download CSVs to import into Google Sheets (File -> Import -> Upload, one tab
per file).

The combined tab is an additive household picture: each plan is modeled and
taxed independently as a single taxpayer (the app's documented approximation)
and the results are summed. It is not a joint income-tax or a joint-simulation
model.
"""

from __future__ import annotations

from datetime import date

import streamlit as st
import plotly.graph_objects as go

import constants as C
import defaults as D
import export
import household as HH
from projection import (
    PlanInputs,
    build_result,
    deterministic_projection,
    rrif_conversion_age,
    monte_carlo,
    validate,
)

st.set_page_config(page_title="Quebec Retirement Planner", page_icon="🍁", layout="wide")

st.title("🍁 Quebec Retirement Planner")
st.caption(
    "QPP · OAS · RRSP · TFSA · RRIF — amounts in CAD. "
    "Two plans (yours and your spouse's) with a combined household view. "
    "Informational estimates only, not financial advice. "
    "This app computes locally; nothing is uploaded anywhere."
)

PERSON_LABEL = {"me": "Your plan", "spouse": "Spouse's plan"}

# ---------------------------------------------------------------------------
# Authoritative session state (per-person / shared), seeded from the saved plan
# ---------------------------------------------------------------------------
def _init_state() -> None:
    """Seed authoritative per-person / shared input dicts.

    These live under NON-widget session-state keys. Streamlit prunes the state
    of a keyed widget whenever that widget is not rendered in a run (e.g. the
    other person's inputs while you edit this one), so widget keys cannot be
    the source of truth. The authoritative values live in these dicts, which
    Streamlit never prunes; widget keys are re-seeded from them on demand.

    The starting values come from the saved plan (``defaults.plan_defaults.json``,
    seeded from the committed ``defaults.example.json``), so a previously saved
    plan becomes the default for the next session.
    """
    ss = st.session_state
    plan = D.load_plan()
    if "people_inputs" not in ss:
        ss["people_inputs"] = {pid: dict(plan["people"][pid]) for pid in ("me", "spouse")}
    if "shared_inputs" not in ss:
        ss["shared_inputs"] = dict(plan["shared"])


def _person(pid: str) -> dict:
    return st.session_state["people_inputs"][pid]


def _shared() -> dict:
    return st.session_state["shared_inputs"]


def _ensure_widget_key(key: str, value) -> None:
    """Set a widget's key from our authoritative dict only when it is absent.

    Widgets are created without a ``value``/``index`` argument and instead read
    their (re-seeded) key, which avoids Streamlit's "default + Session State"
    conflict warnings and survives widget-state pruning between person switches.
    """
    if key not in st.session_state:
        st.session_state[key] = value


def _sync_person(pid: str) -> None:
    """Copy the just-rendered widget values back into the authoritative dict."""
    for f in D.PERSON_FIELDS:
        k = f"{pid}__{f}"
        if k in st.session_state:
            _person(pid)[f] = st.session_state[k]


def _sync_shared() -> None:
    for f in D.SHARED_FIELDS:
        k = f"shared__{f}"
        if k in st.session_state:
            _shared()[f] = st.session_state[k]


# ---------------------------------------------------------------------------
# Shared assumptions (couple-level, entered once, applied to both plans)
# ---------------------------------------------------------------------------
def _render_shared_inputs() -> None:
    st.header("📈 Shared assumptions (both plans)")
    st.caption("Applied to both plans.")
    s = _shared()
    for f, val in s.items():
        _ensure_widget_key(f"shared__{f}", val)
    st.number_input("Annual return (%)", 0.0, 20.0, step=0.5, format="%.2f", key="shared__annual_return_pct")
    st.number_input("Inflation (%)", 0.0, 10.0, step=0.25, format="%.2f", key="shared__inflation_pct")
    st.number_input("Return volatility, Monte Carlo (%)", 0.0, 30.0, step=0.5, format="%.2f", key="shared__volatility_pct")
    st.number_input("Contribution escalation (%/yr)", 0.0, 10.0, step=0.5, format="%.2f", key="shared__escalation_pct")
    _sync_shared()


# ---------------------------------------------------------------------------
# Personal inputs (per-person; unique widget keys keep both people's values)
# ---------------------------------------------------------------------------
def _render_personal_inputs(pid: str) -> None:
    key = lambda f: f"{pid}__{f}"  # noqa: E731
    pi = _person(pid)
    # Re-seed any widget key Streamlit pruned since this person was last shown.
    for f, val in pi.items():
        _ensure_widget_key(key(f), val)

    st.header("👤 Personal")
    st.number_input("Current age", 18, 100, step=1, key=key("current_age"))
    st.number_input("Retirement age", 18, 100, step=1, key=key("retirement_age"))
    st.number_input("End age (life expectancy)", 19, 110, step=1, key=key("end_age"))

    st.header("💰 Accounts")
    st.caption("Current balance + monthly contribution until retirement")
    st.number_input("RRSP balance (CAD)", 0, 20_000_000, step=5_000, format="%d", key=key("rrsp_balance"))
    st.number_input("RRSP monthly contribution (CAD)", 0, 100_000, step=50, format="%d", key=key("rrsp_monthly"))
    st.number_input("TFSA balance (CAD)", 0, 20_000_000, step=5_000, format="%d", key=key("tfsa_balance"))
    st.number_input("TFSA monthly contribution (CAD)", 0, 100_000, step=50, format="%d", key=key("tfsa_monthly"))
    st.number_input("Non-registered balance (CAD)", 0, 20_000_000, step=5_000, format="%d", key=key("nonreg_balance"))
    st.number_input("Non-registered monthly contribution (CAD)", 0, 100_000, step=50, format="%d", key=key("nonreg_monthly"))

    st.header("🏖️ Retirement income")
    st.number_input(
        "Monthly meltdown (CAD, today's $)",
        0, 100_000, step=100, format="%d",
        key=key("monthly_meltdown"),
    )
    st.caption(
        "Save this much into the TFSA each month from retirement until QPP "
        "starts, funded by RRIF withdrawals (taxed first; the after-tax amount "
        "is deposited in the TFSA). Shrinks the RRIF so the mandatory minimums "
        "don't force extra taxable income once QPP/OAS start."
    )
    st.number_input("Target monthly income at retirement (today's CAD)", 0, 100_000, step=250, format="%d", key=key("target_monthly_income"))
    st.slider("Income at end age (% of retirement income)", 0, 100, step=5, key=key("end_income_ratio_pct"))
    st.slider("Steepness of income decline", 0.0, 1.0, step=0.05, key=key("steepness"))
    st.caption(
        "Income needs follow an S-shaped decline from retirement toward the "
        "end-age level: higher steepness holds income nearer full longer then "
        "drops faster around mid-retirement; lower steepness gives a more "
        "gradual, gentler curve."
    )
    st.caption("Pensions are indexed to inflation from today.")
    st.slider("QPP at 65 (% of maximum)", 0, 100, step=1, key=key("qpp_pct"))
    qpp_pct = float(st.session_state[key("qpp_pct")]) / 100.0
    qpp_monthly = qpp_pct * C.QPP_MAX_AT_65_2025
    st.caption(
        f"{qpp_pct * 100.0:.0f}% of the 2025 maximum ({C.QPP_MAX_AT_65_2025:,.2f}/month) "
        f"= {qpp_monthly:,.2f}/month at 65, in today's CAD. "
        "Check Retraite Québec: your statement pension ÷ the maximum."
    )
    st.select_slider(
        "QPP start age",
        options=range(C.QPP_MIN_START_AGE, C.QPP_MAX_START_AGE + 1),
        key=key("qpp_start"),
    )
    st.number_input("OAS monthly at 65 (today's CAD)", 0.0, 3_000.0, step=10.0, format="%.2f", key=key("oas_monthly"))
    st.caption(
        f"2025 maxima: {C.OAS_MAX_2025:,.2f} (65–74) / {C.OAS_MAX_75_2025:,.2f} (75+) — "
        "use your own figure from Service Canada. The model applies the +10% top-up automatically at 75."
    )
    oas_options = (65, C.OAS_DEFERRAL_MAX_AGE)  # statutory choices
    st.radio("OAS start age", options=oas_options, horizontal=True, key=key("oas_start"))
    st.checkbox("Apply OAS clawback (15% above ~$95,323/yr)", key=key("oas_clawback"))
    st.checkbox("Convert RRSP to RRIF at retirement", key=key("convert_at_retirement"))
    st.caption(
        "RRIF minimum withdrawals (ITR s. 7308) and the pension-income tax "
        "credits start at the conversion age; the RRSP must be converted by 71."
    )
    if not bool(st.session_state[key("convert_at_retirement")]):
        st.number_input(
            "RRIF conversion age",
            C.RRIF_CONVERSION_MIN_AGE, C.RRIF_CONVERSION_AGE, step=1, format="%d",
            key=key("rrif_conv_age"),
        )
    _sync_person(pid)


def _plan_inputs(pid: str) -> PlanInputs:
    """Build a frozen PlanInputs for a person from the authoritative dict."""
    pi = _person(pid)
    sh = _shared()
    conv = None if bool(pi["convert_at_retirement"]) else int(pi["rrif_conv_age"])
    qpp_pct = float(pi["qpp_pct"]) / 100.0
    return PlanInputs(
        current_age=int(pi["current_age"]),
        retirement_age=int(pi["retirement_age"]),
        end_age=int(pi["end_age"]),
        rrsp_balance=float(pi["rrsp_balance"]),
        rrsp_monthly=float(pi["rrsp_monthly"]),
        tfsa_balance=float(pi["tfsa_balance"]),
        tfsa_monthly=float(pi["tfsa_monthly"]),
        nonreg_balance=float(pi["nonreg_balance"]),
        nonreg_monthly=float(pi["nonreg_monthly"]),
        annual_return=float(sh["annual_return_pct"]) / 100.0,
        inflation_rate=float(sh["inflation_pct"]) / 100.0,
        volatility=float(sh["volatility_pct"]) / 100.0,
        contribution_escalation=float(sh["escalation_pct"]) / 100.0,
        target_monthly_income=float(pi["target_monthly_income"]),
        end_income_ratio=float(pi["end_income_ratio_pct"]) / 100.0,
        steepness=float(pi["steepness"]),
        qpp_monthly_at_65=qpp_pct * C.QPP_MAX_AT_65_2025,
        qpp_start_age=int(pi["qpp_start"]),
        oas_monthly=float(pi["oas_monthly"]),
        oas_start_age=int(pi["oas_start"]),
        oas_clawback=bool(pi["oas_clawback"]),
        rrif_conversion_age=conv,
        monthly_meltdown=float(pi["monthly_meltdown"]),
    )


def retirement_year(p: PlanInputs) -> int:
    """Calendar year the person retires (offset is the same for both plans)."""
    return date.today().year + (p.retirement_age - p.current_age)


# ---------------------------------------------------------------------------
# Compute (cached on the frozen PlanInputs)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def compute(inp: PlanInputs) -> dict:
    return build_result(inp, deterministic_projection(inp), monte_carlo(inp))


def _save_plan_button() -> None:
    """'Save plan as new defaults' control (writes ``plan_defaults.json``)."""
    invalid = [pid for pid in ("me", "spouse") if validate(_plan_inputs(pid))]
    if invalid:
        st.caption("Fix the invalid plan(s) before saving.")
    if st.button(
        "💾 Save plan as new defaults",
        disabled=bool(invalid),
        help="Persist the current inputs (shared assumptions and both people) as the app's "
             "defaults. They load automatically on the next session.",
    ):
        data = {
            "shared": dict(_shared()),
            "people": {pid: dict(_person(pid)) for pid in ("me", "spouse")},
        }
        try:
            D.save_plan(data)
        except OSError as exc:
            st.error(f"Could not save the plan: {exc}")
        else:
            st.success("Saved. These inputs will open as the defaults on your next session.")


_init_state()

with st.sidebar:
    st.header("🧑‍🤝‍🧑 Plans")
    st.caption("Two independent plans share the assumptions below; personal numbers are per person.")
    editing = st.segmented_control(
        "Editing plan inputs",
        options=("me", "spouse"),
        format_func=lambda v: PERSON_LABEL[v],
        key="editing_person",
        default="me",
    )
    if editing is None:
        editing = "me"
    st.caption(f"Entering numbers for **{PERSON_LABEL[editing]}**. Switch above to edit the other.")

    _render_shared_inputs()

    st.header(f"👤 {PERSON_LABEL[editing]} — personal")
    _render_personal_inputs(editing)

    st.header("🧾 Tax")
    st.caption(
        "Income tax is modeled automatically per person: progressive federal "
        "(14%–33%) and Quebec (14%–25.75%) brackets, 2026, indexed to "
        "inflation — each taxed as a single taxpayer. No tax inputs needed."
    )
    st.header("🎲 Monte Carlo")
    st.caption(f"{D.DEFAULT_MONTE_CARLO_SIMS} simulations per plan, fixed seed {D.DEFAULT_SEED}.")

    st.divider()
    _save_plan_button()


# ---------------------------------------------------------------------------
# Validate + compute both plans
# ---------------------------------------------------------------------------
p_me = _plan_inputs("me")
p_spouse = _plan_inputs("spouse")
err_me = validate(p_me)
err_spouse = validate(p_spouse)

res_me = compute(p_me) if not err_me else None
res_spouse = compute(p_spouse) if not err_spouse else None


def _k(vals: list[float]) -> list[float]:
    """Hover values in whole thousands (e.g. 74123 -> 74k)."""
    return [v / 1000.0 for v in vals]


# ---------------------------------------------------------------------------
# Single-plan tab (used for both people)
# ---------------------------------------------------------------------------
def render_plan_tab(pid: str, label: str, p: PlanInputs, result: dict) -> None:
    prefix = "your_plan" if pid == "me" else "spouse_plan"
    other = "spouse" if pid == "me" else "me"
    other_p = _plan_inputs(other)
    st.caption(
        f"{label} — the other plan currently uses: retirement age "
        f"{other_p.retirement_age}, target income ${other_p.target_monthly_income:,.0f}/mo "
        f"(edit under the sidebar 'Editing plan inputs' control)."
    )

    rows = result["projection"]
    mc = result["montecarlo"]
    summary = dict(result["summary"])

    c1, c2, c3, c4, c5 = st.columns(5)
    det_retirement_balance = next(r["total"] for r in rows if r["age"] == p.retirement_age)
    c1.metric("Median balance at retirement (MC)", f"${mc['retirement_balance'][50]:,.0f}")
    c2.metric("Success rate (never ran out)", f"{mc['success_pct']:.1f}%")
    c3.metric("Balance at retirement (deterministic)", f"${det_retirement_balance:,.0f}")
    c4.metric("Exhaustion year", summary["Exhaustion year (deterministic)"])
    c5.metric("RRIF conversion year", str(rrif_conversion_age(p)) if p.end_age >= rrif_conversion_age(p) else "N/A")

    st.divider()

    # Chart 1: portfolio balance by age (deterministic stacked bars + MC band)
    ages = [r["age"] for r in rows]  # index-aligned with rows and the MC arrays
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ages, y=mc["total_p95"], mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ages, y=mc["total_p5"], mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(31,119,180,0.20)",
            name="P5-P95 range (Monte Carlo)",
            customdata=_k(mc["total_p5"]), hovertemplate="%{customdata:,.0f}k",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ages, y=mc["total_p50"], mode="lines", name="Median (Monte Carlo)",
            line=dict(dash="dot"),
            customdata=_k(mc["total_p50"]), hovertemplate="%{customdata:,.0f}k",
        )
    )
    det_rrsp = [r["rrsp"] for r in rows]
    det_tfsa = [r["tfsa"] for r in rows]
    det_nonreg = [r["nonreg"] for r in rows]
    fig.add_trace(
        go.Bar(x=ages, y=det_rrsp, name="RRSP", marker_color="#2ca02c", opacity=0.85,
               customdata=_k(det_rrsp), hovertemplate="%{customdata:,.0f}k")
    )
    fig.add_trace(
        go.Bar(x=ages, y=det_tfsa, name="TFSA", marker_color="#ff7f0e", opacity=0.85,
               customdata=_k(det_tfsa), hovertemplate="%{customdata:,.0f}k")
    )
    fig.add_trace(
        go.Bar(x=ages, y=det_nonreg, name="Non-registered", marker_color="#9467bd", opacity=0.85,
               customdata=_k(det_nonreg), hovertemplate="%{customdata:,.0f}k")
    )
    fig.update_layout(
        title="Total portfolio balance by age",
        xaxis_title="Age",
        yaxis_title="CAD",
        barmode="stack",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, b=30),
    )
    st.plotly_chart(fig, width="stretch", key=f"{prefix}_portfolio_chart")

    # Chart 2: before-tax income by source, today's dollars
    retirement_rows = [r for r in rows if r["age"] >= p.retirement_age]
    ages2 = [r["age"] for r in retirement_rows]
    qpp_today, oas_today, withdrawals_today, meltdown_today = [], [], [], []
    for r in retirement_rows:
        infl = (1.0 + p.inflation_rate) ** (r["age"] - p.current_age)
        qpp_today.append(r["cpp"] / infl)
        oas_today.append(r["oas"] / infl)
        withdrawals_today.append((r["withdrawal"] - r["meltdown_gross"]) / infl)
        meltdown_today.append(r["meltdown_gross"] / infl)
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=ages2, y=qpp_today, name="QPP", marker_color="#1f77b4",
                          customdata=_k(qpp_today), hovertemplate="%{customdata:,.0f}k"))
    fig2.add_trace(go.Bar(x=ages2, y=oas_today, name="OAS (net of clawback)", marker_color="#d62728",
                          customdata=_k(oas_today), hovertemplate="%{customdata:,.0f}k"))
    fig2.add_trace(go.Bar(x=ages2, y=withdrawals_today, name="Account withdrawals (spending)", marker_color="#2ca02c",
                          customdata=_k(withdrawals_today), hovertemplate="%{customdata:,.0f}k"))
    fig2.add_trace(go.Bar(x=ages2, y=meltdown_today, name="Meltdown to TFSA", marker_color="#ff7f0e",
                          customdata=_k(meltdown_today), hovertemplate="%{customdata:,.0f}k"))
    fig2.update_layout(
        title="Before-tax income by source, with meltdown to TFSA, by age (today's dollars)",
        xaxis_title="Age",
        yaxis_title="CAD (today's $)",
        barmode="stack",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, b=30),
    )
    st.plotly_chart(fig2, width="stretch", key=f"{prefix}_income_chart")

    st.divider()

    st.subheader("Year-by-year projection")
    display_rows = [
        {
            "Age": r["age"], "Year": r["year"], "Income %": round(r["income_pct"], 1),
            "Income target": round(r["income_target"], 0),
            "RRSP": round(r["rrsp"], 0), "TFSA": round(r["tfsa"], 0),
            "Non-registered": round(r["nonreg"], 0), "Total": round(r["total"], 0),
            "Withdrawal": round(r["withdrawal"], 0), "RRIF minimum": round(r["rrif_min"], 0),
            "Shortfall": round(r["shortfall"], 0), "Tax paid": round(r["tax_paid"], 0),
            "Marginal rate": round(r["marginal_rate"] * 100, 1),
            "Effective rate": round(r["effective_rate"] * 100, 1),
            "QPP": round(r["cpp"], 0), "OAS": round(r["oas"], 0),
            "OAS clawback": round(r["oas_clawback"], 0),
        }
        for r in rows
    ]
    st.dataframe(
        display_rows,
        hide_index=True,
        width="stretch",
        height=440,
        column_config={
            "Age": st.column_config.NumberColumn(label="Age", pinned=True),
            "Income %": st.column_config.NumberColumn(label="Income %", help="Income target for the year as a % of the target at retirement (S-shaped decline toward the end-age level)."),
            "Income target": st.column_config.NumberColumn(label="Income target", help="Monthly after-tax income target for the year, inflation-indexed from today's dollars."),
            "RRSP": st.column_config.NumberColumn(label="RRSP", help="End-of-year RRSP balance — withdrawals are fully taxable."),
            "TFSA": st.column_config.NumberColumn(label="TFSA", help="End-of-year TFSA balance — tax-free."),
            "Non-registered": st.column_config.NumberColumn(label="Non-registered", help="End-of-year non-registered balance (untaxed in this model)."),
            "Total": st.column_config.NumberColumn(label="Total", help="RRSP + TFSA + non-registered at year end."),
            "Withdrawal": st.column_config.NumberColumn(label="Withdrawal", help="Gross cash withdrawn from the accounts during the year."),
            "RRIF minimum": st.column_config.NumberColumn(label="RRIF minimum", help="Mandatory minimum RRIF withdrawal (ITR s. 7308) — 0 before the conversion age."),
            "Shortfall": st.column_config.NumberColumn(label="Shortfall", help="Income need not covered by pensions and withdrawals (0 = fully funded)."),
            "Tax paid": st.column_config.NumberColumn(label="Tax paid", help="Federal + Quebec income tax on QPP + OAS + RRSP/RRIF income (progressive brackets, credits, abatement)."),
            "Marginal rate": st.column_config.NumberColumn(label="Marginal rate", format="%.1f%%", help="Tax rate on the next dollar of income. Includes the age 65+ credit clawbacks (15% federal age amount, 18.75% Quebec line-361 amounts), so it rises at 65 while income is in the credit phase-out ranges."),
            "Effective rate": st.column_config.NumberColumn(label="Effective rate", format="%.1f%%", help="(Tax paid + OAS clawback) ÷ taxable income for the year — your average tax burden on CPP + OAS + RRSP/RRIF income."),
            "QPP": st.column_config.NumberColumn(label="QPP", help="QPP pension received for the year, inflation-indexed."),
            "OAS": st.column_config.NumberColumn(label="OAS", help="OAS received for the year, net of any clawback."),
            "OAS clawback": st.column_config.NumberColumn(label="OAS clawback", help="Amount recovered from OAS — 15% of income above the recovery threshold."),
        },
    )

    mc_col, key_col = st.columns([2, 3])
    with mc_col:
        st.subheader("Monte Carlo summary")
        mc_rows = [
            {"Metric": "Balance at retirement (CAD)",
             **{f"P{q}": round(mc["retirement_balance"][q], 0) for q in (5, 25, 50, 75, 95)}},
            {"Metric": "Balance at end age (CAD)",
             **{f"P{q}": round(mc["end_balance"][q], 0) for q in (5, 25, 50, 75, 95)}},
            {"Metric": "Success rate (%)", "P50": round(mc["success_pct"], 2)},
        ]
        st.dataframe(mc_rows, hide_index=True, width="stretch")

    with key_col:
        st.subheader("Key figures")
        key_rows = [
            {"Item": label, "Value": (f"{value:,.2f}" if isinstance(value, (int, float)) else str(value))}
            for label, value in result["summary"]
            if label
            in {
                "Balance at retirement, median of Monte Carlo (CAD)",
                "Balance at retirement, deterministic (CAD)",
                "Success rate: never ran out of money (%)",
                "Exhaustion year (deterministic)",
                "Years of income coverage",
                "QPP monthly at start age, first year (CAD)",
                "OAS monthly at start age, first year (CAD)",
                "Marginal tax rate at retirement, first year (%)",
                "Effective tax rate at retirement, first year (%)",
            }
        ]
        st.dataframe(key_rows, hide_index=True, width="stretch")

    st.divider()
    st.subheader("💾 Download CSVs for Google Sheets")
    st.info(
        "In Google Sheets: **File → Import → Upload** → pick each CSV → "
        "**Insert new sheet(s)**. Each file becomes its own tab and numeric cells "
        "are detected automatically."
    )
    d1, d2, d3, d4 = st.columns(4)
    d1.download_button("Download projection.csv", export.projection_csv(result),
                       file_name=f"{prefix}_projection.csv", mime="text/csv", width="stretch")
    d2.download_button("Download summary.csv", export.summary_csv(result),
                       file_name=f"{prefix}_summary.csv", mime="text/csv", width="stretch")
    d3.download_button("Download montecarlo.csv", export.montecarlo_csv(result),
                       file_name=f"{prefix}_montecarlo.csv", mime="text/csv", width="stretch")
    d4.download_button("Download all (.zip)", export.zip_bytes(result),
                       file_name=f"{prefix}_plan_csv.zip", mime="application/zip", width="stretch")


# ---------------------------------------------------------------------------
# Combined (household) tab
# ---------------------------------------------------------------------------
def render_combined(p_a: PlanInputs, res_a: dict, p_b: PlanInputs, res_b: dict) -> None:
    st.caption(
        "Household = **sum of the two plans**, each modeled and taxed as a "
        "single taxpayer (the app's documented approximation). The Monte Carlo "
        "band is the sum of the two independent runs, so it is indicative only. "
        "A person's balances carry forward at their last modeled value past "
        "their end age (their estate stays in the household)."
    )

    hh_rows = HH.household_projection(res_a["projection"], res_b["projection"])
    mc_hh = HH.household_montecarlo(res_a["montecarlo"], res_b["montecarlo"])
    years = [r["year"] for r in hh_rows]

    both_retired_year = max(retirement_year(p_a), retirement_year(p_b))
    household_ret_row = next((r for r in hh_rows if r["year"] == both_retired_year), None)
    first_shortfall = HH.first_shortfall_year(hh_rows)

    c1, c2, c3 = st.columns(3)
    c1.metric("Household balance now", f"${hh_rows[0]['total']:,.0f}")
    if household_ret_row is not None:
        c2.metric(
            f"Household balance at {both_retired_year} (both retired)",
            f"${household_ret_row['total']:,.0f}",
        )
    else:
        c2.metric("Both-retired year balance", "N/A")
    c3.metric("First household shortfall (either plan)", first_shortfall if first_shortfall is not None else "None")

    st.divider()

    # Chart 1: household balance by calendar year (account types across both
    # people stacked, with the summed-MC band)
    det_rrsp = [r["rrsp"] for r in hh_rows]
    det_tfsa = [r["tfsa"] for r in hh_rows]
    det_nonreg = [r["nonreg"] for r in hh_rows]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=years, y=mc_hh["total_p95"], mode="lines", line=dict(width=0),
                   showlegend=False, hoverinfo="skip")
    )
    fig.add_trace(
        go.Scatter(x=years, y=mc_hh["total_p5"], mode="lines", line=dict(width=0),
                   fill="tonexty", fillcolor="rgba(31,119,180,0.20)",
                   name="P5-P95 range (MC, sum of plans)",
                   customdata=_k(mc_hh["total_p5"]), hovertemplate="%{customdata:,.0f}k")
    )
    fig.add_trace(
        go.Scatter(x=years, y=mc_hh["total_p50"], mode="lines", name="Median (MC, sum of plans)",
                   line=dict(dash="dot"),
                   customdata=_k(mc_hh["total_p50"]), hovertemplate="%{customdata:,.0f}k")
    )
    fig.add_trace(go.Bar(x=years, y=det_rrsp, name="RRSP", marker_color="#2ca02c", opacity=0.85,
                         customdata=_k(det_rrsp), hovertemplate="%{customdata:,.0f}k"))
    fig.add_trace(go.Bar(x=years, y=det_tfsa, name="TFSA", marker_color="#ff7f0e", opacity=0.85,
                         customdata=_k(det_tfsa), hovertemplate="%{customdata:,.0f}k"))
    fig.add_trace(go.Bar(x=years, y=det_nonreg, name="Non-registered", marker_color="#9467bd", opacity=0.85,
                         customdata=_k(det_nonreg), hovertemplate="%{customdata:,.0f}k"))
    fig.update_layout(
        title="Household total balance by calendar year (by account type)",
        xaxis_title="Year",
        yaxis_title="CAD",
        barmode="stack",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, b=30),
    )
    st.plotly_chart(fig, width="stretch", key="household_portfolio_chart")

    # Chart 2: household before-tax income by source, today's dollars
    infl_rate = p_a.inflation_rate
    income_start = min(retirement_year(p_a), retirement_year(p_b))
    income_rows = [r for r in hh_rows if r["year"] >= income_start]
    inc_years = [r["year"] for r in income_rows]
    qpp_t, oas_t, spend_t, melt_t = [], [], [], []
    for r in income_rows:
        infl = (1.0 + infl_rate) ** (r["year"] - income_start)
        qpp_t.append(r["cpp"] / infl)
        oas_t.append(r["oas"] / infl)
        spend_t.append((r["withdrawal"] - r["meltdown_gross"]) / infl)
        melt_t.append(r["meltdown_gross"] / infl)
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=inc_years, y=qpp_t, name="QPP (both)", marker_color="#1f77b4",
                          customdata=_k(qpp_t), hovertemplate="%{customdata:,.0f}k"))
    fig2.add_trace(go.Bar(x=inc_years, y=oas_t, name="OAS (both, net of clawback)", marker_color="#d62728",
                          customdata=_k(oas_t), hovertemplate="%{customdata:,.0f}k"))
    fig2.add_trace(go.Bar(x=inc_years, y=spend_t, name="Account withdrawals (spending)", marker_color="#2ca02c",
                          customdata=_k(spend_t), hovertemplate="%{customdata:,.0f}k"))
    fig2.add_trace(go.Bar(x=inc_years, y=melt_t, name="Meltdown to TFSA", marker_color="#ff7f0e",
                          customdata=_k(melt_t), hovertemplate="%{customdata:,.0f}k"))
    fig2.update_layout(
        title="Household before-tax income by source, with meltdown to TFSA, by year (today's dollars)",
        xaxis_title="Year",
        yaxis_title="CAD (today's $)",
        barmode="stack",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, b=30),
    )
    st.plotly_chart(fig2, width="stretch", key="household_income_chart")

    st.divider()
    st.subheader("Household year-by-year (calendar year)")
    display_rows = [
        {
            "Year": r["year"],
            "Your age": r["age_a"],
            "Spouse's age": r["age_b"],
            "RRSP": round(r["rrsp"], 0),
            "TFSA": round(r["tfsa"], 0),
            "Non-registered": round(r["nonreg"], 0),
            "Total": round(r["total"], 0),
            "Income target": round(r["income_target"], 0),
            "Withdrawal": round(r["withdrawal"], 0),
            "QPP": round(r["cpp"], 0),
            "OAS": round(r["oas"], 0),
            "Tax paid": round(r["tax_paid"], 0),
            "Shortfall": round(r["shortfall"], 0),
        }
        for r in hh_rows
    ]
    st.dataframe(
        display_rows,
        hide_index=True,
        width="stretch",
        height=440,
        column_config={
            "Year": st.column_config.NumberColumn(label="Year", pinned=True),
            "Your age": st.column_config.NumberColumn(label="Your age"),
            "Spouse's age": st.column_config.NumberColumn(label="Spouse's age"),
            "RRSP": st.column_config.NumberColumn(label="RRSP", help="Sum of both plans' RRSP/RRIF balances at year end."),
            "TFSA": st.column_config.NumberColumn(label="TFSA", help="Sum of both plans' TFSA balances at year end."),
            "Non-registered": st.column_config.NumberColumn(label="Non-registered", help="Sum of both plans' non-registered balances at year end."),
            "Total": st.column_config.NumberColumn(label="Total", help="RRSP + TFSA + non-registered across both plans."),
            "Income target": st.column_config.NumberColumn(label="Income target", help="Sum of the monthly after-tax income targets (household spending), where a person is retired."),
            "Withdrawal": st.column_config.NumberColumn(label="Withdrawal", help="Sum of gross cash withdrawn from both plans' accounts during the year."),
            "QPP": st.column_config.NumberColumn(label="QPP", help="QPP received by both people for the year, inflation-indexed."),
            "OAS": st.column_config.NumberColumn(label="OAS", help="OAS received by both people, net of any clawback."),
            "Tax paid": st.column_config.NumberColumn(label="Tax paid", help="Sum of both plans' federal + Quebec income tax (each taxed as a single taxpayer)."),
            "Shortfall": st.column_config.NumberColumn(label="Shortfall", help="Sum of either plan's uncovered income need (0 = fully funded)."),
        },
    )

    st.divider()
    st.subheader("💾 Download household CSV")
    st.download_button(
        "Download household_projection.csv",
        export.household_projection_csv(hh_rows),
        file_name="household_projection.csv",
        mime="text/csv",
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_me, tab_spouse, tab_combined = st.tabs(["Your plan", "Spouse's plan", "Combined"])

with tab_me:
    if err_me:
        st.error("Your plan has invalid inputs:")
        for e in err_me:
            st.error(e)
    else:
        render_plan_tab("me", "Your plan", p_me, res_me)

with tab_spouse:
    if err_spouse:
        st.error("Spouse's plan has invalid inputs:")
        for e in err_spouse:
            st.error(e)
    else:
        render_plan_tab("spouse", "Spouse's plan", p_spouse, res_spouse)

with tab_combined:
    if err_me or err_spouse:
        st.error("The Combined view needs both plans to have valid inputs.")
        for pid, errs in (("me", err_me), ("spouse", err_spouse)):
            if errs:
                st.markdown(f"**{PERSON_LABEL[pid]}:**")
                for e in errs:
                    st.write(f"- {e}")
    else:
        render_combined(p_me, res_me, p_spouse, res_spouse)
