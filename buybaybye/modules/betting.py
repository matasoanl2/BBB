"""Вспомогательные функции для размещения ставок и обработки результатов раундов."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import BetTarget, RuntimeConfig


def format_bet_log(
    *,
    action: str,
    status_icon: str,
    outcome: str = "-",
    amount: str = "-",
    step: str = "-",
    result: str = "-",
    profit: str = "-",
    roi: str = "-",
    balance: str = "-",
    real_balance: str = "-",
    error_msg: str = "",
    bets_count: str = "",
    color_reset: str,
    color_yellow: str,
    color_green: str,
    color_red: str,
    color_magenta: str,
    color_cyan: str,
    pad_width_center_func,
    format_result_pretty_func,
) -> str:
    """Собрать форматированную строку лога для SET/RES событий ставки."""

    time_str = datetime.now().strftime("%H:%M:%S")
    reset_full = color_reset
    result_col_width = 13

    if action in ["SET", "RES"] and status_icon == "✅":
        line_color = color_green if action == "RES" else color_yellow
        result_display = result if action == "RES" else "-" * result_col_width
    elif action == "RES" and status_icon == "❌":
        line_color = color_red
        result_display = result
    else:
        line_color = color_magenta
        result_display = result

    time_part = f"{line_color}[{time_str}]{reset_full}"
    bet_part = f"{line_color}[BET]{reset_full}"

    if bets_count and bets_count.strip():
        bet_number_part = f"{color_cyan}[#{bets_count}]{reset_full}"
    else:
        bet_number_part = "[#---]"
    step_part = step

    result_display_fmt = format_result_pretty_func(result_display)

    try:
        balance_value = float(balance.replace("р", "").strip())
        if balance_value > 0:
            balance_colored = f"{color_green}🧰 {balance}{reset_full}"
        elif balance_value < 0:
            balance_colored = f"{color_red}🧰 {balance}{reset_full}"
        else:
            balance_colored = f"🧰 {balance}"
    except (ValueError, AttributeError):
        balance_colored = f"🧰 {balance}"

    try:
        float(real_balance.replace("р", "").strip())
        real_balance_colored = f"{color_cyan}💰 {real_balance}{reset_full}"
    except (ValueError, AttributeError):
        real_balance_colored = f"💰 {real_balance}"

    status_icon_colored = f"{line_color}{status_icon}{reset_full}"
    action_colored = f"{line_color}{action}{reset_full}"
    outcome_colored = f"{line_color}{outcome}{reset_full}"
    amount_colored = f"{color_magenta}{amount}{reset_full}"
    result_colored = f"{line_color}{result_display_fmt}{reset_full}"
    profit_colored = f"{line_color}{profit}{reset_full}"
    roi_colored = f"{line_color}{roi}{reset_full}"

    log_parts = [
        pad_width_center_func(time_part, 10),
        pad_width_center_func(status_icon_colored, 2),
        pad_width_center_func(bet_part, 5),
        pad_width_center_func(bet_number_part, 6),
        pad_width_center_func(step_part, 6),
        pad_width_center_func(action_colored, 4),
        pad_width_center_func(outcome_colored, 6),
        pad_width_center_func(amount_colored, 7),
        pad_width_center_func(result_colored, result_col_width),
        pad_width_center_func(profit_colored, 7),
        pad_width_center_func(roi_colored, 9),
        pad_width_center_func(balance_colored, 10),
        pad_width_center_func(real_balance_colored, 12),
    ]

    log_line = " | ".join(log_parts)
    if error_msg:
        log_line += f"\n{color_magenta}↳ ERROR: {error_msg}{reset_full}"
    return log_line


def calculate_bet_amount(*, base_bet: float, runtime_context: RuntimeContext) -> float:
    """Рассчитать размер следующей ставки по текущему шагу стратегии."""

    if not runtime_context.current_strategy or not runtime_context.betting_state:
        return base_bet

    current_step = runtime_context.betting_state.get("current_step", 0)
    coefficients = runtime_context.current_strategy.get("coefficients", [1])
    step_index = min(current_step, len(coefficients) - 1)
    coefficient = coefficients[step_index]
    amount = base_bet * coefficient
    runtime_context.betting_state["last_bet_amount"] = amount
    return amount


def _format_bet_target_token(outcome: str, specifier: str) -> str:
    if outcome == "double":
        return "D"
    prefix = "R" if outcome == "red" else "Y"
    return f"{prefix}{specifier}"


def _format_bet_targets_pretty(bet_targets: tuple[BetTarget, ...], format_outcome_pretty_func) -> str:
    return ", ".join(format_outcome_pretty_func(target.outcome, target.specifier) for target in bet_targets)


def _normalize_account_balance(raw_balance) -> float | None:
    try:
        if raw_balance is None:
            return None
        return float(raw_balance)
    except (TypeError, ValueError):
        return None


def _clear_low_balance_pause_state(betting_state: dict) -> None:
    betting_state["low_balance_pause_active"] = False
    betting_state["low_balance_pause_required_balance"] = 0.0
    betting_state["low_balance_pause_started_at"] = None
    betting_state["low_balance_pause_targets"] = []


def _set_low_balance_pause_state(betting_state: dict, *, amount: float, bet_targets: tuple[BetTarget, ...]) -> bool:
    target_tokens = [target.token for target in bet_targets]
    state_changed = (
        not betting_state.get("low_balance_pause_active")
        or float(betting_state.get("low_balance_pause_required_balance", 0.0) or 0.0) != float(amount)
        or list(betting_state.get("low_balance_pause_targets") or []) != target_tokens
    )
    betting_state["low_balance_pause_active"] = True
    betting_state["low_balance_pause_required_balance"] = float(amount)
    betting_state["low_balance_pause_targets"] = target_tokens
    if state_changed:
        betting_state["low_balance_pause_started_at"] = datetime.now(timezone.utc).isoformat()
    return state_changed


def _get_affordable_bet_targets(
    *,
    bet_targets: tuple[BetTarget, ...],
    amount: float,
    available_balance: float | None,
) -> tuple[BetTarget, ...]:
    if available_balance is None or amount <= 0:
        return bet_targets

    affordable_count = int(available_balance // amount)
    if affordable_count <= 0:
        return ()

    return bet_targets[: min(len(bet_targets), affordable_count)]


def _is_insufficient_balance_response(status_code: int, response_text: str) -> bool:
    if status_code != 400 or not response_text:
        return False

    lowered_response = response_text.lower()
    return "недостаточно средств" in lowered_response or "insufficient" in lowered_response


def _build_bet_payload(target: BetTarget, amount: float) -> dict:
    if target.outcome == "double":
        return {
            "market": "gtlt",
            "outcome": "double",
            "specifier": "",
            "sum": amount,
            "balance_type": "balance",
        }

    return {
        "market": "value",
        "outcome": target.outcome,
        "specifier": target.specifier,
        "sum": amount,
        "balance_type": "balance",
    }


def _is_target_win(target: BetTarget, dice_results: list[dict]) -> tuple[bool, str, int | None]:
    if target.outcome == "double":
        dice_values = [dice.get("value") for dice in dice_results]
        is_double = len(dice_values) == 2 and dice_values[0] == dice_values[1] and dice_values[0] is not None
        return is_double, "double", dice_values[0] if is_double else None

    for dice in dice_results:
        if dice.get("color") != target.outcome:
            continue
        actual_value = dice.get("value")
        return actual_value == int(target.specifier), target.outcome, actual_value

    return False, target.outcome, None


async def place_bets(
    page,
    bet_targets,
    amount: float,
    *,
    allow_refresh_retry: bool = True,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    get_jwt_token_func,
    validate_base_bet_func,
    calculate_roi_func,
    format_outcome_pretty_func,
    format_bet_log_func,
    get_balance_for_log_func,
    get_db_connection_func,
    is_forbidden_access_error_func,
    reload_page_and_refresh_token_func,
    advance_step_after_set_error_func,
    update_runtime_snapshot_func,
    queue_telegram_notification_func,
) -> bool:
    betting_state = runtime_context.betting_state
    current_strategy = runtime_context.current_strategy
    jwt_token = runtime_context.jwt_token
    betting_config = runtime_config.betting
    telegram_config = runtime_config.telegram
    normalized_targets = tuple(bet_targets)
    requested_targets = normalized_targets
    targets_display = _format_bet_targets_pretty(normalized_targets, format_outcome_pretty_func)
    total_round_amount = amount * len(normalized_targets)
    next_round_number = int(betting_state.get("total_bet_rounds", 0) or 0) + 1
    next_round_display = str(next_round_number).zfill(3)

    if not normalized_targets:
        print("[WARNING] Не передано ни одной цели ставки для текущего раунда.", flush=True)
        return False

    if not jwt_token:
        print("[WARNING] JWT токен ещё не найден! Ставки НЕ будут размещены.", flush=True)
        advance_step_after_set_error_func()
        return False

    if betting_config.debug_enabled:
        print(
            f"[DEBUG PLACE_BETS] targets={[target.token for target in normalized_targets]}, amount_per_target={amount}, total={total_round_amount}",
            flush=True,
        )

    if not validate_base_bet_func(amount):
        print(f"[ERROR] Ставка {amount}р ДОЛЖНА делиться на 10 нацело! Ставки НЕ размещены.", flush=True)
        advance_step_after_set_error_func()
        return False

    try:
        step_for_history = betting_state.get("current_step", 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
        available_balance = _normalize_account_balance(betting_state.get("account_balance"))
        was_low_balance_paused = bool(betting_state.get("low_balance_pause_active"))
        if available_balance is None:
            if was_low_balance_paused:
                return False
            if betting_config.debug_enabled and betting_state.get("total_bets_placed", 0) == 0:
                print("[SET-CHECK] Баланс из accounting_ws пока неизвестен, первую batch-ставку пропускаем без проверки лимита.", flush=True)
        else:
            affordable_targets = _get_affordable_bet_targets(
                bet_targets=normalized_targets,
                amount=amount,
                available_balance=available_balance,
            )
            if not affordable_targets:
                pause_changed = _set_low_balance_pause_state(
                    betting_state,
                    amount=amount,
                    bet_targets=normalized_targets,
                )
                betting_state["last_bet_amount"] = 0.0
                betting_state["last_set_amount"] = total_round_amount
                betting_state["last_set_status"] = "paused_low_balance"
                betting_state["last_set_error"] = (
                    f"Пауза: баланс {available_balance:.0f}р меньше минимальной ставки {amount:.0f}р на одну цель"
                )
                if pause_changed:
                    roi = calculate_roi_func()
                    log_line = format_bet_log_func(
                        action="SET",
                        status_icon="❌",
                        outcome=targets_display,
                        amount=f"{total_round_amount:.0f}р",
                        step=f"{step_for_history+1}/{max_steps}",
                        result="PAUSE",
                        profit="-",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state.get('session_balance', 0):.0f}р",
                        real_balance=get_balance_for_log_func(),
                        error_msg=betting_state["last_set_error"],
                        bets_count=next_round_display,
                    )
                    print(log_line, flush=True)
                    print("[SET-PAUSE] Возобновим ставки автоматически после восстановления real balance.", flush=True)
                    update_runtime_snapshot_func(
                        "bet_low_balance_pause",
                        {
                            "last_set_amount": total_round_amount,
                            "last_set_status": betting_state.get("last_set_status"),
                            "last_set_error": betting_state.get("last_set_error"),
                            "requested_targets": [target.token for target in requested_targets],
                            "effective_targets": [],
                            "low_balance_pause_active": True,
                            "low_balance_pause_required_balance": amount,
                        },
                    )
                return False

            if was_low_balance_paused:
                _clear_low_balance_pause_state(betting_state)
                print(
                    f"[SET-RESUME] Real balance восстановлен до {available_balance:.0f}р, продолжаем размещение ставок.",
                    flush=True,
                )
                update_runtime_snapshot_func(
                    "bet_low_balance_resume",
                    {
                        "account_balance": available_balance,
                        "requested_targets": [target.token for target in requested_targets],
                        "effective_targets": [target.token for target in affordable_targets],
                        "low_balance_pause_active": False,
                    },
                )

            if len(affordable_targets) < len(normalized_targets):
                print(
                    "[SET-CHECK] Недостаточно real balance для полного batch, "
                    f"размещаем {len(affordable_targets)}/{len(normalized_targets)} целей.",
                    flush=True,
                )
            normalized_targets = affordable_targets
            targets_display = _format_bet_targets_pretty(normalized_targets, format_outcome_pretty_func)
            total_round_amount = amount * len(normalized_targets)

    except Exception as exc:
        betting_state["last_bet_amount"] = 0.0
        betting_state["last_set_status"] = "precheck_error"
        betting_state["last_set_error"] = str(exc)[:100]
        roi = calculate_roi_func()
        log_line = format_bet_log_func(
            action="SET",
            status_icon="❌",
            outcome=targets_display,
            amount=f"{total_round_amount:.0f}р",
            step="-",
            result="ERROR",
            profit="-",
            roi=f"{roi:.2f}%",
            balance=f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=get_balance_for_log_func(),
            error_msg=str(exc)[:100],
            bets_count=next_round_display,
        )
        print(log_line, flush=True)
        old_step, max_steps, restarted = advance_step_after_set_error_func()
        if betting_config.debug_enabled:
            new_step = betting_state.get("current_step", 0)
            restart_note = " [♻️ RESTART]" if restarted else ""
            print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
        update_runtime_snapshot_func(
            "bet_precheck_error",
            {
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
            },
        )
        return False

    delay = random.uniform(betting_config.bet_delay_min, betting_config.bet_delay_max)
    await asyncio.sleep(delay)

    try:
        step_for_history = betting_state.get("current_step", 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
        payload = {"bets": [_build_bet_payload(target, amount) for target in normalized_targets]}
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://betboom.ru/game/nardsgame",
            "Origin": "https://betboom.ru",
            "X-Requested-With": "XMLHttpRequest",
        }
        if jwt_token:
            headers["X-Access-Token"] = jwt_token

        response = await page.request.post(runtime_config.browser.bet_api_url, data=json.dumps(payload), headers=headers)
        status_code = response.status
        response_text = await response.text()

        try:
            response_json = json.loads(response_text)
            if isinstance(response_json, dict) and "code" in response_json:
                status_code = response_json["code"]
        except (json.JSONDecodeError, ValueError):
            pass

        if betting_config.debug_enabled:
            print("[DEBUG] ========== BATCH BET REQUEST ==========>", flush=True)
            print(f"[DEBUG] Page URL: {page.url}", flush=True)
            print(f"[DEBUG] API URL: {runtime_config.browser.bet_api_url}", flush=True)
            print(f"[DEBUG] Payload: {json.dumps(payload)}", flush=True)
            print(f"[DEBUG] Response Status: {status_code}", flush=True)
            print(f"[DEBUG] Response Body: {response_text}", flush=True)
            print("[DEBUG] =======================================", flush=True)

        try:
            conn = get_db_connection_func()
            cursor = conn.cursor()
            should_refresh_token = is_forbidden_access_error_func(status_code, response_text)

            snapshot_event_type = "bet_set"
            if status_code == 200:
                previous_total_bets = betting_state.get("total_bets_placed", 0)
                current_round_number = next_round_number
                betting_state["total_bet_amount"] += total_round_amount
                betting_state["total_bets_placed"] = previous_total_bets + len(normalized_targets)
                betting_state["total_bet_rounds"] = current_round_number
                betting_state["last_bet_round_number"] = current_round_number
                betting_state["pending_expected_bet_drop"] = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0) + total_round_amount
                betting_state["last_bet_amount"] = total_round_amount
                betting_state["last_set_amount"] = total_round_amount
                betting_state["last_set_status"] = "pending"
                betting_state["last_set_error"] = None

                payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
                potential_single_margin = (amount * payout_coeff) - amount
                potential_total_margin = potential_single_margin * len(normalized_targets)
                pending_bets = []
                for index, target in enumerate(normalized_targets, start=1):
                    cursor.execute(
                        """
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            datetime.now(timezone.utc),
                            target.outcome,
                            target.specifier,
                            amount,
                            betting_config.strategy_name,
                            step_for_history,
                            "pending",
                        ),
                    )
                    history_id_row = cursor.fetchone()
                    history_id = history_id_row[0] if history_id_row else None
                    pending_bets.append(
                        {
                            "history_id": history_id,
                            "outcome": target.outcome,
                            "specifier": target.specifier,
                            "amount": amount,
                            "bet_step": step_for_history,
                            "token": target.token,
                            "round_number": current_round_number,
                        }
                    )

                betting_state["pending_bets"] = pending_bets
                roi = calculate_roi_func()
                log_line = format_bet_log_func(
                    action="SET",
                    status_icon="✅",
                    outcome=targets_display,
                    amount=f"{total_round_amount:.0f}р",
                    step=f"{step_for_history+1}/{max_steps}",
                    result="------",
                    profit=f"+{potential_total_margin:.0f}р",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=get_balance_for_log_func(),
                    bets_count=str(current_round_number).zfill(3),
                )
                print(log_line, flush=True)
            else:
                betting_state["pending_bets"] = []
                betting_state["last_bet_amount"] = 0.0
                betting_state["last_set_amount"] = total_round_amount
                is_insufficient_balance = _is_insufficient_balance_response(status_code, response_text)
                betting_state["last_set_status"] = "forbidden_refresh" if should_refresh_token else "error"
                betting_state["last_set_error"] = response_text[:100] if response_text else "Unknown error"

                if should_refresh_token and allow_refresh_retry:
                    token_refreshed = await reload_page_and_refresh_token_func(page)
                    if token_refreshed:
                        betting_state["last_set_status"] = "retry_after_refresh"
                        betting_state["last_set_error"] = None
                        update_runtime_snapshot_func(
                            "bet_token_refreshed",
                            {
                                "last_set_amount": total_round_amount,
                                "last_set_status": betting_state.get("last_set_status"),
                                "token_refresh_triggered": True,
                                "requested_targets": [target.token for target in requested_targets],
                                "effective_targets": [target.token for target in normalized_targets],
                            },
                        )
                        cursor.close()
                        conn.close()
                        print("[AUTH] Повторяем batch-ставку один раз после обновления токена.", flush=True)
                        runtime_context.jwt_token = get_jwt_token_func()
                        return await place_bets(
                            page,
                            normalized_targets,
                            amount,
                            allow_refresh_retry=False,
                            runtime_context=runtime_context,
                            runtime_config=runtime_config,
                            get_jwt_token_func=get_jwt_token_func,
                            validate_base_bet_func=validate_base_bet_func,
                            calculate_roi_func=calculate_roi_func,
                            format_outcome_pretty_func=format_outcome_pretty_func,
                            format_bet_log_func=format_bet_log_func,
                            get_balance_for_log_func=get_balance_for_log_func,
                            get_db_connection_func=get_db_connection_func,
                            is_forbidden_access_error_func=is_forbidden_access_error_func,
                            reload_page_and_refresh_token_func=reload_page_and_refresh_token_func,
                            advance_step_after_set_error_func=advance_step_after_set_error_func,
                            update_runtime_snapshot_func=update_runtime_snapshot_func,
                            queue_telegram_notification_func=queue_telegram_notification_func,
                        )

                    queue_telegram_notification_func(
                        "[BuyBayBye] Ошибка авторизации batch-ставки",
                        f"403 FORBIDDEN, обновление JWT не помогло.\nСтавки: {targets_display}\nСумма: {total_round_amount:.0f}р",
                        dedup_key="auth_refresh_failed",
                        enabled=telegram_config.notify_auth_issues,
                    )

                if is_insufficient_balance:
                    pause_changed = _set_low_balance_pause_state(
                        betting_state,
                        amount=amount,
                        bet_targets=normalized_targets,
                    )
                    betting_state["last_set_status"] = "paused_low_balance"
                    snapshot_event_type = "bet_low_balance_pause"
                    roi = calculate_roi_func()
                    log_line = format_bet_log_func(
                        action="SET",
                        status_icon="❌",
                        outcome=targets_display,
                        amount=f"{total_round_amount:.0f}р",
                        step=f"{step_for_history+1}/{max_steps}",
                        result="PAUSE",
                        profit="-",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state.get('session_balance', 0):.0f}р",
                        real_balance=get_balance_for_log_func(),
                        error_msg=betting_state["last_set_error"],
                        bets_count=next_round_display,
                    )
                    print(log_line, flush=True)
                    if pause_changed:
                        print("[SET-PAUSE] API вернул недостаточно средств, шаг стратегии не сдвигаем.", flush=True)
                else:
                    roi = calculate_roi_func()
                    log_line = format_bet_log_func(
                        action="SET",
                        status_icon="❌",
                        outcome=targets_display,
                        amount=f"{total_round_amount:.0f}р",
                        step=f"{step_for_history+1}/{max_steps}",
                        result="ERROR",
                        profit="-",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state.get('session_balance', 0):.0f}р",
                        real_balance=get_balance_for_log_func(),
                        error_msg=response_text[:100] if response_text else "Unknown error",
                        bets_count=next_round_display,
                    )
                    print(log_line, flush=True)
                    old_step, max_steps, restarted = advance_step_after_set_error_func()
                    if betting_config.debug_enabled:
                        new_step = betting_state.get("current_step", 0)
                        restart_note = " [♻️ RESTART]" if restarted else ""
                        print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)

                    for target in normalized_targets:
                        cursor.execute(
                            """
                            INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                datetime.now(timezone.utc),
                                target.outcome,
                                target.specifier,
                                amount,
                                betting_config.strategy_name,
                                step_for_history,
                                "error",
                            ),
                        )

            snapshot_extra = {
                "last_set_amount": total_round_amount,
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
                "http_status": status_code,
                "token_refresh_triggered": should_refresh_token,
                "effective_targets": [target.token for target in normalized_targets],
                "requested_targets": [target.token for target in requested_targets],
                "pending_bets_count": len(betting_state.get("pending_bets", [])),
                "low_balance_pause_active": betting_state.get("low_balance_pause_active", False),
                "low_balance_pause_required_balance": betting_state.get("low_balance_pause_required_balance", 0.0),
            }
            conn.commit()
            cursor.close()
            conn.close()
            update_runtime_snapshot_func(snapshot_event_type, snapshot_extra)
        except Exception as exc:
            betting_state["pending_bets"] = []
            betting_state["last_bet_amount"] = 0.0
            betting_state["last_set_status"] = "db_error"
            betting_state["last_set_error"] = str(exc)[:100]
            roi = calculate_roi_func()
            log_line = format_bet_log_func(
                action="SET",
                status_icon="❌",
                outcome=targets_display,
                amount=f"{total_round_amount:.0f}р",
                step="-",
                result="DB_ERROR",
                profit="-",
                roi=f"{roi:.2f}%",
                balance=get_balance_for_log_func(),
                error_msg=str(exc)[:100],
                bets_count=next_round_display,
            )
            print(log_line, flush=True)
            queue_telegram_notification_func(
                "[BuyBayBye] Ошибка сохранения batch-ставки",
                f"Не удалось записать batch-ставку в БД.\nСтавки: {targets_display}\nСумма: {total_round_amount:.0f}р\nОшибка: {str(exc)[:300]}",
                dedup_key="bet_db_error",
                enabled=telegram_config.notify_bet_errors,
            )
            update_runtime_snapshot_func(
                "bet_db_error",
                {
                    "last_set_status": betting_state.get("last_set_status"),
                    "last_set_error": betting_state.get("last_set_error"),
                    "requested_targets": [target.token for target in requested_targets],
                    "effective_targets": [target.token for target in normalized_targets],
                },
            )

        return status_code == 200

    except Exception as exc:
        betting_state["pending_bets"] = []
        betting_state["last_bet_amount"] = 0.0
        betting_state["last_set_status"] = "request_error"
        betting_state["last_set_error"] = str(exc)[:100]
        roi = calculate_roi_func()
        log_line = format_bet_log_func(
            action="SET",
            status_icon="❌",
            outcome=targets_display,
            amount=f"{total_round_amount:.0f}р",
            step="-",
            result="ERROR",
            profit="-",
            roi=f"{roi:.2f}%",
            balance=f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=get_balance_for_log_func(),
            error_msg=str(exc)[:100],
            bets_count=next_round_display,
        )
        print(log_line, flush=True)
        queue_telegram_notification_func(
            "[BuyBayBye] Ошибка запроса batch-ставки",
            f"Запрос на размещение ставок завершился ошибкой.\nСтавки: {targets_display}\nСумма: {total_round_amount:.0f}р\nОшибка: {str(exc)[:300]}",
            dedup_key="bet_request_error",
            enabled=telegram_config.notify_bet_errors,
        )
        old_step, max_steps, restarted = advance_step_after_set_error_func()
        if betting_config.debug_enabled:
            new_step = betting_state.get("current_step", 0)
            restart_note = " [♻️ RESTART]" if restarted else ""
            print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
        update_runtime_snapshot_func(
            "bet_request_error",
            {
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
                "requested_targets": [target.token for target in requested_targets],
                "effective_targets": [target.token for target in normalized_targets],
            },
        )
        return False


async def place_bet(
    page,
    outcome: str,
    specifier: str,
    amount: float,
    *,
    allow_refresh_retry: bool = True,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    get_jwt_token_func,
    validate_base_bet_func,
    calculate_roi_func,
    format_outcome_pretty_func,
    format_bet_log_func,
    get_balance_for_log_func,
    get_db_connection_func,
    is_forbidden_access_error_func,
    reload_page_and_refresh_token_func,
    advance_step_after_set_error_func,
    update_runtime_snapshot_func,
    queue_telegram_notification_func,
) -> bool:
    """Разместить ставку через HTTP API и обновить runtime state по результату запроса."""
    return await place_bets(
        page,
        (BetTarget(outcome=outcome, specifier="" if outcome == "double" else specifier),),
        amount,
        allow_refresh_retry=allow_refresh_retry,
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        get_jwt_token_func=get_jwt_token_func,
        validate_base_bet_func=validate_base_bet_func,
        calculate_roi_func=calculate_roi_func,
        format_outcome_pretty_func=format_outcome_pretty_func,
        format_bet_log_func=format_bet_log_func,
        get_balance_for_log_func=get_balance_for_log_func,
        get_db_connection_func=get_db_connection_func,
        is_forbidden_access_error_func=is_forbidden_access_error_func,
        reload_page_and_refresh_token_func=reload_page_and_refresh_token_func,
        advance_step_after_set_error_func=advance_step_after_set_error_func,
        update_runtime_snapshot_func=update_runtime_snapshot_func,
        queue_telegram_notification_func=queue_telegram_notification_func,
    )


async def process_betting_round(
    page,
    payload: object,
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    format_ws_payload_func,
    get_db_connection_func,
    format_round_result_pretty_func,
    format_outcome_pretty_func,
    format_bet_log_func,
    get_balance_for_log_func,
    calculate_roi_func,
    update_runtime_snapshot_func,
    print_session_stats_func,
    print_dice_stats_20_func,
    update_dynamic_bet_func,
    generate_random_bet_func,
    calculate_bet_amount_func,
    place_bet_func,
    place_bets_func,
) -> None:
    betting_state = runtime_context.betting_state
    current_strategy = runtime_context.current_strategy
    dynamic_bet_mode = runtime_config.dynamic_betting.enabled and len(runtime_context.get_configured_bet_targets()) <= 1
    bet_debug_enabled = runtime_config.betting.debug_enabled
    try:
        payload_text = format_ws_payload_func(payload)
        parsed_payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if not isinstance(parsed_payload, dict) or parsed_payload.get("status") != "rng_values":
        return

    results = parsed_payload.get("results")
    if not isinstance(results, dict):
        return

    dice_results = results.get("dice", [])
    combo_stats = betting_state.get("combo_stats", {})
    for dice in dice_results:
        dice_value = dice.get("value")
        dice_color = dice.get("color")
        if dice_color in ["red", "yellow"] and dice_value and 1 <= dice_value <= 6:
            combo_key = f"{dice_color}_{dice_value}"
            if combo_key in combo_stats:
                combo_stats[combo_key] += 1

    if len(dice_results) == 2:
        values = [d.get("value") for d in dice_results]
        double_stats = betting_state.get("double_stats", {})
        if values[0] == values[1] and values[0] is not None:
            double_stats["doubles"] = double_stats.get("doubles", 0) + 1
        else:
            double_stats["no_doubles"] = double_stats.get("no_doubles", 0) + 1

    rolled_dice_representation = format_round_result_pretty_func(dice_results)
    betting_state["last_round_result"] = rolled_dice_representation
    betting_state["last_round_game_id"] = parsed_payload.get("game_id")
    betting_state["last_round_status"] = parsed_payload.get("status")
    betting_state["last_round_timestamp"] = datetime.now(timezone.utc).isoformat()
    player_info = results.get("player", {}) if isinstance(results.get("player"), dict) else {}
    betting_state["last_round_player_name"] = player_info.get("name")
    betting_state["last_round_position"] = player_info.get("position")

    pending_bets = list(betting_state.get("pending_bets") or [])
    had_resolved_bet = len(pending_bets) > 0
    actual_dice_representation = rolled_dice_representation

    if had_resolved_bet:
        conn = None
        cursor = None
        result_snapshot_extra = None
        try:
            conn = get_db_connection_func()
            cursor = conn.cursor()
            current_step_for_log = betting_state["current_step"]

            payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
            round_margin = 0.0
            settlement_credit = 0.0
            resolved_target_tokens: list[str] = []
            round_target_labels: list[str] = []
            winning_targets = 0

            for pending_bet in pending_bets:
                target = BetTarget(outcome=pending_bet["outcome"], specifier=pending_bet.get("specifier", ""))
                is_win, stored_dice_color, actual_dice_value = _is_target_win(target, dice_results)
                status = "win" if is_win else "loss"
                bet_amount = float(pending_bet.get("amount", 0.0) or 0.0)
                margin = (bet_amount * payout_coeff) - bet_amount if is_win else -bet_amount
                if is_win:
                    winning_targets += 1
                    settlement_credit += bet_amount * payout_coeff
                round_margin += margin
                resolved_token = pending_bet.get("token") or _format_bet_target_token(target.outcome, target.specifier)
                resolved_target_tokens.append(resolved_token)
                round_target_labels.append(format_outcome_pretty_func(target.outcome, target.specifier))

                if pending_bet.get("history_id") is not None:
                    cursor.execute(
                        """
                        UPDATE bet_history
                        SET status = %s, result_dice_color = %s, result_dice_value = %s
                        WHERE id = %s
                        """,
                        (status, stored_dice_color, actual_dice_value, pending_bet["history_id"]),
                    )

            max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
            betting_state["pending_bets"] = []
            betting_state["pending_expected_settlement_credit"] = settlement_credit
            betting_state["total_profit"] += round_margin
            betting_state["session_balance"] += round_margin

            restarted = False
            if round_margin > 0:
                betting_state["current_step"] = 0
                betting_state["consecutive_losses"] = 0
            elif current_step_for_log + 1 >= max_steps:
                betting_state["current_step"] = 0
                betting_state["consecutive_losses"] = 0
                restarted = True
            else:
                betting_state["current_step"] = current_step_for_log + 1
                betting_state["consecutive_losses"] = betting_state.get("consecutive_losses", 0) + 1

            roi = calculate_roi_func()
            total_bets = betting_state.get("total_bets_placed", 0)
            resolved_round_number = 0
            if pending_bets:
                resolved_round_number = int(pending_bets[0].get("round_number", 0) or 0)
            if resolved_round_number <= 0:
                resolved_round_number = int(betting_state.get("last_bet_round_number", 0) or 0)
            round_targets_display = ", ".join(round_target_labels)
            log_line = format_bet_log_func(
                action="RES",
                status_icon="✅" if round_margin > 0 else "❌",
                outcome=round_targets_display,
                amount=f"{betting_state.get('last_bet_amount', 0):.0f}р",
                step=(f"{current_step_for_log+1}/{max_steps}" if round_margin > 0 or not restarted else f"{max_steps}/{max_steps}"),
                result=actual_dice_representation,
                profit=f"{round_margin:+.0f}р",
                roi=f"{roi:.2f}%",
                balance=f"{betting_state['session_balance']:.0f}р",
                real_balance=get_balance_for_log_func(),
                bets_count=str(resolved_round_number or total_bets).zfill(3),
            )
            if restarted:
                print(log_line + " [♻️ RESTART]", flush=True)
            else:
                print(log_line, flush=True)

            if total_bets > 0 and total_bets % 50 == 0:
                print_session_stats_func(total_bets)
            if total_bets > 0 and total_bets % 20 == 0:
                print_dice_stats_20_func()

            result_snapshot_extra = {
                "bet_result_status": "win" if round_margin > 0 else "loss",
                "bet_result_value": winning_targets,
                "bet_result_display": actual_dice_representation,
                "requested_targets": resolved_target_tokens,
                "effective_targets": resolved_target_tokens,
            }
            conn.commit()
        except Exception as exc:
            print(f"[DB ERROR] Ошибка обновления результата ставки: {exc}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()
        if result_snapshot_extra is not None:
            update_runtime_snapshot_func("bet_result", result_snapshot_extra)

    if bet_debug_enabled:
        print(f"[DEBUG PROCESS] DYNAMIC_BET_MODE={dynamic_bet_mode}, calling _update_dynamic_bet", flush=True)
    if dynamic_bet_mode:
        if bet_debug_enabled:
            print("[DEBUG PROCESS] Entering if DYNAMIC_BET_MODE, calling function", flush=True)
        update_dynamic_bet_func()
    
    bet_targets_to_place: tuple[BetTarget, ...]
    if dynamic_bet_mode:
        current_outcome, current_specifier = runtime_context.get_current_bet_target()
        bet_targets_to_place = (BetTarget(outcome=current_outcome, specifier="" if current_outcome == "double" else current_specifier),)
    else:
        bet_targets_to_place = runtime_context.get_configured_bet_targets()

    consecutive_losses = betting_state.get("consecutive_losses", 0)
    random_fallback_enabled = runtime_config.dynamic_betting.random_fallback_enabled
    random_fallback_loss_streak = runtime_config.dynamic_betting.random_fallback_loss_streak
    if random_fallback_enabled and len(bet_targets_to_place) == 1 and consecutive_losses >= random_fallback_loss_streak:
        print("", flush=True)
        new_outcome, new_specifier = generate_random_bet_func()
        runtime_context.set_current_bet_target(new_outcome, new_specifier)
        betting_state["consecutive_losses"] = 0
        print("", flush=True)
        bet_targets_to_place = (BetTarget(outcome=new_outcome, specifier="" if new_outcome == "double" else new_specifier),)

    bet_amount = calculate_bet_amount_func()
    if bet_debug_enabled:
        print(
            f"[DEBUG PROCESS_BET] Вызов place_bets для {[target.token for target in bet_targets_to_place]} по {bet_amount:.0f}р на цель",
            flush=True,
        )
    await place_bets_func(page, bet_targets_to_place, bet_amount)
