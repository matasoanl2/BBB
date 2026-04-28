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
        browser=BrowserConfig("profile", "strategies", "wss://target", "wss://accounting", "bet", False),
        database=DatabaseConfig("postgres", "postgres", "localhost", "5432", "buybaybye"),
        betting=BettingConfig(True, True, tuple(), "", None, "red", "5", 10.0, 0.0, "balanced", 0.8, 1.5, False),
        dynamic_betting=DynamicBettingConfig(True, 40, 5, True, True, True, False, False, True, 15),
        accounting=AccountingConfig(15.0, 25.0, 30.0, 300.0, 300.0, 3.0, False),
        telegram=TelegramConfig(False, "", "", 5.0, 60.0, True, True, True, True, True),
        logging=LoggingConfig(False, False),
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