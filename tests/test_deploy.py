"""Tests for deploy.py: STREAMLIT_CLOUD detection."""

import pytest

import deploy as DEPLOY


@pytest.mark.parametrize(
    "value",
    ["1", "true", "TRUE", "True", "yes", "YES", " 1 ", " true "],
)
def test_truthy_values_return_true(monkeypatch, value):
    monkeypatch.setenv("STREAMLIT_CLOUD", value)
    assert DEPLOY.is_streamlit_cloud() is True


@pytest.mark.parametrize(
    "value",
    ["0", "false", "no", "on", "cloud", "anything-else", " "],
)
def test_non_truthy_values_return_false(monkeypatch, value):
    monkeypatch.setenv("STREAMLIT_CLOUD", value)
    assert DEPLOY.is_streamlit_cloud() is False


def test_unset_returns_false(monkeypatch):
    monkeypatch.delenv("STREAMLIT_CLOUD", raising=False)
    assert DEPLOY.is_streamlit_cloud() is False
