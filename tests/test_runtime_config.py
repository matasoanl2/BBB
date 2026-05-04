from pathlib import Path

import pytest

from buybaybye.core.runtime_config import (
    AccountingConfig,
    BettingConfig,
    BrowserConfig,
    ColorConfig,
    DynamicBettingConfig,
    LoggingConfig,
    RuntimeConfig,
    RuntimeRoleConfig,
    TelegramConfig,
    load_runtime_config,
    validate_runtime_config,
)
from buybaybye.core.runtime_config import DatabaseConfig


def make_config() -> RuntimeConfig:
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


def test_validate_runtime_config_accepts_valid_values() -> None:
    validate_runtime_config(make_config())


def test_validate_runtime_config_rejects_negative_delay() -> None:
    config = make_config()
    config.betting.bet_delay_min = -1.0
    with pytest.raises(ValueError):
        validate_runtime_config(config)


def test_validate_runtime_config_rejects_zero_recalc_interval() -> None:
    config = make_config()
    config.dynamic_betting.recalc_interval = 0
    with pytest.raises(ValueError):
        validate_runtime_config(config)


def test_load_runtime_config_random_fallback_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DYNAMIC_RANDOM_FALLBACK_ENABLED", raising=False)

    config = load_runtime_config(Path("."))

    assert config.dynamic_betting.random_fallback_enabled is False