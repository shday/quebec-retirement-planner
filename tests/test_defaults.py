"""Tests for defaults.py: engine defaults, factory plan, and JSON persistence."""

import json

import pytest

import defaults as D
from projection import PlanInputs


def test_engine_defaults_still_seed_plan_inputs():
    # The model's built-in defaults moved out of constants.py into defaults.py;
    # PlanInputs() must still resolve to them.
    p = PlanInputs()
    assert p.current_age == D.DEFAULT_CURRENT_AGE
    assert p.retirement_age == D.DEFAULT_RETIREMENT_AGE
    assert p.end_age == D.DEFAULT_END_AGE
    assert p.annual_return == D.DEFAULT_ANNUAL_RETURN
    assert p.inflation_rate == D.DEFAULT_INFLATION
    assert p.target_monthly_income == D.DEFAULT_TARGET_MONTHLY_INCOME
    assert p.num_sims == D.DEFAULT_MONTE_CARLO_SIMS
    assert p.seed == D.DEFAULT_SEED


def test_factory_plan_matches_engine_defaults_and_people_identical():
    plan = D.factory_plan()
    assert D.plan_fields_complete(plan)
    sh = plan["shared"]
    assert sh["annual_return_pct"] == pytest.approx(D.DEFAULT_ANNUAL_RETURN * 100.0)
    assert sh["inflation_pct"] == pytest.approx(D.DEFAULT_INFLATION * 100.0)
    me = plan["people"]["me"]
    assert me["current_age"] == D.DEFAULT_CURRENT_AGE
    assert me["rrsp_balance"] == D.DEFAULT_RRSP_BALANCE
    assert me["target_monthly_income"] == D.DEFAULT_TARGET_MONTHLY_INCOME
    assert me["end_income_ratio_pct"] == int(D.DEFAULT_END_INCOME_RATIO * 100.0)
    assert me["qpp_pct"] == int(D.DEFAULT_QPP_PCT_OF_MAX * 100.0)
    assert me["oas_clawback"] is True and me["convert_at_retirement"] is True
    assert plan["people"]["spouse"] == me  # both people start identical


def test_field_lists_are_covered_by_coercion_types(tmp_path):
    # Every serialized field must be classified (int/float/bool) so coercion
    # never silently drops a field.
    covered = D._INT_FIELDS | D._FLOAT_FIELDS | D._BOOL_FIELDS
    for f in D.PERSON_FIELDS + D.SHARED_FIELDS:
        assert f in covered


def test_load_creates_personal_file_from_seed(tmp_path):
    seed = tmp_path / "defaults.example.json"
    plan_file = tmp_path / "plan_defaults.json"
    D.write_seed(seed)
    plan = D.load_plan(plan_path=plan_file, seed_path=seed)
    assert plan == D.factory_plan()
    assert plan_file.exists()  # personal file was materialized


def test_save_plan_load_round_trip_preserves_values(tmp_path):
    plan_file = tmp_path / "plan_defaults.json"
    data = D.factory_plan()
    data["shared"]["annual_return_pct"] = 6.25
    data["shared"]["inflation_pct"] = 2.0
    data["people"]["me"]["current_age"] = 55
    data["people"]["me"]["rrsp_balance"] = 750_000
    data["people"]["me"]["oas_clawback"] = False
    data["people"]["me"]["convert_at_retirement"] = False
    data["people"]["me"]["rrif_conv_age"] = 60
    data["people"]["spouse"]["current_age"] = 52
    data["people"]["spouse"]["monthly_meltdown"] = 300
    D.save_plan(data, plan_path=plan_file)
    loaded = D.load_plan(plan_path=plan_file)
    assert loaded == data
    assert loaded["people"]["me"]["current_age"] == 55
    assert loaded["people"]["me"]["oas_clawback"] is False
    assert loaded["shared"]["annual_return_pct"] == pytest.approx(6.25)


def test_corrupt_personal_file_falls_back_to_factory_and_rewrites(tmp_path):
    seed = tmp_path / "defaults.example.json"
    plan_file = tmp_path / "plan_defaults.json"
    D.write_seed(seed)
    plan_file.write_text("{ not valid json !!!")
    plan = D.load_plan(plan_path=plan_file, seed_path=seed)
    assert plan == D.factory_plan()
    assert D.plan_fields_complete(json.loads(plan_file.read_text()))


def test_load_coerces_stringly_typed_values(tmp_path):
    plan_file = tmp_path / "plan_defaults.json"
    data = D.factory_plan()
    # Simulate a hand-edited file where some numbers are quoted.
    data["shared"]["annual_return_pct"] = "6.0"
    data["people"]["me"]["current_age"] = "62"
    data["people"]["me"]["oas_clawback"] = "false"
    data["people"]["me"]["oas_monthly"] = "800"
    plan_file.write_text(json.dumps(data))
    loaded = D.load_plan(plan_path=plan_file)
    assert loaded["shared"]["annual_return_pct"] == 6.0
    assert loaded["people"]["me"]["current_age"] == 62
    assert loaded["people"]["me"]["oas_clawback"] is False
    assert isinstance(loaded["people"]["me"]["oas_monthly"], float)


def test_plan_fields_complete_rejects_partial():
    assert D.plan_fields_complete(D.factory_plan())
    partial = D.factory_plan()
    del partial["people"]["spouse"]
    assert not D.plan_fields_complete(partial)
    assert not D.plan_fields_complete({"shared": {}})


def test_committed_example_seed_matches_factory(tmp_path):
    # Guard against drift between the committed defaults.example.json and the
    # canonical factory values used by the code/tests.
    seed = D.SEED_PATH
    if not seed.exists():
        pytest.skip("committed example seed not present")
    parsed = json.loads(seed.read_text())
    assert parsed == D.factory_plan()
