from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_offline_script_entrypoints_support_direct_execution() -> None:
    script_paths = [
        ROOT_DIR / "scripts" / "analysis" / "compare_strategies.py",
        ROOT_DIR / "scripts" / "analysis" / "analys_comprehensive.py",
        ROOT_DIR / "scripts" / "data" / "import_export.py",
    ]

    for script_path in script_paths:
        completed = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        assert "usage:" in completed.stdout.lower()