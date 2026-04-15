"""Backward-compatible wrapper for dashboard.app."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_DASHBOARD_APP_PATH = Path(__file__).resolve().parent / "dashboard" / "app.py"
_SPEC = importlib.util.spec_from_file_location("buybaybye_dashboard_app", _DASHBOARD_APP_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load dashboard app from {_DASHBOARD_APP_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_MODULE, _name)
