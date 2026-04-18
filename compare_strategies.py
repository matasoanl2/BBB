"""Backward-compatible wrapper for scripts.analysis.compare_strategies."""

from __future__ import annotations

from scripts.analysis import compare_strategies as _impl

main = _impl.main


if __name__ == "__main__":
    main()
