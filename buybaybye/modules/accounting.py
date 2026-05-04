"""Вспомогательные функции для баланса accounting websocket и recovery-логики."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import RuntimeConfig


def _is_page_crashed_error(exc: Exception) -> bool:
    return "page crashed" in str(exc).lower()


async def _recover_from_crashed_page(*, page, runtime_context: RuntimeContext) -> tuple[bool, str]:
    """Попробовать восстановиться после page crash созданием новой страницы в том же context."""

    context = page.context
    target_url = page.url or "https://betboom.ru/game/nardsgame"

    replacement_page = await context.new_page()
    await replacement_page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
    runtime_context.active_page = replacement_page

    try:
        if not page.is_closed():
            await page.close()
    except Exception:
        # Старую упавшую страницу можно игнорировать, если закрыть ее не удалось.
        pass

    return True, target_url


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

    message_type = data.get("type")
    balance_update = data.get("balance_update")

    # Некоторые версии accounting_ws присылают стартовый баланс в type=subscribe
    # внутри subscribe.balances вместо отдельного type=balance_update.
    if not isinstance(balance_update, dict) and message_type == "subscribe":
        subscribe_payload = data.get("subscribe")
        if isinstance(subscribe_payload, dict):
            balances = subscribe_payload.get("balances")
            if isinstance(balances, list):
                selected_balance: dict | None = None
                for item in balances:
                    if not isinstance(item, dict):
                        continue
                    try:
                        if int(item.get("balance_type")) == 1:
                            selected_balance = item
                            break
                    except (TypeError, ValueError):
                        continue

                if selected_balance is not None:
                    balance_update = {
                        "code": subscribe_payload.get("code", 200),
                        "balance_type": selected_balance.get("balance_type"),
                        "value": selected_balance.get("value"),
                    }

    if not isinstance(balance_update, dict):
        record_accounting_rejection_func(f"ignored message type={message_type}", payload_text)
        return

    code_value = balance_update.get("code")
    try:
        normalized_code = int(code_value)
    except (TypeError, ValueError):
        record_accounting_rejection_func(f"invalid balance_update.code={code_value}", payload_text)
        return

    if normalized_code != 200:
        record_accounting_rejection_func(f"balance_update.code={normalized_code}", payload_text)
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
    try:
        new_balance = float(value)
    except (TypeError, ValueError):
        record_accounting_rejection_func(f"non-numeric balance value={value}", payload_text)
        return
    previous_balance = betting_state.get("account_balance")
    pending_expected_bet_drop = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0)
    pending_expected_settlement_credit = float(betting_state.get("pending_expected_settlement_credit", 0.0) or 0.0)
    early_settlement_credit_buffer = float(betting_state.get("early_settlement_credit_buffer", 0.0) or 0.0)

    # Учитываем pending-значения второго слота (они хранятся в отдельном betting_state_2,
    # но деньги на одном счёте, поэтому сверяем суммарные ожидаемые движения).
    betting_state_2_ref = getattr(runtime_context, "betting_state_2", None)
    slot2_pending_bet_drop = float((betting_state_2_ref or {}).get("pending_expected_bet_drop", 0.0) or 0.0)
    slot2_pending_settlement = float((betting_state_2_ref or {}).get("pending_expected_settlement_credit", 0.0) or 0.0)

    # Если рост баланса пришел раньше RES (race), накапливаем его в буфере и
    # затем погашаем им ожидаемый settlement_credit, когда тот появится.
    if early_settlement_credit_buffer > 0.009:
        total_pending_settlement_for_buffer = pending_expected_settlement_credit + slot2_pending_settlement
        if total_pending_settlement_for_buffer > 0.009:
            covered_by_early_buffer = min(early_settlement_credit_buffer, total_pending_settlement_for_buffer)
            slot1_buffer_used = min(covered_by_early_buffer, pending_expected_settlement_credit)
            slot2_buffer_used = covered_by_early_buffer - slot1_buffer_used

            pending_expected_settlement_credit = max(0.0, pending_expected_settlement_credit - slot1_buffer_used)
            if betting_state_2_ref is not None:
                betting_state_2_ref["pending_expected_settlement_credit"] = max(
                    0.0,
                    slot2_pending_settlement - slot2_buffer_used,
                )
                slot2_pending_settlement = max(0.0, slot2_pending_settlement - slot2_buffer_used)

            early_settlement_credit_buffer = max(0.0, early_settlement_credit_buffer - covered_by_early_buffer)

            if runtime_config.betting.debug_enabled:
                print(
                    (
                        "[ACCOUNTING][DEBUG] early settlement buffer погасил ожидаемый settlement: "
                        f"covered={covered_by_early_buffer:.0f}р, "
                        f"buffer_left={early_settlement_credit_buffer:.0f}р"
                    ),
                    flush=True,
                )

    withdrawal_detected = False
    withdrawal_amount = 0.0
    deposit_detected = False
    deposit_amount = 0.0

    if isinstance(previous_balance, (int, float)) and new_balance < previous_balance:
        actual_drop = float(previous_balance) - new_balance
        total_pending_bet_drop = pending_expected_bet_drop + slot2_pending_bet_drop
        covered_by_bet = min(actual_drop, total_pending_bet_drop)
        # Уменьшаем сначала слот 1, потом слот 2
        slot1_bet_used = min(covered_by_bet, pending_expected_bet_drop)
        slot2_bet_used = covered_by_bet - slot1_bet_used
        pending_expected_bet_drop = max(0.0, pending_expected_bet_drop - slot1_bet_used)
        if betting_state_2_ref is not None:
            betting_state_2_ref["pending_expected_bet_drop"] = max(0.0, slot2_pending_bet_drop - slot2_bet_used)
            slot2_pending_bet_drop = max(0.0, slot2_pending_bet_drop - slot2_bet_used)
        withdrawal_amount = actual_drop - covered_by_bet

        if withdrawal_amount > 0.009:
            withdrawal_detected = True
            betting_state["external_withdrawals_total"] = betting_state.get("external_withdrawals_total", 0.0) + withdrawal_amount
            print(
                f"[ACCOUNTING] Обнаружен вывод: -{withdrawal_amount:.0f}р",
                flush=True,
            )
            queue_telegram_notification_func(
                "[BuyBayBye] Обнаружен вывод средств",
                (
                    "Accounting balance уменьшился вне ожидаемого списания ставки.\n"
                    f"Сумма вывода: {withdrawal_amount:.0f}р\n"
                    f"Новый real balance: {new_balance:.0f}р"
                ),
                dedup_key="withdrawal_detected",
                enabled=runtime_config.telegram.notify_withdrawals,
            )
    elif isinstance(previous_balance, (int, float)) and new_balance > previous_balance:
        actual_rise = new_balance - float(previous_balance)
        total_pending_settlement = pending_expected_settlement_credit + slot2_pending_settlement
        covered_by_settlement = min(actual_rise, total_pending_settlement)
        # Уменьшаем сначала слот 1, потом слот 2
        slot1_credit_used = min(covered_by_settlement, pending_expected_settlement_credit)
        slot2_credit_used = covered_by_settlement - slot1_credit_used
        pending_expected_settlement_credit = max(0.0, pending_expected_settlement_credit - slot1_credit_used)
        if betting_state_2_ref is not None:
            betting_state_2_ref["pending_expected_settlement_credit"] = max(0.0, slot2_pending_settlement - slot2_credit_used)
            slot2_pending_settlement = max(0.0, slot2_pending_settlement - slot2_credit_used)
        remaining_rise = actual_rise - covered_by_settlement
        # pending_expected_bet_drop может быть ненулевым, если:
        # 1) ставка была зафиксирована как pending, но WS пришёл раньше HTTP-ответа (race condition)
        #    → списание уже обработано как вывод, но pending остался;
        # 2) PAUSE/RESUME вернул ставку на счёт без уменьшения баланса.
        # В обоих случаях необходимо погасить pending_expected_bet_drop встречным ростом баланса,
        # чтобы сиротский остаток не вызвал ложный депозит позднее.
        # Поглощение выполняется ВСЕГДА при remaining_rise > 0, независимо от наличия settlement.
        if remaining_rise > 0.0:
            total_remaining_bet_drop = pending_expected_bet_drop + slot2_pending_bet_drop
            if total_remaining_bet_drop > 0.009:
                covered_by_pending_drop = min(remaining_rise, total_remaining_bet_drop)
                slot1_drop_used2 = min(covered_by_pending_drop, pending_expected_bet_drop)
                slot2_drop_used2 = covered_by_pending_drop - slot1_drop_used2
                pending_expected_bet_drop = max(0.0, pending_expected_bet_drop - slot1_drop_used2)
                if betting_state_2_ref is not None:
                    betting_state_2_ref["pending_expected_bet_drop"] = max(0.0, slot2_pending_bet_drop - slot2_drop_used2)
                    slot2_pending_bet_drop = max(0.0, slot2_pending_bet_drop - slot2_drop_used2)
                remaining_rise -= covered_by_pending_drop
                if runtime_config.betting.debug_enabled and covered_by_pending_drop > 0.009:
                    print(
                        f"[ACCOUNTING][DEBUG] pending_expected_bet_drop погасил рост баланса: "
                        f"covered={covered_by_pending_drop:.0f}р, remaining={remaining_rise:.0f}р",
                        flush=True,
                    )
        if remaining_rise > 0.009:
            pending_bets_slot1 = bool(betting_state.get("pending_bets"))
            pending_bets_slot2 = bool((betting_state_2_ref or {}).get("pending_bets"))
            total_pending_settlement_after_cover = pending_expected_settlement_credit + slot2_pending_settlement

            # Если есть pending_bets, но ожидаемый settlement еще не выставлен,
            # считаем этот рост ранним settlement и не маркируем как депозит.
            if total_pending_settlement_after_cover <= 0.009 and (pending_bets_slot1 or pending_bets_slot2):
                early_settlement_credit_buffer += remaining_rise
                if runtime_config.betting.debug_enabled:
                    print(
                        (
                            "[ACCOUNTING][DEBUG] Зафиксирован ранний рост баланса до RES, "
                            f"переносим в buffer: +{remaining_rise:.0f}р"
                        ),
                        flush=True,
                    )
                remaining_rise = 0.0

        if remaining_rise > 0.009:
            deposit_detected = True
            deposit_amount = remaining_rise
            betting_state["external_deposits_total"] = betting_state.get("external_deposits_total", 0.0) + deposit_amount
            print(
                f"[ACCOUNTING] Обнаружено пополнение: +{deposit_amount:.0f}р",
                flush=True,
            )
            queue_telegram_notification_func(
                "[BuyBayBye] Обнаружено пополнение средств",
                (
                    "Accounting balance вырос вне ожидаемого расчета ставки.\n"
                    f"Сумма пополнения: {deposit_amount:.0f}р\n"
                    f"Новый real balance: {new_balance:.0f}р"
                ),
                dedup_key="deposit_detected",
                enabled=runtime_config.telegram.notify_deposits,
            )

    betting_state["pending_expected_bet_drop"] = pending_expected_bet_drop
    betting_state["pending_expected_settlement_credit"] = pending_expected_settlement_credit
    betting_state["early_settlement_credit_buffer"] = early_settlement_credit_buffer
    if pending_expected_bet_drop > 0.009:
        betting_state["reconciliation_phase"] = "awaiting_bet_drop"
    elif pending_expected_settlement_credit > 0.009:
        betting_state["reconciliation_phase"] = "awaiting_settlement"
    elif withdrawal_detected:
        betting_state["reconciliation_phase"] = "external_withdrawal"
    elif deposit_detected:
        betting_state["reconciliation_phase"] = "external_deposit"
    else:
        betting_state["reconciliation_phase"] = "idle"
    betting_state["last_external_balance_change_type"] = "deposit" if deposit_detected else ("withdrawal" if withdrawal_detected else None)
    betting_state["last_external_balance_change_amount"] = deposit_amount if deposit_detected else withdrawal_amount
    betting_state["account_balance"] = new_balance
    betting_state["account_balance_type"] = normalized_balance_type
    betting_state["account_balance_updated_at"] = datetime.now(timezone.utc).isoformat()
    betting_state["last_accounting_rejection_reason"] = None
    update_runtime_snapshot_func(
        "balance_update",
        {
            "account_balance": new_balance,
            "withdrawal_detected": withdrawal_detected,
            "withdrawal_amount": withdrawal_amount,
            "deposit_detected": deposit_detected,
            "deposit_amount": deposit_amount,
            "reconciliation_phase": betting_state.get("reconciliation_phase"),
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
    active_page = runtime_context.active_page or page
    if active_page.is_closed():
        return False

    print(f"[ACCOUNTING] Баланс устарел, перезагружаем страницу для восстановления канала ({reason})...", flush=True)
    queue_telegram_notification_func(
        "[BuyBayBye] Проблема с accounting balance",
        f"Запущено восстановление accounting_ws.\nПричина: {reason}\nПоследний real balance: {get_balance_for_log_func()}",
        dedup_key=f"accounting_recovery_start:{reason}",
        enabled=runtime_config.telegram.notify_accounting_issues,
    )
    betting_state["last_accounting_recovery_attempted_at"] = datetime.now(timezone.utc).isoformat()
    betting_state["accounting_recovery_attempts"] = int(betting_state.get("accounting_recovery_attempts", 0) or 0) + 1

    try:
        await active_page.reload(wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        if _is_page_crashed_error(exc):
            crash_count = int(betting_state.get("accounting_consecutive_page_crashes", 0) or 0) + 1
            betting_state["accounting_consecutive_page_crashes"] = crash_count
            threshold = runtime_config.accounting.page_crash_restart_threshold
            if crash_count >= threshold:
                fatal_message = (
                    "[ACCOUNTING] Достигнут порог подряд идущих page crash при recovery "
                    f"({crash_count}/{threshold}). Останавливаем процесс для контролируемого рестарта."
                )
                print(fatal_message, flush=True)
                update_runtime_snapshot_func(
                    "accounting_recovery_fatal",
                    {
                        "accounting_recovery_reason": reason,
                        "consecutive_page_crashes": crash_count,
                        "page_crash_restart_threshold": threshold,
                    },
                )
                queue_telegram_notification_func(
                    "[BuyBayBye] Критическая ошибка recovery accounting_ws",
                    (
                        "Достигнут порог подряд идущих page crash во время восстановления accounting_ws.\n"
                        f"Порог: {threshold}\n"
                        f"Текущий счетчик: {crash_count}\n"
                        f"Причина: {reason}\n"
                        "Процесс будет остановлен для внешнего рестарта."
                    ),
                    dedup_key="accounting_recovery_page_crash_threshold",
                    enabled=runtime_config.telegram.notify_accounting_issues,
                )
                raise RuntimeError(fatal_message)

            print("[ACCOUNTING] Обнаружен crash страницы во время recovery, пробуем пересоздать страницу...", flush=True)
            try:
                recovered, target_url = await _recover_from_crashed_page(page=active_page, runtime_context=runtime_context)
            except Exception as recover_exc:
                print(
                    f"[ACCOUNTING] Не удалось восстановиться после page crash через новую страницу: {recover_exc}",
                    flush=True,
                )
            else:
                if recovered:
                    betting_state["last_accounting_recovery_at"] = datetime.now(timezone.utc).isoformat()
                    update_runtime_snapshot_func(
                        "accounting_recovery",
                        {
                            "accounting_recovery_reason": reason,
                            "accounting_recovery_attempts": betting_state.get("accounting_recovery_attempts"),
                            "recovery_mode": "new_page_after_crash",
                            "recovery_target_url": target_url,
                        },
                    )
                    queue_telegram_notification_func(
                        "[BuyBayBye] accounting_ws восстановлен",
                        (
                            "Страница упала во время reload, выполнено восстановление через новую страницу.\n"
                            f"Причина: {reason}\n"
                            f"Текущий real balance: {get_balance_for_log_func()}"
                        ),
                        dedup_key=f"accounting_recovery_success_after_crash:{reason}",
                        enabled=runtime_config.telegram.notify_accounting_issues,
                    )
                    return True

        print(f"[ACCOUNTING] Ошибка перезагрузки страницы при восстановлении accounting_ws: {exc}", flush=True)
        queue_telegram_notification_func(
            "[BuyBayBye] Ошибка восстановления accounting_ws",
            f"Page reload завершился ошибкой.\nПричина: {reason}\nОшибка: {exc}",
            dedup_key=f"accounting_recovery_error:{reason}",
            enabled=runtime_config.telegram.notify_accounting_issues,
        )
        return False

    betting_state["accounting_consecutive_page_crashes"] = 0
    betting_state["last_accounting_recovery_at"] = datetime.now(timezone.utc).isoformat()
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

        active_page = runtime_context.active_page or page
        if active_page.is_closed():
            return

        last_recovery_age = get_accounting_age_seconds_func("last_accounting_recovery_attempted_at")
        if last_recovery_age is not None and last_recovery_age < runtime_config.accounting.recovery_cooldown_seconds:
            continue

        ws_age = get_accounting_age_seconds_func("last_accounting_ws_message_at")
        ws_open_age = get_accounting_age_seconds_func("last_accounting_ws_opened_at")
        balance_age = get_accounting_age_seconds_func("account_balance_updated_at")

        reason = None
        if betting_state.get("accounting_ws_connected") is False and betting_state.get("last_accounting_ws_closed_at"):
            reason = "accounting_ws closed"
        elif (
            runtime_config.accounting.recovery_reload_on_stale_balance
            and is_account_balance_stale_func()
            and balance_age is not None
            and balance_age >= runtime_config.accounting.recovery_reload_seconds
        ):
            reason = f"balance_update stale for {balance_age:.0f}s"
        elif (
            betting_state.get("account_balance") is not None
            and ws_age is not None
            and ws_age >= runtime_config.accounting.recovery_reload_seconds
            and float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0) > 0
        ):
            reason = f"no accounting messages for {ws_age:.0f}s"
        elif (
            betting_state.get("accounting_ws_connected")
            and betting_state.get("account_balance") is None
            and ws_open_age is not None
            and ws_open_age >= runtime_config.accounting.initial_balance_timeout_seconds
        ):
            reason = f"initial balance_update missing for {ws_open_age:.0f}s"
        elif betting_state.get("accounting_ws_connected"):
            idle_threshold = runtime_config.accounting.idle_reconnect_seconds
            if ws_age is not None and ws_age >= idle_threshold:
                reason = f"accounting_ws idle for {ws_age:.0f}s"
            elif ws_age is None and ws_open_age is not None and ws_open_age >= idle_threshold:
                reason = f"accounting_ws connected without messages for {ws_open_age:.0f}s"

        if reason:
            await reload_page_for_accounting_recovery_func(active_page, reason)
