"""Backward-compatible wrapper for scripts.analysis.analys_comprehensive."""

from __future__ import annotations

from scripts.analysis import analys_comprehensive as _impl

main = _impl.main


if __name__ == "__main__":
    main()
