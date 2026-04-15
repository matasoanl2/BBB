"""Вспомогательные функции для баланса accounting websocket и recovery-логики."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from buybaybye.runtime_context import RuntimeContext
from buybaybye.runtime_config import RuntimeConfig


def get_accounting_age_seconds(*, runtime_context: RuntimeContext, reference_key: str) -> float | None:
    """Вернуть возраст timestamp-поля из betting_state в секундах."""

    raw_value = runtime_context.betting_state.get(reference_key)
    if not raw_value:
        return None
    try:
        timestamp = datetime.fromisoformat(raw_value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())


def is_account_balance_stale(*, runtime_context: RuntimeContext, runtime_config: RuntimeConfig, get_accounting_age_seconds_func) -> bool:
    """Определить, считается ли текущий accounting balance устаревшим."""

    betting_state = runtime_context.betting_state
    if not betting_state:
        return False
    if betting_state.get("account_balance") is None:
        return False
    if betting_state.get("accounting_ws_connected") is False and betting_state.get("last_accounting_ws_closed_at"):
        return True

    pending_drop = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0)
    if pending_drop <= 0:
        return False

    age_seconds = get_accounting_age_seconds_func("account_balance_updated_at")
    if age_seconds is None:
        return True
    return age_seconds >= runtime_config.accounting.balance_stale_seconds


def record_accounting_rejection(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    reason: str,
    payload_preview: str | None,
) -> None:
    """Сохранить причину отклонения accounting-сообщения и при необходимости вывести ее в лог."""

    runtime_context.betting_state["last_accounting_rejection_reason"] = reason
    if runtime_config.accounting.debug_rejected_messages or runtime_config.betting.debug_enabled:
        preview = f" | payload={payload_preview[:220]}" if payload_preview else ""
        print(f"[ACCOUNTING][SKIP] {reason}{preview}", flush=True)


def get_balance_for_log(*, runtime_context: RuntimeContext, is_account_balance_stale_func) -> str:
    """Вернуть строку баланса для логов с маркером устаревшего real balance."""

    betting_state = runtime_context.betting_state
    account_balance = betting_state.get("account_balance")
    if account_balance is not None:
        suffix = " !" if is_account_balance_stale_func() else ""
        return f"{account_balance:.0f}р{suffix}"
    return f"{betting_state.get('session_balance', 0):.0f}р"


def update_balance_from_accounting_payload(
    payload: object,
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    format_ws_payload_func,
    record_accounting_rejection_func,
    update_runtime_snapshot_func,
    queue_telegram_notification_func,
) -> None:
    """Обработать accounting payload и синхронизировать real balance с betting state."""

    betting_state = runtime_context.betting_state
    try:
        payload_text = format_ws_payload_func(payload)
        data = json.loads(payload_text)
    except Exception:
        record_accounting_rejection_func("payload is not valid JSON")
        return

    betting_state["last_accounting_ws_message_at"] = datetime.now(timezone.utc).isoformat()

    if not isinstance(data, dict):
        record_accounting_rejection_func("payload root is not an object", payload_text)
        return
    if data.get("type") != "balance_update":
        record_accounting_rejection_func(f"ignored message type={data.get('type')}", payload_text)
        return

    balance_update = data.get("balance_update")
    if not isinstance(balance_update, dict):
        record_accounting_rejection_func("balance_update field is missing or not an object", payload_text)
        return
    if balance_update.get("code") != 200:
        record_accounting_rejection_func(f"balance_update.code={balance_update.get('code')}", payload_text)
        return

    balance_type = balance_update.get("balance_type")
    try:
        normalized_balance_type = int(balance_type)
    except (TypeError, ValueError):
        record_accounting_rejection_func(f"invalid balance_type={balance_type}", payload_text)
        return

    if normalized_balance_type != 1:
        record_accounting_rejection_func(f"ignored balance_type={normalized_balance_type}", payload_text)
        return

    value = balance_update.get("value")
    if not isinstance(value, (int, float)):
        record_accounting_rejection_func(f"non-numeric balance value={value}", payload_text)
        return

    new_balance = float(value)
    previous_balance = betting_state.get("account_balance")
    pending_expected_bet_drop = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0)
    withdrawal_detected = False

    if isinstance(previous_balance, (int, float)) and new_balance < previous_balance:
        actual_drop = float(previous_balance) - new_balance
        covered_by_bet = min(actual_drop, pending_expected_bet_drop)
        pending_expected_bet_drop = max(0.0, pending_expected_bet_drop - covered_by_bet)
        withdrawal_amount = actual_drop - covered_by_bet

        if withdrawal_amount > 0.009:
            withdrawal_detected = True
            betting_state["session_balance"] -= withdrawal_amount
            betting_state["external_withdrawals_total"] = betting_state.get("external_withdrawals_total", 0.0) + withdrawal_amount
            print(
                f"[ACCOUNTING] Обнаружен вывод: -{withdrawal_amount:.0f}р, session_balance скорректирован до {betting_state['session_balance']:.0f}р",
                flush=True,
            )
            queue_telegram_notification_func(
                "[BuyBayBye] Обнаружен вывод средств",
                (
                    "Accounting balance уменьшился вне ожидаемого списания ставки.\n"
                    f"Сумма вывода: {withdrawal_amount:.0f}р\n"
                    f"Новый real balance: {new_balance:.0f}р\n"
                    f"Session balance: {betting_state['session_balance']:.0f}р"
                ),
                dedup_key="withdrawal_detected",
                enabled=runtime_config.telegram.notify_withdrawals,
            )

    betting_state["pending_expected_bet_drop"] = pending_expected_bet_drop
    betting_state["account_balance"] = new_balance
    betting_state["account_balance_type"] = normalized_balance_type
    betting_state["account_balance_updated_at"] = datetime.now(timezone.utc).isoformat()
    betting_state["last_accounting_rejection_reason"] = None
    update_runtime_snapshot_func(
        "balance_update",
        {
            "account_balance": new_balance,
            "withdrawal_detected": withdrawal_detected,
        },
    )

    if runtime_config.betting.debug_enabled:
        btype = betting_state.get("account_balance_type")
        print(f"[ACCOUNTING] Баланс обновлен: {new_balance} (balance_type={btype})", flush=True)


async def reload_page_for_accounting_recovery(
    page,
    reason: str,
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    get_balance_for_log_func,
    queue_telegram_notification_func,
    update_runtime_snapshot_func,
) -> bool:
    """Перезагрузить страницу для восстановления accounting websocket и обновления real balance."""

    betting_state = runtime_context.betting_state
    if page.is_closed():
        return False

    print(f"[ACCOUNTING] Баланс устарел, перезагружаем страницу для восстановления канала ({reason})...", flush=True)
    queue_telegram_notification_func(
        "[BuyBayBye] Проблема с accounting balance",
        f"Запущено восстановление accounting_ws.\nПричина: {reason}\nПоследний real balance: {get_balance_for_log_func()}",
        dedup_key=f"accounting_recovery_start:{reason}",
        enabled=runtime_config.telegram.notify_accounting_issues,
    )
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        print(f"[ACCOUNTING] Ошибка перезагрузки страницы при восстановлении accounting_ws: {exc}", flush=True)
        queue_telegram_notification_func(
            "[BuyBayBye] Ошибка восстановления accounting_ws",
            f"Page reload завершился ошибкой.\nПричина: {reason}\nОшибка: {exc}",
            dedup_key=f"accounting_recovery_error:{reason}",
            enabled=runtime_config.telegram.notify_accounting_issues,
        )
        return False

    betting_state["last_accounting_recovery_at"] = datetime.now(timezone.utc).isoformat()
    betting_state["accounting_recovery_attempts"] = int(betting_state.get("accounting_recovery_attempts", 0) or 0) + 1
    update_runtime_snapshot_func(
        "accounting_recovery",
        {
            "accounting_recovery_reason": reason,
            "accounting_recovery_attempts": betting_state.get("accounting_recovery_attempts"),
        },
    )
    queue_telegram_notification_func(
        "[BuyBayBye] accounting_ws восстановлен",
        f"Перезагрузка страницы завершилась успешно.\nПричина: {reason}\nТекущий real balance: {get_balance_for_log_func()}",
        dedup_key=f"accounting_recovery_success:{reason}",
        enabled=runtime_config.telegram.notify_accounting_issues,
    )
    return True


async def monitor_accounting_ws_health(
    page,
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    get_accounting_age_seconds_func,
    is_account_balance_stale_func,
    reload_page_for_accounting_recovery_func,
) -> None:
    """Следить за свежестью accounting_ws и запускать recovery через reload страницы.

    Цикл считает баланс устаревшим только тогда, когда после размещенной ставки
    остается неподтвержденное ожидаемое списание. Частота проверки задается
    через ``runtime_config.accounting.monitor_poll_seconds``.
    """
    betting_state = runtime_context.betting_state
    while True:
        await asyncio.sleep(runtime_config.accounting.monitor_poll_seconds)

        if page.is_closed():
            return

        last_recovery_age = get_accounting_age_seconds_func("last_accounting_recovery_at")
        if last_recovery_age is not None and last_recovery_age < runtime_config.accounting.recovery_cooldown_seconds:
            continue

        ws_age = get_accounting_age_seconds_func("last_accounting_ws_message_at")
        balance_age = get_accounting_age_seconds_func("account_balance_updated_at")

        reason = None
        if betting_state.get("accounting_ws_connected") is False and betting_state.get("last_accounting_ws_closed_at"):
            reason = "accounting_ws closed"
        elif is_account_balance_stale_func() and balance_age is not None and balance_age >= runtime_config.accounting.recovery_reload_seconds:
            reason = f"balance_update stale for {balance_age:.0f}s"
        elif (
            betting_state.get("account_balance") is not None
            and ws_age is not None
            and ws_age >= runtime_config.accounting.recovery_reload_seconds
            and float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0) > 0
        ):
            reason = f"no accounting messages for {ws_age:.0f}s"

        if reason:
            await reload_page_for_accounting_recovery_func(page, reason)