# Project Guidelines — BuyBayBye

## Overview

Automated betting data collector + strategy runner for betboom.ru dice game.
Single Python file (`main.py`) using Patchright browser automation, PostgreSQL storage, and YAML-based betting strategies.

**Language:** Russian comments/logs, English code identifiers.

## Architecture

| File | Purpose |
|------|---------|
| `main.py` | Core: browser automation (Patchright), WebSocket interception, bet placement via REST API, colored terminal logging (~1800 lines) |
| `analys_comprehensive.py` | Offline simulation of strategies against historical DB data |
| `compare_strategies.py` | CLI comparison of strategies across bet combinations; saves reports to `reports/` |
| `import_export.py` | JSON ↔ PostgreSQL bulk import/export |
| `save_profile.py` | Browser profile backup utility |
| `strategies/*.yaml` | One strategy per file — coefficients, payout, reset condition |
| `.env` | All runtime configuration (loaded via `python-dotenv`) |

**Key patterns:**
- All config via env vars (`os.getenv`), loaded from `.env` by `python-dotenv`
- Boolean env vars: `"true"/"false"` parsed with `.lower() in {"1", "true", "yes", "on"}`
- DB tables: `game_results` (dice rolls), `bet_history` (placed bets) — auto-created on startup
- Strategies loaded from `strategies/` via `glob("*.yaml")`, key = filename stem
- Browser profile persisted in `profile/` for session reuse
- JWT token auto-detected from network traffic (multiple sources)
- Dynamic betting mode (`DYNAMIC_BET_MODE`): analyzes recent results, auto-selects best outcome+specifier combo on configurable interval
- Real-time balance via second WebSocket (`ACCOUNTING_WS_URL`); only `balance_type == 0` messages are real-money balance (freebets have `balance_type != 0`)

## Build and Test

```bash
# Local (requires venv)
python -m venv venv
venv\Scripts\activate.bat          # Windows
pip install -r requirements.txt
patchright install chromium

# Run
python main.py

# Docker
docker compose up --build
docker compose up -d postgres      # DB only (for local dev)
```

**No test suite exists.** When adding tests, use `pytest`.

## Code Conventions

- **Single-file architecture**: `main.py` contains all runtime logic (~1800 lines). Do not split without explicit request.
- **Strategies are data, not code**: add new strategies as YAML files in `strategies/`, never hardcode coefficients.
- **Bet amounts must be divisible by 10**: `BASE_BET × coefficient` is validated on load. All coefficients must be integers.
- **Logging format**: unified columnar format via `_format_bet_log()` with ANSI colors and emoji. Uses `_visible_length()` + `_pad_width()` with ANSI+emoji terminal compensation (`_ansi_emoji_compensation`).
- **Emoji terminal width**: known emoji are forced to 2 columns (`_DOUBLE_WIDTH_EMOJI` set + `FORCE_DOUBLE_WIDTH_EMOJI=true`). ANSI color wrapping multiple emoji causes extra column per emoji — compensated in `_pad_width`.
- **Comments and user-facing strings** in Russian. Function/variable names in English.
- **No type checking or linter configured.** Use `from __future__ import annotations` for type hints.

## Gotchas

- `profile/` contains live Chromium session data — never delete while browser is running
- `postgres_data/` is a live PostgreSQL data directory mounted by Docker — treat as read-only
- WebSocket URL and bet API URL are hardcoded constants at the top of `main.py`
- `wcwidth` is an optional dependency but should be installed for accurate column alignment
- PowerShell execution policy may block venv activation — use `cmd` or run `venv\Scripts\python.exe` directly
- `reports/` is auto-created by `compare_strategies.py` — do not commit large report files
- `_advance_step_after_set_error()`: when a SET API error occurs, step advances but `session_balance`/profit stay unchanged (money was returned)
