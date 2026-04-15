"""Вспомогательные функции для сборки и сохранения runtime snapshot payloads."""

from __future__ import annotations

from datetime import datetime, timezone

from psycopg2.extras import Json

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import RuntimeConfig


def build_runtime_snapshot(
    *,
    event_type: str = "heartbeat",
    extra: dict | None = None,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    is_account_balance_stale_func,
) -> dict:
    """Собрать единый snapshot текущего runtime state для live-мониторинга."""

    betting_state = runtime_context.betting_state
    current_strategy = runtime_context.current_strategy
    strategy_name_value = runtime_config.betting.strategy_name if runtime_config.betting.enabled else None
    strategy_display_name = current_strategy.get("name") if current_strategy else None
    max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else None

    snapshot = {
        "event_type": event_type,
        "bet_mode_enabled": runtime_config.betting.enabled,
        "dynamic_bet_mode": runtime_config.dynamic_betting.enabled,
        "strategy_name": strategy_name_value,
        "strategy_display_name": strategy_display_name,
        "current_step": betting_state.get("current_step") if betting_state else None,
        "max_steps": max_steps,
        "consecutive_losses": betting_state.get("consecutive_losses") if betting_state else 0,
        "session_balance": betting_state.get("session_balance") if betting_state else 0.0,
        "account_balance": betting_state.get("account_balance") if betting_state else None,
        "account_balance_updated_at": betting_state.get("account_balance_updated_at") if betting_state else None,
        "last_accounting_ws_message_at": betting_state.get("last_accounting_ws_message_at") if betting_state else None,
        "last_accounting_ws_opened_at": betting_state.get("last_accounting_ws_opened_at") if betting_state else None,
        "last_accounting_ws_closed_at": betting_state.get("last_accounting_ws_closed_at") if betting_state else None,
        "accounting_ws_connected": betting_state.get("accounting_ws_connected") if betting_state else False,
        "account_balance_is_stale": is_account_balance_stale_func() if betting_state else False,
        "last_accounting_rejection_reason": betting_state.get("last_accounting_rejection_reason") if betting_state else None,
        "last_accounting_recovery_at": betting_state.get("last_accounting_recovery_at") if betting_state else None,
        "accounting_recovery_attempts": betting_state.get("accounting_recovery_attempts") if betting_state else 0,
        "total_profit": betting_state.get("total_profit") if betting_state else 0.0,
        "total_bet_amount": betting_state.get("total_bet_amount") if betting_state else 0.0,
        "total_bets_placed": betting_state.get("total_bets_placed") if betting_state else 0,
        "pending_expected_bet_drop": betting_state.get("pending_expected_bet_drop") if betting_state else 0.0,
        "external_deposits_total": betting_state.get("external_deposits_total") if betting_state else 0.0,
        "external_withdrawals_total": betting_state.get("external_withdrawals_total") if betting_state else 0.0,
        "current_outcome": runtime_context.bet_mode_outcome if runtime_config.betting.enabled else None,
        "current_specifier": runtime_context.bet_mode_specifier if runtime_config.betting.enabled else None,
        "dynamic_outcome": betting_state.get("dynamic_outcome") if betting_state else None,
        "dynamic_specifier": betting_state.get("dynamic_specifier") if betting_state else None,
        "dynamic_use_average_value_selection": runtime_config.dynamic_betting.use_average_value_selection,
        "dynamic_include_double_selection": runtime_config.dynamic_betting.include_double_selection,
        "dynamic_filter_by_player": runtime_config.dynamic_betting.filter_by_player,
        "dynamic_filter_by_side": runtime_config.dynamic_betting.filter_by_side,
        "last_bet_amount": betting_state.get("last_bet_amount") if betting_state else 0.0,
        "last_set_amount": betting_state.get("last_set_amount") if betting_state else 0.0,
        "last_set_status": betting_state.get("last_set_status") if betting_state else None,
        "last_set_error": betting_state.get("last_set_error") if betting_state else None,
        "last_round_result": betting_state.get("last_round_result") if betting_state else None,
        "last_round_game_id": betting_state.get("last_round_game_id") if betting_state else None,
        "last_round_status": betting_state.get("last_round_status") if betting_state else None,
        "last_round_timestamp": betting_state.get("last_round_timestamp") if betting_state else None,
        "last_round_player_name": betting_state.get("last_round_player_name") if betting_state else None,
        "last_round_position": betting_state.get("last_round_position") if betting_state else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        snapshot.update(extra)
    return snapshot


def update_runtime_snapshot(*, get_db_connection_func, snapshot: dict, event_type: str) -> None:
    """Сохранить live snapshot и отдельное runtime event в базе данных."""

    try:
        conn = get_db_connection_func()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO runtime_snapshot (snapshot_key, updated_at, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (snapshot_key)
            DO UPDATE SET updated_at = EXCLUDED.updated_at, payload = EXCLUDED.payload
            """,
            ("live", datetime.now(timezone.utc), Json(snapshot)),
        )
        cursor.execute(
            """
            INSERT INTO runtime_events (timestamp, event_type, payload)
            VALUES (%s, %s, %s)
            """,
            (datetime.now(timezone.utc), event_type, Json(snapshot)),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        print(f"[DB ERROR] Ошибка обновления runtime_snapshot: {exc}", flush=True)