"""Привязка browser websocket к target- и accounting-каналам."""

from __future__ import annotations

from datetime import datetime, timezone
import asyncio

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import RuntimeConfig


def wire_ws_logging(
    page,
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    update_runtime_snapshot_func,
    format_ws_payload_func,
    update_balance_from_accounting_payload_func,
    save_target_ws_message_func,
    process_betting_round_func,
) -> None:
    """Подключить обработчики websocket для target- и accounting-каналов страницы."""

    betting_state = runtime_context.betting_state
    browser_config = runtime_config.browser
    ws_log_enabled = runtime_config.logging.ws_log_enabled

    def on_websocket(ws) -> None:
        """Обработать открытие нового websocket и привязать события фреймов."""

        is_target = ws.url.startswith(browser_config.target_ws_url)
        is_accounting = ws.url.startswith(browser_config.accounting_ws_url)
        tag = "TARGET-WS" if is_target else "WS"
        if is_accounting:
            betting_state["accounting_ws_connected"] = True
            betting_state["last_accounting_ws_opened_at"] = datetime.now(timezone.utc).isoformat()
            update_runtime_snapshot_func("accounting_ws_open")
        if ws_log_enabled:
            print(f"[{tag} OPEN] {ws.url}", flush=True)

        def on_sent(payload) -> None:
            """Вывести исходящий websocket frame в лог при включенном tracing."""

            if ws_log_enabled:
                print(f"[{tag} >>] {format_ws_payload_func(payload)}", flush=True)

        def on_received(payload) -> None:
            """Обработать входящий websocket frame и передать его в нужный доменный pipeline."""

            if ws_log_enabled:
                print(f"[{tag} <<] {format_ws_payload_func(payload)}", flush=True)

            if is_accounting:
                update_balance_from_accounting_payload_func(payload)

            if is_target:
                if runtime_config.role.writes_round_results:
                    save_target_ws_message_func(payload)
                if runtime_config.betting.enabled:
                    asyncio.create_task(process_betting_round_func(page, payload))

        def on_close(*_) -> None:
            """Отметить закрытие accounting websocket и обновить runtime snapshot."""

            if is_accounting:
                betting_state["accounting_ws_connected"] = False
                betting_state["last_accounting_ws_closed_at"] = datetime.now(timezone.utc).isoformat()
                update_runtime_snapshot_func("accounting_ws_close")
            if ws_log_enabled:
                print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)