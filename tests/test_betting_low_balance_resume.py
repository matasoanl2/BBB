import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from buybaybye.core.runtime_config import (
    AccountingConfig,
    BetTarget,
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
from buybaybye.core.runtime_context import create_runtime_context
from buybaybye.core.runtime_state import build_runtime_betting_state
from buybaybye.modules.accounting import update_balance_from_accounting_payload
from buybaybye.modules.betting import _run_set_precheck_for_slot, process_betting_round


def _make_runtime_config(*, combine_slots_in_single_post: bool = False) -> RuntimeConfig:
    configured_targets = (BetTarget("red", "1"),)
    configured_targets_2 = (BetTarget("yellow", "2"),)
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
            configured_targets=configured_targets,
            configured_targets_raw="R1",
            configured_targets_error=None,
            default_outcome="red",
            default_specifier="1",
            base_bet=10.0,
            stop_at_balance=0.0,
            stop_at_balance_resume_check_seconds=5.0,
            max_stake_percent_of_bank=100.0,
            strategy_name="balanced",
            bet_delay_min=0.0,
            bet_delay_max=0.0,
            debug_enabled=False,
            post_log_enabled=False,
            combine_slots_in_single_post=combine_slots_in_single_post,
            strategy_name_2="balanced",
            base_bet_2=10.0,
            configured_targets_2=configured_targets_2,
            configured_targets_raw_2="Y2",
            configured_targets_error_2=None,
            secondary_enabled=True,
        ),
        dynamic_betting=DynamicBettingConfig(
            enabled=False,
            window_size=40,
            recalc_interval=5,
            update_output_enabled=True,
            unchanged_analysis_output_enabled=True,
            use_average_value_selection=True,
            include_double_selection=True,
            filter_by_player=False,
            filter_by_side=False,
            random_fallback_enabled=False,
            random_fallback_loss_streak=15,
            enabled_2=False,
            multi_target_enabled=False,
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


def _make_runtime_context():
    runtime_context = create_runtime_context(
        configured_bet_targets=(BetTarget("red", "1"),),
        bet_mode_outcome="red",
        bet_mode_specifier="1",
    )
    runtime_context.current_strategy = {"name": "balanced", "coefficients": [1], "payout_coefficient": 5.7}
    runtime_context.current_strategy_2 = {"name": "balanced", "coefficients": [1], "payout_coefficient": 5.7}
    runtime_context.betting_state = build_runtime_betting_state(
        strategy=runtime_context.current_strategy,
        bet_mode_outcome="red",
        bet_mode_specifier="1",
    )
    runtime_context.betting_state_2 = build_runtime_betting_state(
        strategy=runtime_context.current_strategy_2,
        bet_mode_outcome="yellow",
        bet_mode_specifier="2",
    )
    runtime_context.configured_bet_targets_2 = (BetTarget("yellow", "2"),)
    runtime_context.set_current_bet_target_2("yellow", "2")
    return runtime_context


def _format_bet_log_stub(**kwargs) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple) -> None:
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return None

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        return None


def _make_single_slot_runtime_context():
    runtime_context = create_runtime_context(
        configured_bet_targets=(BetTarget("red", "1"),),
        bet_mode_outcome="red",
        bet_mode_specifier="1",
    )
    runtime_context.current_strategy = {"name": "balanced", "coefficients": [1, 2, 3], "payout_coefficient": 5.7}
    runtime_context.betting_state = build_runtime_betting_state(
        strategy=runtime_context.current_strategy,
        bet_mode_outcome="red",
        bet_mode_specifier="1",
    )
    return runtime_context


def test_precheck_keeps_api_insufficient_balance_pause_until_fresh_accounting_update() -> None:
    runtime_config = _make_runtime_config()
    betting_state = build_runtime_betting_state(strategy={"coefficients": [1]}, bet_mode_outcome="red", bet_mode_specifier="1")
    fail_at = datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc)
    stale_update_at = fail_at - timedelta(seconds=2)

    betting_state["account_balance"] = 24.0
    betting_state["account_balance_updated_at"] = stale_update_at.isoformat()
    betting_state["low_balance_pause_active"] = True
    betting_state["low_balance_pause_reason"] = "api_insufficient_balance"
    betting_state["low_balance_api_fail_at"] = fail_at.isoformat()
    betting_state["current_step"] = 3
    betting_state["consecutive_losses"] = 2

    ok, effective_targets, effective_amount = _run_set_precheck_for_slot(
        betting_state=betting_state,
        current_strategy={"coefficients": [1]},
        amount=10.0,
        bet_targets=(BetTarget("red", "1"), BetTarget("yellow", "2")),
        requested_targets=(BetTarget("red", "1"), BetTarget("yellow", "2")),
        slot_label="1",
        step_for_history=3,
        max_steps=5,
        next_round_display="001",
        runtime_config=runtime_config,
        calculate_roi_func=lambda: 0.0,
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_bet_log_func=_format_bet_log_stub,
        get_balance_for_log_func=lambda: "24р",
        update_runtime_snapshot_func=lambda *args, **kwargs: None,
        required_bank_base_bet=10.0,
        resume_base_bet=10.0,
    )

    assert ok is False
    assert effective_targets == ()
    assert effective_amount == 10.0
    assert betting_state["low_balance_pause_active"] is True
    assert betting_state["current_step"] == 3
    assert betting_state["consecutive_losses"] == 2

    betting_state["account_balance"] = 14.0
    betting_state["account_balance_updated_at"] = (fail_at + timedelta(seconds=1)).isoformat()

    ok, effective_targets, effective_amount = _run_set_precheck_for_slot(
        betting_state=betting_state,
        current_strategy={"coefficients": [1]},
        amount=10.0,
        bet_targets=(BetTarget("red", "1"), BetTarget("yellow", "2")),
        requested_targets=(BetTarget("red", "1"), BetTarget("yellow", "2")),
        slot_label="1",
        step_for_history=3,
        max_steps=5,
        next_round_display="001",
        runtime_config=runtime_config,
        calculate_roi_func=lambda: 0.0,
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_bet_log_func=_format_bet_log_stub,
        get_balance_for_log_func=lambda: "14р",
        update_runtime_snapshot_func=lambda *args, **kwargs: None,
        required_bank_base_bet=10.0,
        resume_base_bet=10.0,
    )

    assert ok is True
    assert effective_amount == 10.0
    assert [target.token for target in effective_targets] == ["R1"]
    assert betting_state["low_balance_pause_active"] is False
    assert betting_state["current_step"] == 0
    assert betting_state["consecutive_losses"] == 0


def test_process_round_waits_for_fresh_accounting_update_then_keeps_only_one_slot() -> None:
    runtime_config = _make_runtime_config(combine_slots_in_single_post=True)
    runtime_context = _make_runtime_context()
    fail_at = datetime.now(timezone.utc)
    stale_update_at = fail_at - timedelta(seconds=1)

    for state in (runtime_context.betting_state, runtime_context.betting_state_2):
        state["account_balance"] = 24.0
        state["account_balance_updated_at"] = stale_update_at.isoformat()
        state["low_balance_pause_active"] = True
        state["low_balance_pause_reason"] = "api_insufficient_balance"
        state["low_balance_api_fail_at"] = fail_at.isoformat()

    slot1_calls: list[tuple[list[str], float]] = []
    slot2_calls: list[tuple[list[str], float]] = []
    combined_calls: list[tuple[list[str], float, list[str], float]] = []

    async def _place_bets_stub(page, targets, amount):
        slot1_calls.append(([target.token for target in targets], amount))
        return True

    async def _place_bets_2_stub(page, targets, amount):
        slot2_calls.append(([target.token for target in targets], amount))
        return True

    async def _place_bets_combined_stub(page, *, slot1_targets, slot1_amount, slot2_targets, slot2_amount):
        combined_calls.append(
            ([target.token for target in slot1_targets], slot1_amount, [target.token for target in slot2_targets], slot2_amount)
        )
        return True

    async def _run_once(payload: str) -> None:
        await process_betting_round(
            page=None,
            payload=payload,
            runtime_context=runtime_context,
            runtime_config=runtime_config,
            format_ws_payload_func=lambda value: value,
            get_db_connection_func=lambda: None,
            format_round_result_pretty_func=lambda dice: "R1,Y2",
            format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier or 'D'}",
            format_bet_log_func=_format_bet_log_stub,
            get_balance_for_log_func=lambda: "14р",
            calculate_roi_func=lambda: 0.0,
            update_runtime_snapshot_func=lambda *args, **kwargs: None,
            print_session_stats_func=lambda *args, **kwargs: None,
            print_dice_stats_20_func=lambda *args, **kwargs: None,
            update_dynamic_bet_func=lambda *args, **kwargs: None,
            update_dynamic_bet_2_func=lambda *args, **kwargs: None,
            generate_random_bet_func=lambda: ("red", "1"),
            calculate_bet_amount_func=lambda: 10.0,
            place_bet_func=lambda *args, **kwargs: None,
            place_bets_func=_place_bets_stub,
            place_bets_combined_slots_func=_place_bets_combined_stub,
            calculate_bet_amount_2_func=lambda: 10.0,
            place_bets_2_func=_place_bets_2_stub,
        )

    first_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-1",
            "results": {
                "dice": [{"color": "red", "value": 1}, {"color": "yellow", "value": 2}],
                "player": {"name": "tester", "position": "left"},
            },
        }
    )
    asyncio.run(_run_once(first_payload))

    assert slot1_calls == []
    assert slot2_calls == []
    assert combined_calls == []

    update_balance_from_accounting_payload(
        json.dumps({"type": "balance_update", "balance_update": {"code": 200, "balance_type": 1, "value": 14.0}}),
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        format_ws_payload_func=lambda payload: payload,
        record_accounting_rejection_func=lambda *args, **kwargs: None,
        update_runtime_snapshot_func=lambda *args, **kwargs: None,
        queue_telegram_notification_func=lambda *args, **kwargs: None,
    )

    second_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-2",
            "results": {
                "dice": [{"color": "red", "value": 2}, {"color": "yellow", "value": 3}],
                "player": {"name": "tester", "position": "right"},
            },
        }
    )
    asyncio.run(_run_once(second_payload))

    assert slot1_calls == [(["R1"], 10.0)]
    assert slot2_calls == []
    assert combined_calls == []
    assert runtime_context.betting_state["low_balance_pause_active"] is False
    assert runtime_context.betting_state_2["low_balance_pause_active"] is False


def test_false_win_waits_for_accounting_then_repeats_same_step() -> None:
    runtime_config = _make_runtime_config()
    runtime_context = _make_single_slot_runtime_context()
    runtime_context.betting_state["current_step"] = 2
    runtime_context.betting_state["consecutive_losses"] = 2
    runtime_context.betting_state["account_balance"] = 1450.0
    runtime_context.betting_state["pending_bets"] = [
        {
            "history_id": 101,
            "outcome": "red",
            "specifier": "1",
            "amount": 10.0,
            "bet_step": 2,
            "token": "R1",
            "round_number": 1,
        }
    ]

    placed_calls: list[tuple[list[str], float]] = []
    db_connections: list[_FakeConnection] = []

    def _get_db_connection():
        connection = _FakeConnection()
        db_connections.append(connection)
        return connection

    async def _place_bets_stub(page, targets, amount):
        placed_calls.append(([target.token for target in targets], amount))
        return True

    async def _run_round(payload: str) -> None:
        await process_betting_round(
            page=None,
            payload=payload,
            runtime_context=runtime_context,
            runtime_config=runtime_config,
            format_ws_payload_func=lambda value: value,
            get_db_connection_func=_get_db_connection,
            format_round_result_pretty_func=lambda dice: "R1,Y6",
            format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier or 'D'}",
            format_bet_log_func=_format_bet_log_stub,
            get_balance_for_log_func=lambda: "1450р",
            calculate_roi_func=lambda: 0.0,
            update_runtime_snapshot_func=lambda *args, **kwargs: None,
            print_session_stats_func=lambda *args, **kwargs: None,
            print_dice_stats_20_func=lambda *args, **kwargs: None,
            update_dynamic_bet_func=lambda *args, **kwargs: None,
            generate_random_bet_func=lambda: ("red", "1"),
            calculate_bet_amount_func=lambda: [10.0, 20.0, 30.0, 40.0][runtime_context.betting_state["current_step"]],
            place_bet_func=lambda *args, **kwargs: None,
            place_bets_func=_place_bets_stub,
        )

    winning_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-false-win-1",
            "results": {
                "dice": [{"color": "red", "value": 1}, {"color": "yellow", "value": 6}],
                "player": {"name": "tester", "position": "left"},
            },
        }
    )
    asyncio.run(_run_round(winning_payload))

    assert placed_calls == []
    assert runtime_context.betting_state["pending_win_confirmation"] is not None
    assert runtime_context.betting_state["current_step"] == 2
    assert runtime_context.betting_state["session_balance"] == 0.0
    assert runtime_context.betting_state["total_profit"] == 0.0
    assert runtime_context.betting_state["pending_expected_settlement_credit"] == 57.0
    assert db_connections[0].cursor_instance.executed[-1][1][0] == "win_pending_confirmation"

    update_balance_from_accounting_payload(
        json.dumps({"type": "balance_update", "balance_update": {"code": 200, "balance_type": 1, "value": 1450.0}}),
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        format_ws_payload_func=lambda payload: payload,
        record_accounting_rejection_func=lambda *args, **kwargs: None,
        update_runtime_snapshot_func=lambda *args, **kwargs: None,
        queue_telegram_notification_func=lambda *args, **kwargs: None,
    )

    followup_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-false-win-2",
            "results": {
                "dice": [{"color": "yellow", "value": 2}, {"color": "red", "value": 6}],
                "player": {"name": "tester", "position": "right"},
            },
        }
    )
    asyncio.run(_run_round(followup_payload))

    assert placed_calls == [(["R1"], 10.0)]
    assert runtime_context.betting_state["pending_win_confirmation"] is None
    assert runtime_context.betting_state["current_step"] == 0
    assert runtime_context.betting_state["session_balance"] == -10.0
    assert runtime_context.betting_state["total_profit"] == -10.0
    assert runtime_context.betting_state["pending_expected_settlement_credit"] == 0.0
    assert runtime_context.betting_state["last_set_status"] == "false_win"
    assert runtime_context.betting_state["pending_bets"] == []
    assert any(
        params[0] == "false_win"
        for connection in db_connections
        for _, params in connection.cursor_instance.executed
        if params
    )


def test_false_win_without_accounting_update_does_not_skip_next_round() -> None:
    runtime_config = _make_runtime_config()
    runtime_context = _make_single_slot_runtime_context()
    runtime_context.betting_state["current_step"] = 2
    runtime_context.betting_state["consecutive_losses"] = 2
    runtime_context.betting_state["account_balance"] = 1450.0
    runtime_context.betting_state["pending_bets"] = [
        {
            "history_id": 303,
            "outcome": "red",
            "specifier": "1",
            "amount": 10.0,
            "bet_step": 2,
            "token": "R1",
            "round_number": 1,
        }
    ]

    placed_calls: list[tuple[list[str], float]] = []
    db_connections: list[_FakeConnection] = []

    def _get_db_connection():
        connection = _FakeConnection()
        db_connections.append(connection)
        return connection

    async def _place_bets_stub(page, targets, amount):
        placed_calls.append(([target.token for target in targets], amount))
        return True

    async def _run_round(payload: str) -> None:
        await process_betting_round(
            page=None,
            payload=payload,
            runtime_context=runtime_context,
            runtime_config=runtime_config,
            format_ws_payload_func=lambda value: value,
            get_db_connection_func=_get_db_connection,
            format_round_result_pretty_func=lambda dice: "R1,Y6",
            format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier or 'D'}",
            format_bet_log_func=_format_bet_log_stub,
            get_balance_for_log_func=lambda: "1450р",
            calculate_roi_func=lambda: 0.0,
            update_runtime_snapshot_func=lambda *args, **kwargs: None,
            print_session_stats_func=lambda *args, **kwargs: None,
            print_dice_stats_20_func=lambda *args, **kwargs: None,
            update_dynamic_bet_func=lambda *args, **kwargs: None,
            generate_random_bet_func=lambda: ("red", "1"),
            calculate_bet_amount_func=lambda: [10.0, 20.0, 30.0, 40.0][runtime_context.betting_state["current_step"]],
            place_bet_func=lambda *args, **kwargs: None,
            place_bets_func=_place_bets_stub,
        )

    winning_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-false-win-no-accounting-1",
            "results": {
                "dice": [{"color": "red", "value": 1}, {"color": "yellow", "value": 6}],
                "player": {"name": "tester", "position": "left"},
            },
        }
    )
    asyncio.run(_run_round(winning_payload))

    assert placed_calls == []
    assert runtime_context.betting_state["pending_win_confirmation"] is not None
    assert runtime_context.betting_state["current_step"] == 2
    assert runtime_context.betting_state["pending_expected_settlement_credit"] == 57.0
    assert db_connections[0].cursor_instance.executed[-1][1][0] == "win_pending_confirmation"

    followup_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-false-win-no-accounting-2",
            "results": {
                "dice": [{"color": "yellow", "value": 2}, {"color": "red", "value": 6}],
                "player": {"name": "tester", "position": "right"},
            },
        }
    )
    asyncio.run(_run_round(followup_payload))

    assert placed_calls == [(["R1"], 10.0)]
    assert runtime_context.betting_state["pending_win_confirmation"] is None
    assert runtime_context.betting_state["current_step"] == 0
    assert runtime_context.betting_state["session_balance"] == -10.0
    assert runtime_context.betting_state["total_profit"] == -10.0
    assert runtime_context.betting_state["pending_expected_settlement_credit"] == 0.0
    assert runtime_context.betting_state["last_set_status"] == "false_win"
    assert runtime_context.betting_state["pending_bets"] == []
    assert any(
        params[0] == "false_win"
        for connection in db_connections
        for _, params in connection.cursor_instance.executed
        if params
    )


def test_confirmed_win_waits_for_accounting_then_resets_step() -> None:
    runtime_config = _make_runtime_config()
    runtime_context = _make_single_slot_runtime_context()
    runtime_context.betting_state["current_step"] = 2
    runtime_context.betting_state["consecutive_losses"] = 2
    runtime_context.betting_state["account_balance"] = 1450.0
    runtime_context.betting_state["pending_bets"] = [
        {
            "history_id": 202,
            "outcome": "red",
            "specifier": "1",
            "amount": 10.0,
            "bet_step": 2,
            "token": "R1",
            "round_number": 1,
        }
    ]

    placed_calls: list[tuple[list[str], float]] = []
    db_connections: list[_FakeConnection] = []

    def _get_db_connection():
        connection = _FakeConnection()
        db_connections.append(connection)
        return connection

    async def _place_bets_stub(page, targets, amount):
        placed_calls.append(([target.token for target in targets], amount))
        return True

    async def _run_round(payload: str, balance_text: str) -> None:
        await process_betting_round(
            page=None,
            payload=payload,
            runtime_context=runtime_context,
            runtime_config=runtime_config,
            format_ws_payload_func=lambda value: value,
            get_db_connection_func=_get_db_connection,
            format_round_result_pretty_func=lambda dice: "R1,Y6",
            format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier or 'D'}",
            format_bet_log_func=_format_bet_log_stub,
            get_balance_for_log_func=lambda: balance_text,
            calculate_roi_func=lambda: 0.0,
            update_runtime_snapshot_func=lambda *args, **kwargs: None,
            print_session_stats_func=lambda *args, **kwargs: None,
            print_dice_stats_20_func=lambda *args, **kwargs: None,
            update_dynamic_bet_func=lambda *args, **kwargs: None,
            generate_random_bet_func=lambda: ("red", "1"),
            calculate_bet_amount_func=lambda: [10.0, 20.0, 30.0][runtime_context.betting_state["current_step"]],
            place_bet_func=lambda *args, **kwargs: None,
            place_bets_func=_place_bets_stub,
        )

    winning_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-confirm-win-1",
            "results": {
                "dice": [{"color": "red", "value": 1}, {"color": "yellow", "value": 6}],
                "player": {"name": "tester", "position": "left"},
            },
        }
    )
    asyncio.run(_run_round(winning_payload, "1450р"))

    assert placed_calls == []
    assert runtime_context.betting_state["pending_win_confirmation"] is not None

    update_balance_from_accounting_payload(
        json.dumps({"type": "balance_update", "balance_update": {"code": 200, "balance_type": 1, "value": 1507.0}}),
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        format_ws_payload_func=lambda payload: payload,
        record_accounting_rejection_func=lambda *args, **kwargs: None,
        update_runtime_snapshot_func=lambda *args, **kwargs: None,
        queue_telegram_notification_func=lambda *args, **kwargs: None,
    )

    followup_payload = json.dumps(
        {
            "status": "rng_values",
            "game_id": "game-confirm-win-2",
            "results": {
                "dice": [{"color": "yellow", "value": 2}, {"color": "red", "value": 6}],
                "player": {"name": "tester", "position": "right"},
            },
        }
    )
    asyncio.run(_run_round(followup_payload, "1507р"))

    assert placed_calls == [(["R1"], 10.0)]
    assert runtime_context.betting_state["pending_win_confirmation"] is None
    assert runtime_context.betting_state["current_step"] == 0
    assert runtime_context.betting_state["consecutive_losses"] == 0
    assert runtime_context.betting_state["session_balance"] == 47.0
    assert runtime_context.betting_state["total_profit"] == 47.0
    assert runtime_context.betting_state["pending_expected_settlement_credit"] == 0.0
    assert runtime_context.betting_state["last_set_status"] == "win"
    assert db_connections[-1].cursor_instance.executed[-1][1][0] == "win"