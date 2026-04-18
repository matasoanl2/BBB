"""Привязка browser websocket к target- и accounting-каналам."""

from __future__ import annotations

import json
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
    schedule_background_task_func,
) -> None:
    """Подключить обработчики websocket для target- и accounting-каналов страницы."""

    betting_state = runtime_context.betting_state
    browser_config = runtime_config.browser
    ws_log_enabled = runtime_config.logging.ws_log_enabled

    def _build_target_snapshot_extra(payload) -> dict | None:
        payload_text = format_ws_payload_func(payload)
        try:
            parsed_payload = json.loads(payload_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

        if not isinstance(parsed_payload, dict) or parsed_payload.get("status") != "rng_values":
            return None

        results = parsed_payload.get("results")
        if not isinstance(results, dict):
            return None

        player_info = results.get("player") if isinstance(results.get("player"), dict) else {}
        return {
            "last_round_game_id": parsed_payload.get("game_id"),
            "last_round_status": parsed_payload.get("status"),
            "last_round_timestamp": datetime.now(timezone.utc).isoformat(),
            "last_round_player_name": player_info.get("name"),
            "last_round_position": player_info.get("position"),
        }

    def on_websocket(ws) -> None:
        """Обработать открытие нового websocket и привязать события фреймов."""

        is_target = ws.url.startswith(browser_config.target_ws_url)
        is_accounting = ws.url.startswith(browser_config.accounting_ws_url)
        accounting_ws_token = runtime_context.issue_accounting_ws_token() if is_accounting else None
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
                if not runtime_context.is_active_accounting_ws_token(accounting_ws_token):
                    return
                update_balance_from_accounting_payload_func(payload)

            if is_target:
                if runtime_config.role.writes_round_results:
                    save_target_ws_message_func(payload)
                    snapshot_extra = _build_target_snapshot_extra(payload)
                    if snapshot_extra is not None:
                        update_runtime_snapshot_func("collector_round_ingress", snapshot_extra)
                if runtime_config.betting.enabled:
                    async def _run_round_pipeline() -> None:
                        async with runtime_context.ensure_round_processing_lock():
                            await process_betting_round_func(page, payload)

                    schedule_background_task_func(
                        _run_round_pipeline(),
                        description="process betting round",
                    )

        def on_close(*_) -> None:
            """Отметить закрытие accounting websocket и обновить runtime snapshot."""

            if is_accounting:
                if not runtime_context.is_active_accounting_ws_token(accounting_ws_token):
                    return
                betting_state["accounting_ws_connected"] = False
                betting_state["last_accounting_ws_closed_at"] = datetime.now(timezone.utc).isoformat()
                update_runtime_snapshot_func("accounting_ws_close")
            if ws_log_enabled:
                print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)