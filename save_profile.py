"""Backward-compatible wrapper for scripts.profile.save_profile."""

from __future__ import annotations

from scripts.profile.save_profile import *  # noqa: F401,F403

if __name__ == "__main__":
    main()
