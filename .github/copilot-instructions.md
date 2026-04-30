# Project Guidelines — BuyBayBye

## Overview

Automated betting data collector and strategy runner for the betboom.ru dice game.

- Main runtime entrypoint: `main.py`
- Runtime package: `buybaybye/`
- Dashboard app: `dashboard.py`
- Strategy definitions: `strategies/*.yaml`
- Environment file exists in the workspace as `.env`, but runtime code reads settings via `os.getenv`; Docker Compose injects `.env` through `env_file`

User-facing logs and comments are in Russian. Code identifiers stay in English.

## Architecture

The runtime is modularized.

- `main.py` is a thin entrypoint that builds runtime components and runs the app
- `buybaybye/runtime_factory.py` assembles config, context, services, and app
- `buybaybye/runtime_config.py` contains immutable env-derived config dataclasses
- `buybaybye/runtime_context.py` contains mutable shared runtime state
- `buybaybye/runtime_app.py` owns startup, browser lifecycle, and shutdown flow
- `buybaybye/runtime_services.py` is a facade over narrower runtime services
- `buybaybye/runtime_auth_service.py`, `runtime_accounting_service.py`, `runtime_betting_service.py`, and `runtime_infrastructure_service.py` split runtime responsibilities by domain
- `buybaybye/betting.py`, `dynamic_betting.py`, `accounting.py`, `browser_ws.py`, `jwt_capture.py`, `db.py`, and `runtime_snapshot.py` contain subsystem logic
- `dashboard.py` is a separate FastAPI app backed by PostgreSQL tables `game_results`, `bet_history`, `runtime_snapshot`, and `runtime_events`

For broader product behavior and operator-facing details, link to `README.md` instead of duplicating it.

## Build and Test

```bash
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
patchright install chromium
python main.py
```

```bash
docker compose up --build
docker compose up -d postgres
docker compose up -d dashboard
```

```bash
uvicorn dashboard:app --host 0.0.0.0 --port 8000
python analys_comprehensive.py
python compare_strategies.py
python import_export.py
python save_profile.py
```

There is no automated test suite yet. If tests are added, use `pytest`.

## Conventions

- Keep changes consistent with the modular runtime layout; do not move logic back into `main.py`
- Strategies are data, not code: add or change betting progressions in `strategies/*.yaml`, not in Python code
- `BASE_BET × coefficient` must stay divisible by 10; strategy coefficients are expected to be integers
- When writing or updating a strategy YAML, always check if `# банк:` already exists on line 4 before adding it; if it exists, **update** the existing line in place — never duplicate it
- Read config through the runtime config layer for runtime code; avoid scattering fresh `os.getenv` reads across runtime services unless there is a clear reason
- Preserve the current logging style: Russian user-facing strings, columnar bet logs, ANSI-color-aware formatting, and emoji width compensation
- Prefer extending the existing runtime layers (`runtime_config`, `runtime_context`, service modules) rather than introducing new globals
- Keep dashboard changes separate from betting runtime changes unless a task genuinely spans both

## Gotchas

- `profile/` contains live Chromium session data; never delete it while the browser is running
- `postgres_data/` is a live Docker-mounted PostgreSQL data directory; treat it as read-only from the repo side
- PowerShell execution policy may block venv activation; running `venv\Scripts\python.exe` directly is a valid fallback
- `wcwidth` should remain installed for correct terminal alignment of ANSI-colored emoji logs
- `reports/` is generated output from strategy comparison scripts; avoid committing large report artifacts
- Accounting balance handling is websocket-driven and project-specific; follow the observed runtime payload behavior in code rather than assuming generic semantics
- When a SET API call fails, strategy step advancement can change without changing session profit or balance because the stake was returned
