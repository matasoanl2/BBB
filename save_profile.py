"""Backward-compatible wrapper for scripts.profile.save_profile."""

from __future__ import annotations

from scripts.profile import save_profile as _impl

main = _impl.main


if __name__ == "__main__":
    main()
