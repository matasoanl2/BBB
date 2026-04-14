---
description: "Use when editing BuyBayBye runtime Python files under buybaybye/. Covers runtime layers, websocket/accounting behavior, betting flow, and shared state boundaries."
applyTo: "buybaybye/**/*.py"
---
# Runtime Python Guidelines

- Keep runtime changes inside the existing layers: immutable env config in `runtime_config.py`, mutable shared state in `runtime_context.py`, orchestration in `runtime_app.py` and `runtime_factory.py`, and domain behavior in service or subsystem modules.
- Prefer threading `RuntimeConfig` and `RuntimeContext` through services and helpers instead of adding globals, singleton state, or fresh scattered `os.getenv` reads.
- Preserve current runtime behavior around accounting, websocket, and betting flows unless the task explicitly changes it.
- Treat accounting and websocket payload semantics as project-specific. Follow observed payloads and existing guards instead of assuming generic betting-platform behavior.
- Preserve Russian user-facing logs and the current columnar ANSI-aware log format. Keep code identifiers in English.
- Keep dashboard, analysis, and utility-script concerns out of `buybaybye/` runtime modules unless the task genuinely spans both areas.
- When changing bet placement or accounting reconciliation, keep `pending_expected_bet_drop`, strategy step advancement, and session profit/balance transitions internally consistent.