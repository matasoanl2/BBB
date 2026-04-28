import json
from pathlib import Path

from buybaybye.core.runtime_config import (
    AccountingConfig,
    BettingConfig,
    BrowserConfig,
    ColorConfig,
    DatabaseConfig,
    DynamicBettingConfig,
    LoggingConfig,
    RuntimeConfig,
    RuntimeRoleConfig,
    TelegramConfig,
)
from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_state import build_runtime_betting_state
from buybaybye.modules.accounting import update_balance_from_accounting_payload


def make_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        role=RuntimeRoleConfig("bettor", True, True, False),
        browser=BrowserConfig(Path("profile"), Path("strategies"), "target", "accounting", "bet", False),
        database=DatabaseConfig("postgres", "postgres", "localhost", "5432", "buybaybye"),
        betting=BettingConfig(True, True, tuple(), "", None, "red", "5", 10.0, 0.0, "balanced", 0.8, 1.5, False),
        dynamic_betting=DynamicBettingConfig(True, 40, 5, True, True, True, False, False, True, 15),
        accounting=AccountingConfig(15.0, 25.0, 30.0, 300.0, 300.0, 3.0, False),
        telegram=TelegramConfig(False, "", "", 5.0, 60.0, True, True, True, True, True),
        logging=LoggingConfig(False, True),
        colors=ColorConfig(True, "", "", "", "", "", "", ""),
    )


def test_accounting_detects_external_deposit() -> None:
    runtime_context = RuntimeContext(bet_mode_outcome="red", bet_mode_specifier="5")
    runtime_context.betting_state = build_runtime_betting_state(strategy=None, bet_mode_outcome="red", bet_mode_specifier="5")
    runtime_context.betting_state["account_balance"] = 100.0
    notifications = []
    snapshots = []

    update_balance_from_accounting_payload(
        json.dumps({"type": "balance_update", "balance_update": {"code": 200, "balance_type": 1, "value": 130.0}}),
        runtime_context=runtime_context,
        runtime_config=make_runtime_config(),
        format_ws_payload_func=lambda payload: payload,
        record_accounting_rejection_func=lambda *args, **kwargs: None,
        update_runtime_snapshot_func=lambda event_type, extra=None: snapshots.append((event_type, extra or {})),
        queue_telegram_notification_func=lambda *args, **kwargs: notifications.append((args, kwargs)),
    )

    assert runtime_context.betting_state["external_deposits_total"] == 30.0
    assert runtime_context.betting_state["session_balance"] == 30.0
    assert runtime_context.betting_state["reconciliation_phase"] == "external_deposit"
    assert snapshots[-1][1]["deposit_detected"] is True


def test_accounting_detects_external_withdrawal_on_active_balance_stream() -> None:
    runtime_context = RuntimeContext(bet_mode_outcome="red", bet_mode_specifier="5")
    runtime_context.betting_state = build_runtime_betting_state(strategy=None, bet_mode_outcome="red", bet_mode_specifier="5")
    runtime_context.betting_state["account_balance"] = 500.0
    runtime_context.betting_state["session_balance"] = 120.0
    snapshots = []

    update_balance_from_accounting_payload(
        json.dumps({"type": "balance_update", "balance_update": {"code": 200, "balance_type": 1, "value": 420.0}}),
        runtime_context=runtime_context,
        runtime_config=make_runtime_config(),
        format_ws_payload_func=lambda payload: payload,
        record_accounting_rejection_func=lambda *args, **kwargs: None,
        update_runtime_snapshot_func=lambda event_type, extra=None: snapshots.append((event_type, extra or {})),
        queue_telegram_notification_func=lambda *args, **kwargs: None,
    )

    assert runtime_context.betting_state["external_withdrawals_total"] == 80.0
    assert runtime_context.betting_state["session_balance"] == 40.0
    assert runtime_context.betting_state["reconciliation_phase"] == "external_withdrawal"
    assert snapshots[-1][1]["withdrawal_detected"] is True
