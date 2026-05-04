from __future__ import annotations

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
from buybaybye.modules.browser_ws import wire_ws_logging


class FakeWebSocket:
    def __init__(self, url: str):
        self.url = url
        self._handlers: dict[str, object] = {}

    def on(self, event_name: str, handler) -> None:
        self._handlers[event_name] = handler

    def receive(self, payload: object) -> None:
        self._handlers["framereceived"](payload)

    def close(self) -> None:
        self._handlers["close"]()


class FakePage:
    def __init__(self):
        self._handlers: dict[str, object] = {}

    def on(self, event_name: str, handler) -> None:
        self._handlers[event_name] = handler

    def emit_websocket(self, ws: FakeWebSocket) -> None:
        self._handlers["websocket"](ws)


def make_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        role=RuntimeRoleConfig("bettor", True, True, False),
        browser=BrowserConfig(
            session_dir="profile",
            strategies_dir="strategies",
            target_ws_url="wss://target",
            accounting_ws_url="wss://accounting",
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
        logging=LoggingConfig(False, False, False, False),
        colors=ColorConfig(True, "", "", "", "", "", "", ""),
    )


def test_browser_ws_ignores_frames_from_stale_accounting_socket() -> None:
    runtime_context = RuntimeContext(bet_mode_outcome="red", bet_mode_specifier="5")
    runtime_context.betting_state = build_runtime_betting_state(strategy=None, bet_mode_outcome="red", bet_mode_specifier="5")
    page = FakePage()
    received_payloads: list[object] = []
    snapshot_events: list[str] = []

    wire_ws_logging(
        page,
        runtime_context=runtime_context,
        runtime_config=make_runtime_config(),
        update_runtime_snapshot_func=lambda event_type, extra=None: snapshot_events.append(event_type),
        format_ws_payload_func=lambda payload: str(payload),
        update_balance_from_accounting_payload_func=lambda payload: received_payloads.append(payload),
        save_target_ws_message_func=lambda payload: None,
        process_betting_round_func=lambda page, payload: None,
        schedule_background_task_func=lambda coroutine, description: None,
    )

    stale_ws = FakeWebSocket("wss://accounting/socket-a")
    active_ws = FakeWebSocket("wss://accounting/socket-b")

    page.emit_websocket(stale_ws)
    page.emit_websocket(active_ws)

    stale_ws.receive("stale-payload")
    active_ws.receive("active-payload")
    stale_ws.close()
    active_ws.close()

    assert received_payloads == ["active-payload"]
    assert snapshot_events.count("accounting_ws_open") == 2
    assert snapshot_events.count("accounting_ws_close") == 1
    assert runtime_context.betting_state["accounting_ws_connected"] is False