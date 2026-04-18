"""Backward-compatible wrapper for scripts.data.import_export."""

from __future__ import annotations

from scripts.data import import_export as _impl

main = _impl.main


if __name__ == "__main__":
    main()
