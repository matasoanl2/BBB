from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone


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
    time_str = datetime.now().strftime("%H:%M:%S")
    reset_full = color_reset
    result_col_width = 13

    if action == "SET" and status_icon == "✅":
        line_color = color_yellow
        result_display = "-" * result_col_width
    elif action == "RES" and status_icon == "✅":
        line_color = color_green
        result_display = result
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


def calculate_bet_amount(*, base_bet: float, betting_state: dict, current_strategy: dict | None) -> float:
    if not current_strategy or not betting_state:
        return base_bet

    current_step = betting_state.get("current_step", 0)
    coefficients = current_strategy.get("coefficients", [1])
    step_index = min(current_step, len(coefficients) - 1)
    coefficient = coefficients[step_index]
    amount = base_bet * coefficient
    betting_state["last_bet_amount"] = amount
    return amount


async def place_bet(
    page,
    outcome: str,
    specifier: str,
    amount: float,
    *,
    allow_refresh_retry: bool = True,
    betting_state: dict,
    current_strategy: dict | None,
    strategy_name: str,
    bet_api_url: str,
    jwt_token: str | None,
    get_jwt_token_func,
    bet_delay_min: float,
    bet_delay_max: float,
    bet_debug_enabled: bool,
    telegram_notify_bet_errors: bool,
    telegram_notify_auth_issues: bool,
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
    requested_specifier = specifier

    if not jwt_token:
        print("[WARNING] JWT токен ещё не найден! Ставка НЕ будет размещена.", flush=True)
        advance_step_after_set_error_func()
        return False

    if bet_debug_enabled:
        print(f"[DEBUG PLACE_BET] outcome={outcome}, specifier={specifier}, amount={amount}", flush=True)

    if not validate_base_bet_func(amount):
        print(f"[ERROR] Ставка {amount}р ДОЛЖНА делиться на 10 нацело! Ставка НЕ размещена.", flush=True)
        advance_step_after_set_error_func()
        return False

    try:
        step_for_history = betting_state.get("current_step", 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
        available_balance = betting_state.get("account_balance")
        if available_balance is None:
            if bet_debug_enabled and betting_state.get("total_bets_placed", 0) == 0:
                print("[SET-CHECK] Баланс из accounting_ws пока неизвестен, первую ставку пропускаем без проверки лимита.", flush=True)
        else:
            try:
                available_balance = float(available_balance)
            except (TypeError, ValueError):
                available_balance = None

        if available_balance is not None and amount > available_balance:
            betting_state["last_set_amount"] = amount
            betting_state["last_set_status"] = "skipped_insufficient_balance"
            betting_state["last_set_error"] = f"Ставка пропущена: {amount:.0f}р > баланс {available_balance:.0f}р (accounting_ws)"
            roi = calculate_roi_func()
            log_line = format_bet_log_func(
                action="SET",
                status_icon="❌",
                outcome=format_outcome_pretty_func(outcome, specifier),
                amount=f"{amount}р",
                step=f"{step_for_history+1}/{max_steps}",
                result="SKIP",
                profit="-",
                roi=f"{roi:.2f}%",
                balance=f"{betting_state.get('session_balance', 0):.0f}р",
                real_balance=get_balance_for_log_func(),
                error_msg=f"Ставка пропущена: {amount:.0f}р > баланс {available_balance:.0f}р (accounting_ws)",
                bets_count=str(betting_state.get("total_bets_placed", 0)).zfill(3),
            )
            print(log_line, flush=True)

            try:
                conn = get_db_connection_func()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (datetime.now(timezone.utc), outcome, specifier, amount, strategy_name, step_for_history, "skipped_insufficient_balance"),
                )
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as db_err:
                print(f"[DB ERROR] Ошибка сохранения пропущенной ставки: {db_err}", flush=True)

            old_step, max_steps, restarted = advance_step_after_set_error_func()
            if bet_debug_enabled:
                new_step = betting_state.get("current_step", 0)
                restart_note = " [♻️ RESTART]" if restarted else ""
                print(f"[SET-SKIP] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
            update_runtime_snapshot_func(
                "bet_skipped",
                {
                    "last_set_amount": amount,
                    "last_set_status": betting_state.get("last_set_status"),
                    "last_set_error": betting_state.get("last_set_error"),
                },
            )
            return False

    except Exception as exc:
        betting_state["last_set_status"] = "precheck_error"
        betting_state["last_set_error"] = str(exc)[:100]
        roi = calculate_roi_func()
        log_line = format_bet_log_func(
            action="SET",
            status_icon="❌",
            outcome="-",
            amount="-",
            step="-",
            result="ERROR",
            profit="-",
            roi=f"{roi:.2f}%",
            balance=f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=get_balance_for_log_func(),
            error_msg=str(exc)[:100],
            bets_count=str(betting_state.get("total_bets_placed", 0)).zfill(3),
        )
        print(log_line, flush=True)
        old_step, max_steps, restarted = advance_step_after_set_error_func()
        if bet_debug_enabled:
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

    delay = random.uniform(bet_delay_min, bet_delay_max)
    await asyncio.sleep(delay)

    try:
        step_for_history = betting_state.get("current_step", 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15

        if outcome == "double":
            bet_payload = {
                "market": "gtlt",
                "outcome": "double",
                "specifier": "",
                "sum": amount,
                "balance_type": "balance",
            }
            specifier = outcome
        else:
            bet_payload = {
                "market": "value",
                "outcome": outcome,
                "specifier": specifier,
                "sum": amount,
                "balance_type": "balance",
            }

        payload = {"bets": [bet_payload]}
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://betboom.ru/game/nardsgame",
            "Origin": "https://betboom.ru",
            "X-Requested-With": "XMLHttpRequest",
        }
        if jwt_token:
            headers["X-Access-Token"] = jwt_token

        response = await page.request.post(bet_api_url, data=json.dumps(payload), headers=headers)
        status_code = response.status
        response_text = await response.text()

        try:
            response_json = json.loads(response_text)
            if isinstance(response_json, dict) and "code" in response_json:
                status_code = response_json["code"]
        except (json.JSONDecodeError, ValueError):
            pass

        if bet_debug_enabled:
            print("[DEBUG] ========== BET REQUEST ==========>", flush=True)
            print(f"[DEBUG] Page URL: {page.url}", flush=True)
            print(f"[DEBUG] API URL: {bet_api_url}", flush=True)
            print(f"[DEBUG] Payload: {json.dumps(payload)}", flush=True)
            print(f"[DEBUG] Headers sent: {json.dumps({k: v[:50] + '...' if len(str(v)) > 50 else v for k, v in headers.items()})}", flush=True)
            print(f"[DEBUG] Response Status: {status_code}", flush=True)
            print(f"[DEBUG] Response Body: {response_text}", flush=True)
            print("[DEBUG] ==================================", flush=True)
            if status_code != 200:
                print(f"[DEBUG] Статус: {status_code}", flush=True)
                print(f"[DEBUG] Ответ: {response_text[:500]}", flush=True)
                print(f"[DEBUG] Headers: {dict(response.headers)}", flush=True)

        try:
            conn = get_db_connection_func()
            cursor = conn.cursor()
            should_refresh_token = is_forbidden_access_error_func(status_code, response_text)

            if status_code == 200:
                bet_status = "pending"
                betting_state["total_bet_amount"] += amount
                betting_state["total_bets_placed"] += 1
                betting_state["pending_expected_bet_drop"] = amount
                betting_state["last_set_amount"] = amount
                betting_state["last_set_status"] = "pending"
                betting_state["last_set_error"] = None

                payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
                potential_win = amount * payout_coeff
                potential_margin = potential_win - amount
                roi = calculate_roi_func()
                log_line = format_bet_log_func(
                    action="SET",
                    status_icon="✅",
                    outcome=format_outcome_pretty_func(outcome, specifier),
                    amount=f"{amount}р",
                    step=f"{step_for_history+1}/{max_steps}",
                    result="------",
                    profit=f"+{potential_margin:.0f}р",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=get_balance_for_log_func(),
                    bets_count=str(betting_state.get("total_bets_placed", 0)).zfill(3),
                )
                print(log_line, flush=True)
            else:
                bet_status = "error"
                betting_state["last_set_amount"] = amount
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
                                "last_set_amount": amount,
                                "last_set_status": betting_state.get("last_set_status"),
                                "token_refresh_triggered": True,
                            },
                        )
                        cursor.close()
                        conn.close()
                        print("[AUTH] Повторяем ставку один раз после обновления токена.", flush=True)
                        return await place_bet(
                            page,
                            outcome,
                            requested_specifier,
                            amount,
                            allow_refresh_retry=False,
                            betting_state=betting_state,
                            current_strategy=current_strategy,
                            strategy_name=strategy_name,
                            bet_api_url=bet_api_url,
                            jwt_token=get_jwt_token_func(),
                            get_jwt_token_func=get_jwt_token_func,
                            bet_delay_min=bet_delay_min,
                            bet_delay_max=bet_delay_max,
                            bet_debug_enabled=bet_debug_enabled,
                            telegram_notify_bet_errors=telegram_notify_bet_errors,
                            telegram_notify_auth_issues=telegram_notify_auth_issues,
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
                        "[BuyBayBye] Ошибка авторизации ставки",
                        f"403 FORBIDDEN, обновление JWT не помогло.\nСтавка: {format_outcome_pretty_func(outcome, requested_specifier)}\nСумма: {amount:.0f}р",
                        dedup_key="auth_refresh_failed",
                        enabled=telegram_notify_auth_issues,
                    )

                roi = calculate_roi_func()
                log_line = format_bet_log_func(
                    action="SET",
                    status_icon="❌",
                    outcome=format_outcome_pretty_func(outcome, specifier),
                    amount=f"{amount}р",
                    step=f"{step_for_history+1}/{max_steps}",
                    result="ERROR",
                    profit="-",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=get_balance_for_log_func(),
                    error_msg=response_text[:100] if response_text else "Unknown error",
                    bets_count=str(betting_state.get("total_bets_placed", 0)).zfill(3),
                )
                print(log_line, flush=True)
                old_step, max_steps, restarted = advance_step_after_set_error_func()
                if bet_debug_enabled:
                    new_step = betting_state.get("current_step", 0)
                    restart_note = " [♻️ RESTART]" if restarted else ""
                    print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
                if should_refresh_token:
                    betting_state["last_set_error"] = "403 FORBIDDEN -> token refresh failed"

            update_runtime_snapshot_func(
                "bet_set",
                {
                    "last_set_amount": amount,
                    "last_set_status": betting_state.get("last_set_status"),
                    "last_set_error": betting_state.get("last_set_error"),
                    "http_status": status_code,
                    "token_refresh_triggered": should_refresh_token,
                },
            )

            cursor.execute(
                """
                INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (datetime.now(timezone.utc), outcome, specifier, amount, strategy_name, step_for_history, bet_status),
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as exc:
            betting_state["last_set_status"] = "db_error"
            betting_state["last_set_error"] = str(exc)[:100]
            roi = calculate_roi_func()
            log_line = format_bet_log_func(
                action="SET",
                status_icon="❌",
                outcome="-",
                amount="-",
                step="-",
                result="DB_ERROR",
                profit="-",
                roi=f"{roi:.2f}%",
                balance=get_balance_for_log_func(),
                error_msg=str(exc)[:100],
                bets_count=str(betting_state.get("total_bets_placed", 0)).zfill(3),
            )
            print(log_line, flush=True)
            queue_telegram_notification_func(
                "[BuyBayBye] Ошибка сохранения ставки",
                f"Не удалось записать ставку в БД.\nСтавка: {format_outcome_pretty_func(outcome, specifier)}\nСумма: {amount:.0f}р\nОшибка: {str(exc)[:300]}",
                dedup_key="bet_db_error",
                enabled=telegram_notify_bet_errors,
            )
            update_runtime_snapshot_func(
                "bet_db_error",
                {
                    "last_set_status": betting_state.get("last_set_status"),
                    "last_set_error": betting_state.get("last_set_error"),
                },
            )

        return status_code == 200

    except Exception as exc:
        betting_state["last_set_status"] = "request_error"
        betting_state["last_set_error"] = str(exc)[:100]
        roi = calculate_roi_func()
        log_line = format_bet_log_func(
            action="SET",
            status_icon="❌",
            outcome="-",
            amount="-",
            step="-",
            result="ERROR",
            profit="-",
            roi=f"{roi:.2f}%",
            balance=f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=get_balance_for_log_func(),
            error_msg=str(exc)[:100],
            bets_count=str(betting_state.get("total_bets_placed", 0)).zfill(3),
        )
        print(log_line, flush=True)
        queue_telegram_notification_func(
            "[BuyBayBye] Ошибка запроса ставки",
            f"Запрос на размещение ставки завершился ошибкой.\nСтавка: {format_outcome_pretty_func(outcome, requested_specifier)}\nСумма: {amount:.0f}р\nОшибка: {str(exc)[:300]}",
            dedup_key="bet_request_error",
            enabled=telegram_notify_bet_errors,
        )
        old_step, max_steps, restarted = advance_step_after_set_error_func()
        if bet_debug_enabled:
            new_step = betting_state.get("current_step", 0)
            restart_note = " [♻️ RESTART]" if restarted else ""
            print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
        update_runtime_snapshot_func(
            "bet_request_error",
            {
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
            },
        )
        return False


async def process_betting_round(
    page,
    payload: object,
    *,
    betting_state: dict,
    current_strategy: dict | None,
    dynamic_bet_mode: bool,
    bet_debug_enabled: bool,
    format_ws_payload_func,
    get_db_connection_func,
    get_current_bet_target_func,
    set_current_bet_target_func,
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
) -> None:
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

    current_outcome, current_specifier = get_current_bet_target_func()
    matching_dice = None
    is_win = False
    actual_dice_value = None
    dice_colors_appeared = []
    actual_dice_representation = rolled_dice_representation

    if current_outcome == "double":
        dice_values = [d.get("value") for d in dice_results]
        dice_colors_appeared = [d.get("color") for d in dice_results]
        is_double = len(dice_values) == 2 and dice_values[0] == dice_values[1]
        actual_dice_value = dice_values[0] if is_double else None
        is_win = is_double
    else:
        for dice in dice_results:
            if dice.get("color") == current_outcome:
                matching_dice = dice
                break
        dice_colors_appeared = [d.get("color") for d in dice_results]
        target_dice_value = int(current_specifier)
        actual_dice_value = matching_dice.get("value") if matching_dice else None
        is_win = actual_dice_value == target_dice_value

    if betting_state["last_bet_amount"] > 0:
        try:
            conn = get_db_connection_func()
            cursor = conn.cursor()
            current_step_for_log = betting_state["current_step"]

            if is_win:
                status = "win"
                betting_state["consecutive_losses"] = 0
                betting_state["current_step"] = 0
                payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
                bet_amount = betting_state["last_bet_amount"]
                winnings = bet_amount * payout_coeff
                margin = winnings - bet_amount
                betting_state["total_profit"] += margin
                betting_state["session_balance"] += margin
                roi = calculate_roi_func()
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                total_bets = betting_state.get("total_bets_placed", 0)
                log_line = format_bet_log_func(
                    action="RES",
                    status_icon="✅",
                    outcome=format_outcome_pretty_func(current_outcome, current_specifier),
                    amount=f"{bet_amount}р",
                    step=f"{current_step_for_log+1}/{max_steps}",
                    result=actual_dice_representation,
                    profit=f"+{margin:.0f}р",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state['session_balance']:.0f}р",
                    real_balance=get_balance_for_log_func(),
                    bets_count=str(total_bets).zfill(3),
                )
                print(log_line, flush=True)
                if total_bets % 50 == 0:
                    print_session_stats_func(total_bets)
            else:
                status = "loss"
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                bet_amount = betting_state["last_bet_amount"]
                margin = -bet_amount
                betting_state["total_profit"] += margin
                betting_state["session_balance"] += margin
                roi = calculate_roi_func()
                total_bets = betting_state.get("total_bets_placed", 0)

                if betting_state["current_step"] + 1 == max_steps:
                    betting_state["consecutive_losses"] = 0
                    betting_state["current_step"] = 0
                    log_line = format_bet_log_func(
                        action="RES",
                        status_icon="❌",
                        outcome=format_outcome_pretty_func(current_outcome, current_specifier),
                        amount=f"{bet_amount}р",
                        step=f"{max_steps}/{max_steps}",
                        result=actual_dice_representation,
                        profit=f"{margin:.0f}р",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state['session_balance']:.0f}р",
                        real_balance=get_balance_for_log_func(),
                        bets_count=str(total_bets).zfill(3),
                    )
                    print(log_line + " [♻️ RESTART]", flush=True)
                    if total_bets % 50 == 0:
                        print_session_stats_func(total_bets)
                else:
                    betting_state["consecutive_losses"] += 1
                    betting_state["current_step"] = min(betting_state["current_step"] + 1, max_steps - 1)
                    log_line = format_bet_log_func(
                        action="RES",
                        status_icon="❌",
                        outcome=format_outcome_pretty_func(current_outcome, current_specifier),
                        amount=f"{bet_amount}р",
                        step=f"{current_step_for_log+1}/{max_steps}",
                        result=actual_dice_representation,
                        profit=f"{margin:.0f}р",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state['session_balance']:.0f}р",
                        real_balance=get_balance_for_log_func(),
                        bets_count=str(total_bets).zfill(3),
                    )
                    print(log_line, flush=True)
                    if total_bets % 50 == 0:
                        print_session_stats_func(total_bets)

            total_bets_now = betting_state.get("total_bets_placed", 0)
            if total_bets_now > 0 and total_bets_now % 20 == 0:
                print_dice_stats_20_func()

            stored_dice_color = dice_colors_appeared[0] if dice_colors_appeared else "unknown"
            if current_outcome == "double":
                stored_dice_color = "double"

            cursor.execute(
                """
                UPDATE bet_history
                SET status = %s, result_dice_color = %s, result_dice_value = %s
                WHERE id = (SELECT MAX(id) FROM bet_history)
                """,
                (status, stored_dice_color, actual_dice_value),
            )
            conn.commit()
            cursor.close()
            conn.close()
            update_runtime_snapshot_func(
                "bet_result",
                {
                    "bet_result_status": status,
                    "bet_result_value": actual_dice_value,
                    "bet_result_display": actual_dice_representation,
                },
            )
        except Exception as exc:
            print(f"[DB ERROR] Ошибка обновления результата ставки: {exc}", flush=True)

    if bet_debug_enabled:
        print(f"[DEBUG PROCESS] DYNAMIC_BET_MODE={dynamic_bet_mode}, calling _update_dynamic_bet", flush=True)
    if dynamic_bet_mode:
        if bet_debug_enabled:
            print("[DEBUG PROCESS] Entering if DYNAMIC_BET_MODE, calling function", flush=True)
        update_dynamic_bet_func()
        current_outcome, current_specifier = get_current_bet_target_func()

    consecutive_losses = betting_state.get("consecutive_losses", 0)
    if consecutive_losses >= 15:
        print("", flush=True)
        new_outcome, new_specifier = generate_random_bet_func()
        set_current_bet_target_func(new_outcome, new_specifier)
        betting_state["consecutive_losses"] = 0
        print("", flush=True)
        current_outcome, current_specifier = get_current_bet_target_func()

    bet_amount = calculate_bet_amount_func()
    if bet_debug_enabled:
        print(f"[DEBUG PROCESS_BET] Вызов _place_bet с outcome={current_outcome}, specifier={current_specifier}", flush=True)
    await place_bet_func(page, current_outcome, current_specifier, bet_amount)