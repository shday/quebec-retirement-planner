"""Planning defaults and saved-plan persistence.

Owns two things:

1. **Engine default inputs.** The ``DEFAULT_*`` scalar values that seed the
   model (``projection.PlanInputs`` field defaults) and its Monte Carlo. These
   were formerly in ``constants.py``; they are relocated here so that
   ``constants.py`` holds only statutory values (RRIF minimums, QPP/OAS
   factors, 2026 tax brackets/credits). They are fixed model defaults and do
   NOT change when the user saves a plan.

2. **The app's default plan (saved state).** A single household plan of input
   values the app opens with. It lives in a local JSON file
   (``plan_defaults.json``, git-ignored) that is seeded on first run from a
   committed example (``defaults.example.json``). The **Save plan** control in
   the app writes the current inputs back to ``plan_defaults.json``; the next
   session starts from them. The plan uses the app's "display units" schema
   (see ``SHARED_FIELDS`` / ``PERSON_FIELDS``).

Everything here is pure stdlib (no Streamlit), so it is unit-testable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import constants as C

# ---------------------------------------------------------------------------
# Engine default inputs (fraction / model units where applicable)
# These mirror the old "Planning defaults" block of constants.py.
# ---------------------------------------------------------------------------
# Personal
DEFAULT_CURRENT_AGE = 55
DEFAULT_RETIREMENT_AGE = 65
DEFAULT_END_AGE = 90                    # life expectancy

# Accounts (current balance + monthly contribution until retirement)
DEFAULT_RRSP_BALANCE = 250_000
DEFAULT_RRSP_MONTHLY = 600
DEFAULT_TFSA_BALANCE = 0
DEFAULT_TFSA_MONTHLY = 0
DEFAULT_NONREG_BALANCE = 0
DEFAULT_NONREG_MONTHLY = 0

# Assumptions
DEFAULT_ANNUAL_RETURN = 0.05            # nominal, before inflation
DEFAULT_INFLATION = 0.0225
DEFAULT_VOLATILITY = 0.05               # annual std dev of returns, Monte Carlo
DEFAULT_CONTRIBUTION_ESCALATION = 0.0   # annual growth of monthly contributions

# Retirement income
DEFAULT_TARGET_MONTHLY_INCOME = 4_000   # today's CAD
DEFAULT_END_INCOME_RATIO = 0.65         # income at end age, as a fraction of retirement income
DEFAULT_QPP_PCT_OF_MAX = 0.85           # QPP at 65, as a fraction of the maximum pension
DEFAULT_QPP_START_AGE = 72
DEFAULT_OAS_START_AGE = 70
DEFAULT_OAS_CLAWBACK = True
DEFAULT_RRIF_CONVERSION_AGE = None      # None = convert RRSP to RRIF at retirement age
DEFAULT_MONTHLY_MELTDOWN = 0.0          # monthly TFSA savings (meltdown), today's CAD; 0 = off

# Monte Carlo
DEFAULT_MONTE_CARLO_SIMS = 1_000
DEFAULT_SEED = 42

# ---------------------------------------------------------------------------
# Display-unit schema of a saved plan (maps 1:1 to the sidebar widgets).
# Percentages are whole 0-100, not fractions; oas_monthly is dollars.
# ---------------------------------------------------------------------------
SHARED_FIELDS = (
    "annual_return_pct",
    "inflation_pct",
    "volatility_pct",
    "escalation_pct",
)

PERSON_FIELDS = (
    "current_age",
    "retirement_age",
    "end_age",
    "rrsp_balance",
    "rrsp_monthly",
    "tfsa_balance",
    "tfsa_monthly",
    "nonreg_balance",
    "nonreg_monthly",
    "target_monthly_income",
    "end_income_ratio_pct",  # 0-100
    "qpp_pct",               # 0-100
    "qpp_start",
    "oas_monthly",
    "oas_start",
    "oas_clawback",
    "convert_at_retirement",
    "rrif_conv_age",
    "monthly_meltdown",
)

_INT_FIELDS = {
    "current_age", "retirement_age", "end_age",
    "rrsp_balance", "rrsp_monthly", "tfsa_balance", "tfsa_monthly",
    "nonreg_balance", "nonreg_monthly", "target_monthly_income",
    "end_income_ratio_pct", "qpp_pct", "qpp_start", "oas_start",
    "rrif_conv_age", "monthly_meltdown",
}
_FLOAT_FIELDS = {
    "oas_monthly",
    "annual_return_pct", "inflation_pct", "volatility_pct", "escalation_pct",
}
_BOOL_FIELDS = {"oas_clawback", "convert_at_retirement"}

_PERSON_KEYS = tuple(PERSON_FIELDS)
_SHARED_KEYS = tuple(SHARED_FIELDS)
_PEOPLE_KEYS = ("me", "spouse")


# ---------------------------------------------------------------------------
# Factory (built-in) default plan, in display units
# ---------------------------------------------------------------------------
def factory_shared() -> dict:
    return {
        "annual_return_pct": DEFAULT_ANNUAL_RETURN * 100.0,           # 5.0
        "inflation_pct": DEFAULT_INFLATION * 100.0,                   # 2.25
        "volatility_pct": DEFAULT_VOLATILITY * 100.0,                 # 5.0
        "escalation_pct": DEFAULT_CONTRIBUTION_ESCALATION * 100.0,    # 0.0
    }


def factory_person() -> dict:
    return {
        "current_age": DEFAULT_CURRENT_AGE,
        "retirement_age": DEFAULT_RETIREMENT_AGE,
        "end_age": DEFAULT_END_AGE,
        "rrsp_balance": DEFAULT_RRSP_BALANCE,
        "rrsp_monthly": DEFAULT_RRSP_MONTHLY,
        "tfsa_balance": DEFAULT_TFSA_BALANCE,
        "tfsa_monthly": DEFAULT_TFSA_MONTHLY,
        "nonreg_balance": DEFAULT_NONREG_BALANCE,
        "nonreg_monthly": DEFAULT_NONREG_MONTHLY,
        "target_monthly_income": DEFAULT_TARGET_MONTHLY_INCOME,
        "end_income_ratio_pct": int(DEFAULT_END_INCOME_RATIO * 100.0),  # 65
        "qpp_pct": int(DEFAULT_QPP_PCT_OF_MAX * 100.0),                 # 85
        "qpp_start": DEFAULT_QPP_START_AGE,                             # 72
        "oas_monthly": C.OAS_MAX_2025,
        "oas_start": DEFAULT_OAS_START_AGE,                             # 70
        "oas_clawback": DEFAULT_OAS_CLAWBACK,                           # True
        "convert_at_retirement": DEFAULT_RRIF_CONVERSION_AGE is None,   # True
        "rrif_conv_age": C.RRIF_CONVERSION_AGE,                         # 71
        "monthly_meltdown": int(DEFAULT_MONTHLY_MELTDOWN),              # 500
    }


def factory_plan() -> dict:
    """The canonical built-in default plan (both people identical)."""
    person = factory_person()
    return {"shared": factory_shared(), "people": {"me": dict(person), "spouse": dict(person)}}


# ---------------------------------------------------------------------------
# Paths (resolved relative to this module so CWD does not matter)
# ---------------------------------------------------------------------------
_MODULE_DIR = Path(__file__).resolve().parent
SEED_PATH = _MODULE_DIR / "defaults.example.json"   # committed
PLAN_PATH = _MODULE_DIR / "plan_defaults.json"       # git-ignored (user's saved plan)


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------
def _write_json(path: Path, data: dict) -> None:
    """Write data atomically (temp file + replace) with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _coerce_value(field: str, value):
    """Coerce a single display-unit value from a (possibly hand-edited) file."""
    try:
        if field in _BOOL_FIELDS:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() == "true"
        if field in _INT_FIELDS:
            return int(value)
        if field in _FLOAT_FIELDS:
            return float(value)
    except (TypeError, ValueError):
        return value
    return value


def _coerce_person(person: dict) -> dict:
    out = {}
    for f in _PERSON_KEYS:
        if f in person:
            out[f] = _coerce_value(f, person[f])
    return out


def _coerce(data: dict) -> dict:
    out: dict = {"shared": {}, "people": {}}
    shared = data.get("shared")
    if isinstance(shared, dict):
        out["shared"] = {f: _coerce_value(f, shared[f]) for f in _SHARED_KEYS if f in shared}
    people = data.get("people")
    if isinstance(people, dict):
        for pid in _PEOPLE_KEYS:
            p = people.get(pid)
            if isinstance(p, dict):
                out["people"][pid] = _coerce_person(p)
    return out


def plan_fields_complete(data: dict) -> bool:
    """True if the dict has shared + both people with every expected field."""
    if not isinstance(data, dict):
        return False
    shared = data.get("shared")
    if not isinstance(shared, dict) or not all(f in shared for f in _SHARED_KEYS):
        return False
    people = data.get("people")
    if not isinstance(people, dict):
        return False
    for pid in _PEOPLE_KEYS:
        p = people.get(pid)
        if not isinstance(p, dict) or not all(f in p for f in _PERSON_KEYS):
            return False
    return True


def load_plan(plan_path: Path | str | None = None, seed_path: Path | str | None = None) -> dict:
    """Return the saved plan (``plan_defaults.json``), falling back to factory.

    - If the personal plan file is missing, it is seeded from the committed
      example file (or the factory, if that is missing too) and written.
    - Corrupt or incomplete content is replaced with the factory defaults and
      the file rewritten so it self-heals on the next start.
    """
    pp = Path(plan_path) if plan_path is not None else PLAN_PATH
    sp = Path(seed_path) if seed_path is not None else SEED_PATH

    rewrite = not pp.exists()
    data: dict | None = None
    if pp.exists():
        data = _read_json(pp)
        if data is None:
            rewrite = True  # corrupt -> heal it from the seed/factory
    if data is None and sp.exists():
        data = _read_json(sp)
    if data is None:
        data = factory_plan()
    data = _coerce(data)
    if not plan_fields_complete(data):
        data = factory_plan()
        rewrite = True
    if rewrite:
        _write_json(pp, data)
    return data


def save_plan(data: dict, plan_path: Path | str | None = None) -> None:
    """Persist a plan dict as the app's defaults."""
    pp = Path(plan_path) if plan_path is not None else PLAN_PATH
    _write_json(pp, data)


def write_seed(path: Path | str | None = None) -> None:
    """Write the factory plan to a JSON file (used to (re)generate the committed
    example seed and by tests)."""
    _write_json(Path(path) if path is not None else SEED_PATH, factory_plan())
