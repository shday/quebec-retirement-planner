"""Deployment-runtime detection for the app.

Streamlit Community Cloud exposes no reliable built-in env var to detect that
the app is running on the platform (confirmed via Streamlit's docs and the
community forum), so the app uses an explicit opt-in marker instead:

- Setting ``STREAMLIT_CLOUD`` to ``1``, ``true``, or ``yes`` (case-insensitive)
  puts the app in "Cloud mode": persistence is local-first (Download/Load the
  plan as a JSON file) and nothing is written to the ephemeral container
  filesystem.
- Unset or any other value means local mode, preserving the original
  file-based "Save plan as new defaults" behaviour.

The app reads this once at startup (``is_streamlit_cloud()``) rather than on
every run. Setting it locally is the intended way to exercise the Cloud branch
without deploying.

Pure stdlib so it is unit-testable with no Streamlit import.
"""

from __future__ import annotations

import os

_TRUE_VALUES = frozenset({"1", "true", "yes"})


def is_streamlit_cloud() -> bool:
    """True when ``STREAMLIT_CLOUD`` is set to a truthy value."""
    return os.getenv("STREAMLIT_CLOUD", "").strip().lower() in _TRUE_VALUES
