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
        browser=BrowserConfig(
            session_dir=Path("profile"),
            strategies_dir=Path("strategies"),
            target_ws_url="target",
            accounting_ws_url="accounting",
            bet_api_url="bet",
            headless=False,
            block_video_stream=False,
            block_images=False,
            block_fonts=False,
            disable_gpu=False,
            renderer_process_limit=0,
        ),
        database=DatabaseConfig("postgres", "postgres", "localhost", "5432", "buybaybye"),
        betting=BettingConfig(
            requested_enabled=True,
            enabled=True,
            check_required_bank_on_first_step=False,
            configured_targets=tuple(),
            configured_targets_raw="",
            configured_targets_error=None,
            default_outcome="red",
            default_specifier="5",
            base_bet=10.0,
            stop_at_balance=0.0,
            stop_at_balance_resume_check_seconds=5.0,
            max_stake_percent_of_bank=100.0,
            strategy_name="balanced",
            bet_delay_min=0.8,
            bet_delay_max=1.5,
            debug_enabled=False,
            post_log_enabled=False,
            combine_slots_in_single_post=False,
        ),
        dynamic_betting=DynamicBettingConfig(
            enabled=True,
            window_size=40,
            recalc_interval=5,
            update_output_enabled=True,
            unchanged_analysis_output_enabled=True,
            use_average_value_selection=True,
            include_double_selection=True,
            filter_by_player=False,
            filter_by_side=False,
            random_fallback_enabled=True,
            random_fallback_loss_streak=15,
        ),
        accounting=AccountingConfig(
            balance_stale_seconds=15.0,
            recovery_reload_on_stale_balance=True,
            initial_balance_timeout_seconds=25.0,
            recovery_reload_seconds=30.0,
            recovery_cooldown_seconds=300.0,
            idle_reconnect_seconds=300.0,
            page_crash_restart_threshold=3,
            monitor_poll_seconds=1.0,
            debug_rejected_messages=False,
        ),
        telegram=TelegramConfig(False, "", "", 5.0, 60.0, True, True, True, True, True),
        logging=LoggingConfig(False, True, False, False),
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
    assert runtime_context.betting_state["session_balance"] == 0.0
    assert runtime_context.betting_state["account_balance"] == 130.0
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
    assert runtime_context.betting_state["session_balance"] == 120.0
    assert runtime_context.betting_state["account_balance"] == 420.0
    assert runtime_context.betting_state["reconciliation_phase"] == "external_withdrawal"
    assert snapshots[-1][1]["withdrawal_detected"] is True
