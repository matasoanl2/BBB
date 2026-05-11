"""Вспомогательные функции для размещения ставок и обработки результатов раундов."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import BetTarget, RuntimeConfig


BETTING_BALANCE_EPSILON = 0.009
WIN_PENDING_CONFIRMATION_STATUS = "win_pending_confirmation"
FALSE_WIN_STATUS = "false_win"
PENDING_WIN_CONFIRMATION_WAIT_SECONDS = 0.2
PENDING_WIN_CONFIRMATION_POLL_SECONDS = 0.02
PENDING_WIN_CONFIRMATION_SET_FALLBACK_CHECKS_KEY = "pending_win_confirmation_set_fallback_checks_remaining"


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
    deposit_balance: str = "",
    error_msg: str = "",
    bets_count: str = "",
    color_reset: str,
    color_yellow: str,
    color_green: str,
    color_red: str,
    color_magenta: str,
    color_cyan: str,
    plain_text_output_enabled: bool,
    json_one_line_output_enabled: bool,
    pad_width_center_func,
    format_result_pretty_func,
) -> str:
    """Собрать форматированную строку лога для SET/RES событий ставки."""

    now_local = datetime.now()
    time_str = now_local.strftime("%H:%M:%S")

    if json_one_line_output_enabled:
        status_text = {"✅": "ok", "❌": "fail"}.get(status_icon, status_icon)
        timestamp_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        payload = {
            "log_type": "bet_event",
            "schema_version": 1,
            "ts": timestamp_utc,
            "time": time_str,
            "action": action,
            "status": status_text,
            "round": bets_count or "-",
            "step": step,
            "target": outcome,
            "amount": amount,
            "result": result,
            "profit": profit,
            "roi": roi,
            "deposit_balance": balance if deposit_balance else None,
            "real_balance": real_balance,
            "total_balance": f"{deposit_value + real_value:.0f}р" if deposit_balance else None,
        }
        if error_msg:
            payload["error"] = error_msg
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    if plain_text_output_enabled:
        status_text = {"✅": "ok", "❌": "fail"}.get(status_icon, status_icon)
        fields = [
            f"time={time_str}",
            f"action={action}",
            f"status={status_text}",
            f"round={bets_count or '-'}",
            f"step={step}",
            f"target={outcome}",
            f"amount={amount}",
            f"result={result}",
            f"profit={profit}",
            f"roi={roi}",
            f"deposit_balance={balance}" if deposit_balance else f"session_balance={balance}",
            f"real_balance={real_balance}",
        ]
        if deposit_balance:
            try:
                total = deposit_value + real_value
                fields.append(f"total_balance={total:.0f}р")
            except:
                pass
        if error_msg:
            fields.append(f"error={error_msg}")
        return " | ".join(fields)

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

    if deposit_balance:
        # Deposit mode: balance column shows deposit_balance, real_balance column shows saved_real_balance, add total
        try:
            deposit_value = float(deposit_balance.replace("р", "").strip())
            if deposit_value > 0:
                balance_colored = f"{color_green}🧰 {deposit_balance}{reset_full}"
            elif deposit_value < 0:
                balance_colored = f"{color_red}🧰 {deposit_balance}{reset_full}"
            else:
                balance_colored = f"🧰 {deposit_balance}"
        except (ValueError, AttributeError):
            balance_colored = f"🧰 {deposit_balance}"

        try:
            real_value = float(real_balance.replace("р", "").strip())
            if real_value > 0:
                real_balance_colored = f"{color_cyan}💰 {real_balance}{reset_full}"
            elif real_value < 0:
                real_balance_colored = f"{color_red}💰 {real_balance}{reset_full}"
            else:
                real_balance_colored = f"💰 {real_balance}"
        except (ValueError, AttributeError):
            real_balance_colored = f"💰 {real_balance}"

        # Calculate total
        try:
            total_value = deposit_value + real_value
            total_str = f"{total_value:.0f}р"
            if total_value > 0:
                total_colored = f"{color_green}📊 {total_str}{reset_full}"
            elif total_value < 0:
                total_colored = f"{color_red}📊 {total_str}{reset_full}"
            else:
                total_colored = f"📊 {total_str}"
        except:
            total_colored = "📊 -"
    else:
        # Normal mode: balance column shows session_balance, real_balance column shows accounting balance
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

        total_colored = ""  # No total in normal mode

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
    if deposit_balance:
        log_parts.append(pad_width_center_func(total_colored, 12))

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


def _resolve_target_tokens(tokens: list[str] | tuple[str, ...]) -> tuple[BetTarget, ...]:
    resolved_targets: list[BetTarget] = []
    for token in tokens:
        token_text = str(token).strip().upper()
        if token_text == "D":
            resolved_targets.append(BetTarget(outcome="double", specifier=""))
            continue
        if len(token_text) == 2 and token_text[0] in {"R", "Y"} and token_text[1] in {"1", "2", "3", "4", "5", "6"}:
            resolved_targets.append(
                BetTarget(
                    outcome="red" if token_text[0] == "R" else "yellow",
                    specifier=token_text[1],
                )
            )
    return tuple(resolved_targets)


def _normalize_account_balance(raw_balance) -> float | None:
    try:
        if raw_balance is None:
            return None
        return float(raw_balance)
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _refresh_reconciliation_phase(betting_state: dict) -> None:
    pending_expected_bet_drop = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0)
    pending_expected_settlement_credit = float(betting_state.get("pending_expected_settlement_credit", 0.0) or 0.0)

    if pending_expected_bet_drop > BETTING_BALANCE_EPSILON:
        betting_state["reconciliation_phase"] = "awaiting_bet_drop"
    elif pending_expected_settlement_credit > BETTING_BALANCE_EPSILON:
        betting_state["reconciliation_phase"] = "awaiting_settlement"
    else:
        betting_state["reconciliation_phase"] = "idle"


def _pending_win_confirmation_is_enabled(runtime_config: RuntimeConfig) -> bool:
    return bool(getattr(runtime_config.betting, "pending_win_confirmation_enabled", True))


def _get_pending_win_confirmation_outcome(betting_state: dict) -> str:
    pending_confirmation = betting_state.get("pending_win_confirmation")
    if not isinstance(pending_confirmation, dict) or not pending_confirmation:
        return "none"

    expected_settlement_credit = float(pending_confirmation.get("expected_settlement_credit", 0.0) or 0.0)
    if expected_settlement_credit <= BETTING_BALANCE_EPSILON:
        return "confirmed"

    remaining_settlement_credit = float(betting_state.get("pending_expected_settlement_credit", 0.0) or 0.0)
    if remaining_settlement_credit + BETTING_BALANCE_EPSILON < expected_settlement_credit:
        return "confirmed"

    if _normalize_account_balance(betting_state.get("account_balance")) is None:
        return "pending"

    confirmed_at = _parse_iso_datetime(pending_confirmation.get("recorded_at"))
    account_balance_updated_at = _parse_iso_datetime(betting_state.get("account_balance_updated_at"))
    if confirmed_at is None or account_balance_updated_at is None or account_balance_updated_at <= confirmed_at:
        return "pending"

    if account_balance_updated_at > confirmed_at:
        return FALSE_WIN_STATUS

    return "pending"


def _finalize_pending_win_confirmation_if_ready(
    *,
    betting_state: dict,
    runtime_config: RuntimeConfig,
    get_db_connection_func,
    update_runtime_snapshot_func,
    slot_label: str,
) -> str:
    if not _pending_win_confirmation_is_enabled(runtime_config):
        pending_confirmation = betting_state.get("pending_win_confirmation") or {}
        if isinstance(pending_confirmation, dict):
            betting_state["pending_win_confirmation"] = None
            betting_state["pending_expected_settlement_credit"] = 0.0
            betting_state["reconciliation_phase"] = "idle"
        return "confirmed"

    confirmation_outcome = _get_pending_win_confirmation_outcome(betting_state)
    if confirmation_outcome not in {"confirmed", FALSE_WIN_STATUS}:
        return confirmation_outcome

    pending_confirmation = betting_state.get("pending_win_confirmation") or {}
    history_ids = [history_id for history_id in pending_confirmation.get("history_ids", []) if history_id is not None]
    final_status = "win" if confirmation_outcome == "confirmed" else FALSE_WIN_STATUS

    conn = None
    cursor = None
    try:
        conn = get_db_connection_func()
        cursor = conn.cursor()
        for history_id in history_ids:
            cursor.execute(
                """
                UPDATE bet_history
                SET status = %s
                WHERE id = %s
                """,
                (final_status, history_id),
            )
        conn.commit()
    except Exception as exc:
        print(f"[DB ERROR] Ошибка финализации статуса ставки: {exc}", flush=True)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    if confirmation_outcome == "confirmed":
        round_margin = float(pending_confirmation.get("round_margin", 0.0) or 0.0)
        betting_state["total_profit"] += round_margin
        betting_state["session_balance"] += round_margin
        betting_state["current_step"] = 0
        betting_state["consecutive_losses"] = 0
        betting_state["last_set_status"] = "win"
    else:
        round_margin = float(pending_confirmation.get("round_margin", 0.0) or 0.0)
        expected_settlement_credit = float(pending_confirmation.get("expected_settlement_credit", 0.0) or 0.0)
        remaining_settlement_credit = float(betting_state.get("pending_expected_settlement_credit", 0.0) or 0.0)
        false_round_margin = round_margin - expected_settlement_credit
        current_step_before_resolution = int(
            pending_confirmation.get("current_step_before_resolution", betting_state.get("current_step", 0)) or 0
        )
        consecutive_losses_before_resolution = int(
            pending_confirmation.get(
                "consecutive_losses_before_resolution",
                betting_state.get("consecutive_losses", 0),
            )
            or 0
        )
        max_steps = int(pending_confirmation.get("max_steps", 1) or 1)

        betting_state["pending_expected_settlement_credit"] = max(0.0, remaining_settlement_credit - expected_settlement_credit)
        betting_state["total_profit"] += false_round_margin
        betting_state["session_balance"] += false_round_margin
        if current_step_before_resolution + 1 >= max_steps:
            betting_state["current_step"] = 0
            betting_state["consecutive_losses"] = 0
        else:
            betting_state["current_step"] = current_step_before_resolution + 1
            betting_state["consecutive_losses"] = consecutive_losses_before_resolution + 1
        betting_state["last_set_status"] = FALSE_WIN_STATUS

    _refresh_reconciliation_phase(betting_state)
    betting_state["pending_win_confirmation"] = None
    update_runtime_snapshot_func(
        "bet_result_confirmation",
        {
            "slot": slot_label,
            "bet_result_status": final_status,
            "requested_targets": list(pending_confirmation.get("resolved_target_tokens", [])),
            "effective_targets": list(pending_confirmation.get("resolved_target_tokens", [])),
            "bet_result_display": pending_confirmation.get("result_display"),
        },
    )
    return confirmation_outcome


def _run_pending_win_confirmation_precheck(
    *,
    betting_state: dict,
    runtime_config: RuntimeConfig,
    get_db_connection_func,
    update_runtime_snapshot_func,
    slot_label: str,
) -> bool:
    confirmation_outcome = _finalize_pending_win_confirmation_if_ready(
        betting_state=betting_state,
        runtime_config=runtime_config,
        get_db_connection_func=get_db_connection_func,
        update_runtime_snapshot_func=update_runtime_snapshot_func,
        slot_label=slot_label,
    )
    if confirmation_outcome == "pending":
        pending_confirmation = betting_state.get("pending_win_confirmation") or {}
        fallback_checks_remaining = int(pending_confirmation.get(PENDING_WIN_CONFIRMATION_SET_FALLBACK_CHECKS_KEY, 0) or 0)
        if fallback_checks_remaining > 0:
            pending_confirmation[PENDING_WIN_CONFIRMATION_SET_FALLBACK_CHECKS_KEY] = fallback_checks_remaining - 1
            return True
    return confirmation_outcome != "pending"


def _finalize_pending_win_confirmation_for_set_calculation_if_ready(
    *,
    betting_state: dict,
    runtime_config: RuntimeConfig,
    get_db_connection_func,
    update_runtime_snapshot_func,
    slot_label: str,
) -> None:
    pending_confirmation = betting_state.get("pending_win_confirmation")
    if not isinstance(pending_confirmation, dict) or not pending_confirmation:
        return

    _finalize_pending_win_confirmation_if_ready(
        betting_state=betting_state,
        runtime_config=runtime_config,
        get_db_connection_func=get_db_connection_func,
        update_runtime_snapshot_func=update_runtime_snapshot_func,
        slot_label=slot_label,
    )


def _set_pending_win_confirmation_set_fallback_checks(betting_state: dict, checks_remaining: int) -> None:
    pending_confirmation = betting_state.get("pending_win_confirmation")
    if isinstance(pending_confirmation, dict) and pending_confirmation:
        pending_confirmation[PENDING_WIN_CONFIRMATION_SET_FALLBACK_CHECKS_KEY] = max(0, int(checks_remaining or 0))


def _clear_pending_win_confirmation_set_fallback_checks(betting_state: dict) -> None:
    pending_confirmation = betting_state.get("pending_win_confirmation")
    if isinstance(pending_confirmation, dict) and pending_confirmation:
        pending_confirmation.pop(PENDING_WIN_CONFIRMATION_SET_FALLBACK_CHECKS_KEY, None)


async def _wait_briefly_for_pending_win_confirmation(
    *,
    betting_state: dict,
    runtime_config: RuntimeConfig,
    get_db_connection_func,
    update_runtime_snapshot_func,
    slot_label: str,
) -> str:
    confirmation_outcome = _finalize_pending_win_confirmation_if_ready(
        betting_state=betting_state,
        runtime_config=runtime_config,
        get_db_connection_func=get_db_connection_func,
        update_runtime_snapshot_func=update_runtime_snapshot_func,
        slot_label=slot_label,
    )
    if confirmation_outcome != "pending":
        return confirmation_outcome

    event_loop = asyncio.get_running_loop()
    deadline = event_loop.time() + PENDING_WIN_CONFIRMATION_WAIT_SECONDS
    while True:
        remaining_seconds = deadline - event_loop.time()
        if remaining_seconds <= 0:
            return "pending"

        await asyncio.sleep(min(PENDING_WIN_CONFIRMATION_POLL_SECONDS, remaining_seconds))
        confirmation_outcome = _finalize_pending_win_confirmation_if_ready(
            betting_state=betting_state,
            runtime_config=runtime_config,
            get_db_connection_func=get_db_connection_func,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            slot_label=slot_label,
        )
        if confirmation_outcome != "pending":
            return confirmation_outcome


def _has_fresh_accounting_update_after_api_fail(betting_state: dict) -> bool:
    api_fail_at = _parse_iso_datetime(betting_state.get("low_balance_api_fail_at"))
    if api_fail_at is None:
        return False

    account_balance_updated_at = _parse_iso_datetime(betting_state.get("account_balance_updated_at"))
    if account_balance_updated_at is None:
        return False

    return account_balance_updated_at > api_fail_at


def _clear_low_balance_pause_state(betting_state: dict) -> None:
    betting_state["low_balance_pause_active"] = False
    betting_state["low_balance_pause_required_balance"] = 0.0
    betting_state["low_balance_pause_reason"] = None
    betting_state["low_balance_pause_started_at"] = None
    betting_state["low_balance_pause_targets"] = []
    betting_state["target_balance_pause_last_check_at"] = None
    betting_state["target_balance_pause_last_observed_balance"] = None
    betting_state["low_balance_api_fail_at"] = None


def _set_low_balance_pause_state(
    betting_state: dict,
    *,
    amount: float,
    bet_targets: tuple[BetTarget, ...],
    reason: str,
) -> bool:
    target_tokens = [target.token for target in bet_targets]
    state_changed = (
        not betting_state.get("low_balance_pause_active")
        or float(betting_state.get("low_balance_pause_required_balance", 0.0) or 0.0) != float(amount)
        or str(betting_state.get("low_balance_pause_reason") or "") != str(reason)
        or list(betting_state.get("low_balance_pause_targets") or []) != target_tokens
    )
    betting_state["low_balance_pause_active"] = True
    betting_state["low_balance_pause_required_balance"] = float(amount)
    betting_state["low_balance_pause_reason"] = str(reason)
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


def _print_bet_system_log(
    *,
    runtime_config: RuntimeConfig,
    event: str,
    message: str,
    level: str = "info",
    extra: dict | None = None,
) -> None:
    if runtime_config.logging.terminal_json_logs:
        payload = {
            "log_type": "bet_system",
            "schema_version": 1,
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "level": level,
            "event": event,
            "message": message,
        }
        if extra:
            payload.update(extra)
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
        return

    print(message, flush=True)


def _run_set_precheck_for_slot(
    *,
    betting_state: dict,
    current_strategy: dict,
    amount: float,
    bet_targets: tuple[BetTarget, ...],
    requested_targets: tuple[BetTarget, ...],
    slot_label: str,
    step_for_history: int,
    max_steps: int,
    next_round_display: str,
    runtime_config: RuntimeConfig,
    calculate_roi_func,
    format_outcome_pretty_func,
    format_bet_log_func,
    get_balance_for_log_func,
    get_db_connection_func,
    update_runtime_snapshot_func,
    required_bank_base_bet: float,
    resume_base_bet: float,
    available_balance_override: float | None = None,
) -> tuple[bool, tuple[BetTarget, ...], float]:
    betting_config = runtime_config.betting
    normalized_targets = tuple(bet_targets)
    if not normalized_targets:
        return False, (), amount

    if not _run_pending_win_confirmation_precheck(
        betting_state=betting_state,
        runtime_config=runtime_config,
        get_db_connection_func=get_db_connection_func,
        update_runtime_snapshot_func=update_runtime_snapshot_func,
        slot_label=slot_label,
    ):
        return False, (), amount

    _slot_prefix = f"[{slot_label or '1'}]"
    targets_display = _slot_prefix + _format_bet_targets_pretty(normalized_targets, format_outcome_pretty_func)
    total_round_amount = amount * len(normalized_targets)
    available_balance = _normalize_account_balance(betting_state.get("account_balance"))
    if runtime_config.accounting.deposit_mode_enabled:
        deposit_balance = _normalize_account_balance(betting_state.get("deposit_balance"))
        available_balance = deposit_balance

        # Auto-replenish deposit if insufficient for at least one bet
        if available_balance < amount:
            saved_real_balance = betting_state.get("saved_real_balance", 0.0)
            base_deposit = runtime_config.accounting.base_deposit
            if saved_real_balance >= base_deposit:
                deposit_balance += base_deposit
                saved_real_balance -= base_deposit
                available_balance = deposit_balance
                betting_state["saved_real_balance"] = saved_real_balance
                betting_state["deposit_balance"] = deposit_balance
                if betting_config.debug_enabled:
                    print(f"[DEPOSIT] Автопополнение: +{base_deposit}р на deposit, saved_real={saved_real_balance:.0f}р, deposit={deposit_balance:.0f}р", flush=True)

    was_low_balance_paused = bool(betting_state.get("low_balance_pause_active"))
    stop_at_balance = float(getattr(betting_config, "stop_at_balance", 0.0) or 0.0)
    stop_at_balance_resume_check_seconds = float(
        getattr(betting_config, "stop_at_balance_resume_check_seconds", 300.0) or 300.0
    )

    if str(betting_state.get("low_balance_pause_reason") or "") == "target_balance_reached":
        now_utc = datetime.now(timezone.utc)
        last_check_raw = betting_state.get("target_balance_pause_last_check_at")
        last_observed_balance = _normalize_account_balance(
            betting_state.get("target_balance_pause_last_observed_balance")
        )
        if last_observed_balance is None and available_balance is not None:
            last_observed_balance = available_balance

        check_due = True
        if isinstance(last_check_raw, str) and last_check_raw:
            try:
                last_check_at = datetime.fromisoformat(last_check_raw)
                check_due = (now_utc - last_check_at).total_seconds() >= stop_at_balance_resume_check_seconds
            except ValueError:
                check_due = True

        if not check_due:
            if (
                available_balance is not None
                and last_observed_balance is not None
                and available_balance < last_observed_balance
            ) or betting_state.get("last_external_balance_change_type") == "withdrawal":
                check_due = True

        if not check_due:
            return False, (), amount

        betting_state["target_balance_pause_last_check_at"] = now_utc.isoformat()

        if available_balance is None:
            return False, (), amount

        if last_observed_balance is not None and available_balance < last_observed_balance:
            _clear_low_balance_pause_state(betting_state)
            betting_state["current_step"] = 0
            betting_state["last_set_status"] = "resumed_after_target_balance_drop"
            betting_state["last_set_error"] = (
                f"Возобновление: real balance снизился {last_observed_balance:.0f}р -> {available_balance:.0f}р, продолжаем с шага 1"
            )
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="set_resume_after_target_balance_drop",
                level="info",
                message="[SET-RESUME] После снижения real balance возобновляем ставки с первого шага.",
                extra={
                    "previous_balance": last_observed_balance,
                    "current_balance": available_balance,
                    "check_interval_seconds": stop_at_balance_resume_check_seconds,
                    "slot": slot_label or "1",
                },
            )
        else:
            betting_state["target_balance_pause_last_observed_balance"] = available_balance
            betting_state["last_set_status"] = "paused_target_balance"
            betting_state["last_set_error"] = (
                f"Пауза: real balance {available_balance:.0f}р не снизился; повторная проверка через {int(stop_at_balance_resume_check_seconds // 60)} мин"
            )
            return False, (), amount

    if stop_at_balance > 0 and available_balance is not None and available_balance >= stop_at_balance:
        pause_changed = _set_low_balance_pause_state(
            betting_state,
            amount=stop_at_balance,
            bet_targets=normalized_targets,
            reason="target_balance_reached",
        )
        now_utc = datetime.now(timezone.utc)
        betting_state["target_balance_pause_last_check_at"] = now_utc.isoformat()
        betting_state["target_balance_pause_last_observed_balance"] = available_balance
        betting_state["last_bet_amount"] = 0.0
        betting_state["last_set_amount"] = 0.0
        betting_state["last_set_status"] = "paused_target_balance"
        betting_state["last_set_error"] = (
            f"Пауза: достигнут целевой баланс {available_balance:.0f}р (лимит {stop_at_balance:.0f}р)"
        )
        if pause_changed:
            roi = calculate_roi_func()
            log_line = format_bet_log_func(
                action="SET",
                status_icon="✅",
                outcome=targets_display,
                amount=f"{total_round_amount:.0f}р",
                step=f"{step_for_history+1}/{max_steps}",
                result="STOP",
                profit="-",
                roi=f"{roi:.2f}%",
                balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                error_msg=betting_state["last_set_error"],
                bets_count=next_round_display,
            )
            print(log_line, flush=True)
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="set_stop_target_balance",
                level="info",
                message="[SET-STOP] Достигнут целевой real balance, автоставки остановлены.",
                extra={
                    "account_balance": available_balance,
                    "stop_at_balance": stop_at_balance,
                    "slot": slot_label or "1",
                },
            )
            update_runtime_snapshot_func(
                "bet_target_balance_pause",
                {
                    "last_set_status": betting_state.get("last_set_status"),
                    "last_set_error": betting_state.get("last_set_error"),
                    "account_balance": available_balance,
                    "stop_at_balance": stop_at_balance,
                    "requested_targets": [target.token for target in requested_targets],
                    "effective_targets": [],
                    "low_balance_pause_active": True,
                    "low_balance_pause_required_balance": stop_at_balance,
                    "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                    "slot": slot_label or "1",
                },
            )
        return False, (), amount

    required_bank_units = int(
        (current_strategy or {}).get(
            "required_bank_base_bet_units",
            sum((current_strategy or {}).get("coefficients", [1])),
        )
    )
    required_bank_amount = float(required_bank_units) * float(required_bank_base_bet) * float(len(normalized_targets))
    is_first_strategy_step = int(betting_state.get("total_bet_rounds", 0) or 0) == 0 and int(step_for_history or 0) == 0
    check_required_bank_on_first_step = bool(
        getattr(betting_config, "check_required_bank_on_first_step", True)
    )

    if is_first_strategy_step and check_required_bank_on_first_step:
        if available_balance is None:
            pause_changed = _set_low_balance_pause_state(
                betting_state,
                amount=required_bank_amount,
                bet_targets=normalized_targets,
                reason="required_bank_waiting_balance",
            )
            betting_state["last_bet_amount"] = 0.0
            betting_state["last_set_amount"] = 0.0
            betting_state["last_set_status"] = "paused_required_bank_balance_unknown"
            betting_state["last_set_error"] = (
                "Пауза перед первым шагом: waiting balance update из accounting_ws для проверки required bank"
            )
            if pause_changed:
                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_pause_waiting_required_bank_balance",
                    level="warning",
                    message="[SET-PAUSE] Первый шаг стратегии будет размещен после получения real balance из accounting_ws.",
                    extra={
                        "required_bank_amount": required_bank_amount,
                        "required_bank_base_bet_units": required_bank_units,
                        "slot": slot_label or "1",
                    },
                )
                update_runtime_snapshot_func(
                    "bet_required_bank_wait_balance",
                    {
                        "last_set_status": betting_state.get("last_set_status"),
                        "last_set_error": betting_state.get("last_set_error"),
                        "required_bank_amount": required_bank_amount,
                        "required_bank_base_bet_units": required_bank_units,
                        "requested_targets": [target.token for target in requested_targets],
                        "effective_targets": [],
                        "low_balance_pause_active": True,
                        "low_balance_pause_required_balance": required_bank_amount,
                        "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                        "slot": slot_label or "1",
                    },
                )
            return False, (), amount

        if available_balance < required_bank_amount:
            pause_changed = _set_low_balance_pause_state(
                betting_state,
                amount=required_bank_amount,
                bet_targets=normalized_targets,
                reason="required_bank_insufficient",
            )
            betting_state["last_bet_amount"] = 0.0
            betting_state["last_set_amount"] = 0.0
            betting_state["last_set_status"] = "paused_required_bank"
            betting_state["last_set_error"] = (
                f"Пауза перед первым шагом: баланс {available_balance:.0f}р меньше required bank {required_bank_amount:.0f}р"
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
                    balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                    error_msg=betting_state["last_set_error"],
                    bets_count=next_round_display,
                )
                print(log_line, flush=True)
                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_pause_required_bank_insufficient",
                    level="warning",
                    message="[SET-PAUSE] Для старта стратегии требуется полный банк цикла.",
                    extra={
                        "account_balance": available_balance,
                        "required_bank_amount": required_bank_amount,
                        "required_bank_base_bet_units": required_bank_units,
                        "slot": slot_label or "1",
                    },
                )
                update_runtime_snapshot_func(
                    "bet_required_bank_pause",
                    {
                        "last_set_status": betting_state.get("last_set_status"),
                        "last_set_error": betting_state.get("last_set_error"),
                        "account_balance": available_balance,
                        "required_bank_amount": required_bank_amount,
                        "required_bank_base_bet_units": required_bank_units,
                        "requested_targets": [target.token for target in requested_targets],
                        "effective_targets": [],
                        "low_balance_pause_active": True,
                        "low_balance_pause_required_balance": required_bank_amount,
                        "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                        "slot": slot_label or "1",
                    },
                )
            return False, (), amount

    effective_balance = available_balance
    # In deposit mode, don't apply available_balance_override (percent limit) since it's already calculated from deposit_balance
    # For percent check, always use available_balance directly (which is deposit_balance in deposit mode)
    if available_balance_override is not None and not runtime_config.accounting.deposit_mode_enabled:
        effective_balance = (
            available_balance_override
            if available_balance is None
            else min(available_balance, available_balance_override)
        )

    max_stake_percent_of_bank = float(getattr(betting_config, "max_stake_percent_of_bank", 0.0) or 0.0)
    if max_stake_percent_of_bank > 0 and effective_balance is not None and required_bank_units > 5:
        max_allowed_amount = effective_balance * (max_stake_percent_of_bank / 100.0)
        if amount > max_allowed_amount + 1e-9:
            coefficients = (current_strategy or {}).get("coefficients", [1])
            first_coefficient = float(coefficients[0]) if coefficients else 1.0
            reset_base_amount = float(resume_base_bet if resume_base_bet > 0 else required_bank_base_bet)
            reset_amount = reset_base_amount * first_coefficient if reset_base_amount > 0 else amount
            previous_amount = amount
            previous_step_for_history = int(step_for_history or 0)

            amount = reset_amount
            betting_state["current_step"] = 0
            step_for_history = 0
            total_round_amount = amount * len(normalized_targets)

            _print_bet_system_log(
                runtime_config=runtime_config,
                event="set_step_reset_by_percent_limit",
                level="info",
                message=(
                    "[SET-CHECK] Ставка превысила лимит доли банка; "
                    "сбрасываем шаг на 1 и пересчитываем сумму ставки."
                ),
                extra={
                    "slot": slot_label or "1",
                    "account_balance": available_balance,
                    "max_stake_percent_of_bank": max_stake_percent_of_bank,
                    "required_bank_base_bet_units": required_bank_units,
                    "max_allowed_amount": max_allowed_amount,
                    "previous_amount": previous_amount,
                    "reset_amount": amount,
                    "previous_step_for_history": previous_step_for_history,
                    "step_for_history": step_for_history,
                },
            )

    if effective_balance is None:
        if was_low_balance_paused:
            return False, (), amount
        if betting_config.debug_enabled and betting_state.get("total_bets_placed", 0) == 0:
            print("[SET-CHECK] Баланс из accounting_ws пока неизвестен, первую batch-ставку пропускаем без проверки лимита.", flush=True)
        return True, normalized_targets, amount

    affordable_targets = _get_affordable_bet_targets(
        bet_targets=normalized_targets,
        amount=amount,
        available_balance=effective_balance,
    )
    if not affordable_targets:
        pause_changed = _set_low_balance_pause_state(
            betting_state,
            amount=amount,
            bet_targets=normalized_targets,
            reason="min_bet_insufficient",
        )
        betting_state["last_bet_amount"] = 0.0
        betting_state["last_set_amount"] = total_round_amount
        betting_state["last_set_status"] = "paused_low_balance"
        # Безопасно форматируем effective_balance (может быть None)
        balance_val = effective_balance if effective_balance is not None else 0.0
        betting_state["last_set_error"] = (
            f"Пауза: баланс {balance_val:.0f}р меньше минимальной ставки {amount:.0f}р на одну цель"
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
                balance=f"{balance_val:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                deposit_balance=f"{balance_val:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                error_msg=betting_state["last_set_error"],
                bets_count=next_round_display,
            )
            print(log_line, flush=True)
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="set_pause_low_balance",
                level="warning",
                message="[SET-PAUSE] Возобновим ставки автоматически после восстановления real balance.",
                extra={
                    "account_balance": balance_val,
                    "required_min_bet": amount,
                    "slot": slot_label or "1",
                },
            )
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
                    "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                    "slot": slot_label or "1",
                },
            )
        return False, (), amount

    if was_low_balance_paused:
        _api_fail_pause_reason = str(betting_state.get("low_balance_pause_reason") or "")
        if _api_fail_pause_reason == "api_insufficient_balance" and not _has_fresh_accounting_update_after_api_fail(
            betting_state
        ):
            return False, (), amount
        _clear_low_balance_pause_state(betting_state)
        betting_state["current_step"] = 0
        betting_state["consecutive_losses"] = 0
        balance_val = effective_balance if effective_balance is not None else 0.0
        if resume_base_bet > 0 and amount != resume_base_bet:
            amount = resume_base_bet
            affordable_targets = _get_affordable_bet_targets(
                bet_targets=normalized_targets,
                amount=amount,
                available_balance=balance_val,
            )
            if not affordable_targets:
                return False, (), amount
        # SUPPRESSION: логируем [SET-RESUME] только если баланс изменился
        last_resume_balance = betting_state.get("_last_resume_log_balance")
        if last_resume_balance != balance_val:
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="set_resume_low_balance",
                level="info",
                message=f"[SET-RESUME] Real balance восстановлен до {balance_val:.0f}р, продолжаем размещение ставок.",
                extra={
                    "account_balance": balance_val,
                    "slot": slot_label or "1",
                },
            )
            betting_state["_last_resume_log_balance"] = balance_val
        update_runtime_snapshot_func(
            "bet_low_balance_resume",
            {
                "account_balance": balance_val,
                "requested_targets": [target.token for target in requested_targets],
                "effective_targets": [target.token for target in affordable_targets],
                "low_balance_pause_active": False,
                "slot": slot_label or "1",
            },
        )

    if len(affordable_targets) < len(normalized_targets):
        # SUPPRESSION: логируем только если изменилось число affordable_targets
        last_affordable_count = betting_state.get("_last_affordable_targets_count")
        if last_affordable_count != len(affordable_targets):
            print(
                "[SET-CHECK] Недостаточно real balance для полного batch, "
                f"размещаем {len(affordable_targets)}/{len(normalized_targets)} целей.",
                flush=True,
            )
            betting_state["_last_affordable_targets_count"] = len(affordable_targets)

    return True, affordable_targets, amount


async def place_bets(
    page,
    bet_targets,
    amount: float,
    *,
    allow_refresh_retry: bool = True,
    slot_label: str = "",
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
    _slot_prefix = f"[{slot_label or '1'}]"
    targets_display = _slot_prefix + _format_bet_targets_pretty(normalized_targets, format_outcome_pretty_func)
    total_round_amount = amount * len(normalized_targets)
    next_round_number = int(betting_state.get("total_bet_rounds", 0) or 0) + 1
    next_round_display = str(next_round_number).zfill(3)
    slot_number = 2 if slot_label == "2" else 1

    if not normalized_targets:
        print("[WARNING] Не передано ни одной цели ставки для текущего раунда.", flush=True)
        return False

    if not jwt_token:
        print("[WARNING] JWT токен ещё не найден! Ставки НЕ будут размещены.", flush=True)
        advance_step_after_set_error_func()
        return False

    if betting_config.debug_enabled:
        slot_suffix = f" [слот {slot_label}]" if slot_label else ""
        print(
            f"[DEBUG PLACE_BETS{slot_suffix}] targets={[target.token for target in normalized_targets]}, amount_per_target={amount}, total={total_round_amount}",
            flush=True,
        )

    if not validate_base_bet_func(amount):
        print(f"[ERROR] Ставка {amount}р ДОЛЖНА делиться на 10 нацело! Ставки НЕ размещены.", flush=True)
        advance_step_after_set_error_func()
        return False

    try:
        if not _run_pending_win_confirmation_precheck(
            betting_state=betting_state,
            runtime_config=runtime_config,
            get_db_connection_func=get_db_connection_func,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            slot_label=slot_label,
        ):
            return False, (), amount

        step_for_history = betting_state.get("current_step", 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
        available_balance = _normalize_account_balance(betting_state.get("account_balance"))
        if runtime_config.accounting.deposit_mode_enabled:
            deposit_balance = _normalize_account_balance(betting_state.get("deposit_balance"))
            available_balance = deposit_balance

            # Auto-replenish deposit if insufficient and real balance allows
            if available_balance < total_round_amount:
                saved_real_balance = betting_state.get("saved_real_balance", 0.0)
                base_deposit = runtime_config.accounting.base_deposit
                if saved_real_balance >= base_deposit:
                    deposit_balance += base_deposit
                    saved_real_balance -= base_deposit
                    available_balance = deposit_balance
                    betting_state["saved_real_balance"] = saved_real_balance
                    betting_state["deposit_balance"] = deposit_balance
                    if betting_config.debug_enabled:
                        print(f"[DEPOSIT] Автопополнение: +{base_deposit}р на deposit, saved_real={saved_real_balance:.0f}р, deposit={deposit_balance:.0f}р", flush=True)

        was_low_balance_paused = bool(betting_state.get("low_balance_pause_active"))
        stop_at_balance = float(getattr(betting_config, "stop_at_balance", 0.0) or 0.0)
        stop_at_balance_resume_check_seconds = float(
            getattr(betting_config, "stop_at_balance_resume_check_seconds", 300.0) or 300.0
        )

        if str(betting_state.get("low_balance_pause_reason") or "") == "target_balance_reached":
            now_utc = datetime.now(timezone.utc)
            last_check_raw = betting_state.get("target_balance_pause_last_check_at")
            last_observed_balance = _normalize_account_balance(
                betting_state.get("target_balance_pause_last_observed_balance")
            )
            if last_observed_balance is None and available_balance is not None:
                last_observed_balance = available_balance

            check_due = True
            if isinstance(last_check_raw, str) and last_check_raw:
                try:
                    last_check_at = datetime.fromisoformat(last_check_raw)
                    check_due = (now_utc - last_check_at).total_seconds() >= stop_at_balance_resume_check_seconds
                except ValueError:
                    check_due = True

            if not check_due:
                if (
                    available_balance is not None
                    and last_observed_balance is not None
                    and available_balance < last_observed_balance
                ) or betting_state.get("last_external_balance_change_type") == "withdrawal":
                    check_due = True

            if not check_due:
                return False

            betting_state["target_balance_pause_last_check_at"] = now_utc.isoformat()

            if available_balance is None:
                return False

            if last_observed_balance is not None and available_balance < last_observed_balance:
                _clear_low_balance_pause_state(betting_state)
                betting_state["current_step"] = 0
                betting_state["last_set_status"] = "resumed_after_target_balance_drop"
                betting_state["last_set_error"] = (
                    f"Возобновление: real balance снизился {last_observed_balance:.0f}р -> {available_balance:.0f}р, продолжаем с шага 1"
                )
                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_resume_after_target_balance_drop",
                    level="info",
                    message="[SET-RESUME] После снижения real balance возобновляем ставки с первого шага.",
                    extra={
                        "previous_balance": last_observed_balance,
                        "current_balance": available_balance,
                        "check_interval_seconds": stop_at_balance_resume_check_seconds,
                    },
                )
            else:
                betting_state["target_balance_pause_last_observed_balance"] = available_balance
                betting_state["last_set_status"] = "paused_target_balance"
                betting_state["last_set_error"] = (
                    f"Пауза: real balance {available_balance:.0f}р не снизился; повторная проверка через {int(stop_at_balance_resume_check_seconds // 60)} мин"
                )
                return False

        if stop_at_balance > 0 and available_balance is not None and available_balance >= stop_at_balance:
            pause_changed = _set_low_balance_pause_state(
                betting_state,
                amount=stop_at_balance,
                bet_targets=normalized_targets,
                reason="target_balance_reached",
            )
            now_utc = datetime.now(timezone.utc)
            betting_state["target_balance_pause_last_check_at"] = now_utc.isoformat()
            betting_state["target_balance_pause_last_observed_balance"] = available_balance
            betting_state["last_bet_amount"] = 0.0
            betting_state["last_set_amount"] = 0.0
            betting_state["last_set_status"] = "paused_target_balance"
            betting_state["last_set_error"] = (
                f"Пауза: достигнут целевой баланс {available_balance:.0f}р (лимит {stop_at_balance:.0f}р)"
            )
            if pause_changed:
                roi = calculate_roi_func()
                log_line = format_bet_log_func(
                    action="SET",
                    status_icon="✅",
                    outcome=targets_display,
                    amount=f"{total_round_amount:.0f}р",
                    step=f"{step_for_history+1}/{max_steps}",
                    result="STOP",
                    profit="-",
                    roi=f"{roi:.2f}%",
                    balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                    error_msg=betting_state["last_set_error"],
                    bets_count=next_round_display,
                )
                print(log_line, flush=True)
                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_stop_target_balance",
                    level="info",
                    message="[SET-STOP] Достигнут целевой real balance, автоставки остановлены.",
                    extra={
                        "account_balance": available_balance,
                        "stop_at_balance": stop_at_balance,
                    },
                )
                update_runtime_snapshot_func(
                    "bet_target_balance_pause",
                    {
                        "last_set_status": betting_state.get("last_set_status"),
                        "last_set_error": betting_state.get("last_set_error"),
                        "account_balance": available_balance,
                        "stop_at_balance": stop_at_balance,
                        "requested_targets": [target.token for target in requested_targets],
                        "effective_targets": [],
                        "low_balance_pause_active": True,
                        "low_balance_pause_required_balance": stop_at_balance,
                        "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                    },
                )
            return False

        required_bank_units = int(
            (current_strategy or {}).get(
                "required_bank_base_bet_units",
                sum((current_strategy or {}).get("coefficients", [1])),
            )
        )
        required_bank_amount = float(required_bank_units) * float(betting_config.base_bet) * float(len(normalized_targets))
        is_first_strategy_step = int(betting_state.get("total_bet_rounds", 0) or 0) == 0 and int(step_for_history or 0) == 0
        check_required_bank_on_first_step = bool(
            getattr(betting_config, "check_required_bank_on_first_step", True)
        )

        if is_first_strategy_step and check_required_bank_on_first_step:
            if available_balance is None:
                pause_changed = _set_low_balance_pause_state(
                    betting_state,
                    amount=required_bank_amount,
                    bet_targets=normalized_targets,
                    reason="required_bank_waiting_balance",
                )
                betting_state["last_bet_amount"] = 0.0
                betting_state["last_set_amount"] = 0.0
                betting_state["last_set_status"] = "paused_required_bank_balance_unknown"
                betting_state["last_set_error"] = (
                    "Пауза перед первым шагом: waiting balance update из accounting_ws для проверки required bank"
                )
                if pause_changed:
                    _print_bet_system_log(
                        runtime_config=runtime_config,
                        event="set_pause_waiting_required_bank_balance",
                        level="warning",
                        message="[SET-PAUSE] Первый шаг стратегии будет размещен после получения real balance из accounting_ws.",
                        extra={
                            "required_bank_amount": required_bank_amount,
                            "required_bank_base_bet_units": required_bank_units,
                        },
                    )
                    update_runtime_snapshot_func(
                        "bet_required_bank_wait_balance",
                        {
                            "last_set_status": betting_state.get("last_set_status"),
                            "last_set_error": betting_state.get("last_set_error"),
                            "required_bank_amount": required_bank_amount,
                            "required_bank_base_bet_units": required_bank_units,
                            "requested_targets": [target.token for target in requested_targets],
                            "effective_targets": [],
                            "low_balance_pause_active": True,
                            "low_balance_pause_required_balance": required_bank_amount,
                            "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                        },
                    )
                return False

            if available_balance < required_bank_amount:
                pause_changed = _set_low_balance_pause_state(
                    betting_state,
                    amount=required_bank_amount,
                    bet_targets=normalized_targets,
                    reason="required_bank_insufficient",
                )
                betting_state["last_bet_amount"] = 0.0
                betting_state["last_set_amount"] = 0.0
                betting_state["last_set_status"] = "paused_required_bank"
                betting_state["last_set_error"] = (
                    f"Пауза перед первым шагом: баланс {available_balance:.0f}р меньше required bank {required_bank_amount:.0f}р"
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
                        balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                        real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                        deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                        error_msg=betting_state["last_set_error"],
                        bets_count=next_round_display,
                    )
                    print(log_line, flush=True)
                    _print_bet_system_log(
                        runtime_config=runtime_config,
                        event="set_pause_required_bank_insufficient",
                        level="warning",
                        message="[SET-PAUSE] Для старта стратегии требуется полный банк цикла.",
                        extra={
                            "account_balance": available_balance,
                            "required_bank_amount": required_bank_amount,
                            "required_bank_base_bet_units": required_bank_units,
                        },
                    )
                    update_runtime_snapshot_func(
                        "bet_required_bank_pause",
                        {
                            "last_set_status": betting_state.get("last_set_status"),
                            "last_set_error": betting_state.get("last_set_error"),
                            "account_balance": available_balance,
                            "required_bank_amount": required_bank_amount,
                            "required_bank_base_bet_units": required_bank_units,
                            "requested_targets": [target.token for target in requested_targets],
                            "effective_targets": [],
                            "low_balance_pause_active": True,
                            "low_balance_pause_required_balance": required_bank_amount,
                            "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                        },
                    )
                return False

        max_stake_percent_of_bank = float(getattr(betting_config, "max_stake_percent_of_bank", 0.0) or 0.0)
        if max_stake_percent_of_bank > 0 and available_balance is not None and required_bank_units > 5:
            max_allowed_amount = available_balance * (max_stake_percent_of_bank / 100.0)
            if amount > max_allowed_amount + 1e-9:
                coefficients = current_strategy.get("coefficients", [1]) if current_strategy else [1]
                first_coefficient = float(coefficients[0]) if coefficients else 1.0
                resumed_base_amount = (
                    float(getattr(betting_config, "base_bet_2", 0.0) or 0.0)
                    if slot_label == "2"
                    else float(getattr(betting_config, "base_bet", 0.0) or 0.0)
                )
                reset_amount = resumed_base_amount * first_coefficient if resumed_base_amount > 0 else amount
                previous_amount = amount
                previous_step_for_history = int(step_for_history or 0)

                amount = reset_amount
                betting_state["current_step"] = 0
                step_for_history = 0
                total_round_amount = amount * len(normalized_targets)

                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_step_reset_by_percent_limit",
                    level="info",
                    message=(
                        "[SET-CHECK] Ставка превысила лимит доли банка; "
                        "сбрасываем шаг на 1 и пересчитываем сумму ставки."
                    ),
                    extra={
                        "slot": slot_label or "1",
                        "account_balance": available_balance,
                        "max_stake_percent_of_bank": max_stake_percent_of_bank,
                        "required_bank_base_bet_units": required_bank_units,
                        "max_allowed_amount": max_allowed_amount,
                        "previous_amount": previous_amount,
                        "reset_amount": amount,
                        "previous_step_for_history": previous_step_for_history,
                        "step_for_history": step_for_history,
                    },
                )


        if available_balance is None:
            if was_low_balance_paused:
                return False, (), amount
            if betting_config.debug_enabled and betting_state.get("total_bets_placed", 0) == 0:
                print("[SET-CHECK] Баланс из accounting_ws пока неизвестен, первую batch-ставку пропускаем без проверки лимита.", flush=True)
            return False, (), amount

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
                reason="min_bet_insufficient",
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
                    balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                    error_msg=betting_state["last_set_error"],
                    bets_count=next_round_display,
                )
                print(log_line, flush=True)
                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_pause_low_balance",
                    level="warning",
                    message="[SET-PAUSE] Возобновим ставки автоматически после восстановления real balance.",
                    extra={
                        "account_balance": available_balance,
                        "required_min_bet": amount,
                    },
                )
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
                        "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
                    },
                )
            return False, (), amount

            if was_low_balance_paused:
                _api_fail_pause_reason = str(betting_state.get("low_balance_pause_reason") or "")
                if _api_fail_pause_reason == "api_insufficient_balance" and not _has_fresh_accounting_update_after_api_fail(
                    betting_state
                ):
                    return False
                _clear_low_balance_pause_state(betting_state)
                betting_state["current_step"] = 0
                betting_state["consecutive_losses"] = 0
                # После возобновления из паузы стартуем с базовой ставки,
                # а не с уже рассчитанной суммы предыдущего шага прогрессии.
                resumed_base_amount = (
                    float(getattr(betting_config, "base_bet_2", 0.0) or 0.0)
                    if slot_label == "2"
                    else float(getattr(betting_config, "base_bet", 0.0) or 0.0)
                )
                if resumed_base_amount > 0 and amount != resumed_base_amount:
                    amount = resumed_base_amount
                    affordable_targets = _get_affordable_bet_targets(
                        bet_targets=normalized_targets,
                        amount=amount,
                        available_balance=available_balance,
                    )
                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_resume_low_balance",
                    level="info",
                    message=f"[SET-RESUME] Real balance восстановлен до {available_balance:.0f}р, продолжаем размещение ставок.",
                    extra={
                        "account_balance": available_balance,
                    },
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
            targets_display = _slot_prefix + _format_bet_targets_pretty(normalized_targets, format_outcome_pretty_func)
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
            balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
            deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
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
        target_tokens = [target.token for target in normalized_targets]
        payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://betboom.ru/game/nardsgame",
            "Origin": "https://betboom.ru",
            "X-Requested-With": "XMLHttpRequest",
        }
        if jwt_token:
            headers["X-Access-Token"] = jwt_token

        if betting_config.post_log_enabled:
            request_message = (
                "[POST-SET][REQ] "
                f"url={runtime_config.browser.bet_api_url} "
                f"slot={slot_label or '1'} "
                f"round={next_round_display} "
                f"targets={target_tokens} "
                f"amount_per_target={amount:.0f} "
                f"total_amount={total_round_amount:.0f} "
                f"payload={payload_text}"
            )
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="bet_post_request",
                level="info",
                message=request_message,
                extra={
                    "url": runtime_config.browser.bet_api_url,
                    "slot": slot_label or "1",
                    "round": next_round_display,
                    "target_tokens": target_tokens,
                    "amount_per_target": amount,
                    "total_amount": total_round_amount,
                    "payload": payload,
                },
            )

        response = await page.request.post(runtime_config.browser.bet_api_url, data=json.dumps(payload), headers=headers)
        status_code = response.status
        response_text = await response.text()
        response_text_preview = response_text
        if len(response_text_preview) > 800:
            response_text_preview = response_text_preview[:800] + "...(truncated)"

        try:
            response_json = json.loads(response_text)
            if isinstance(response_json, dict) and "code" in response_json:
                status_code = response_json["code"]
        except (json.JSONDecodeError, ValueError):
            pass

        if betting_config.post_log_enabled:
            response_message = (
                "[POST-SET][RES] "
                f"url={runtime_config.browser.bet_api_url} "
                f"slot={slot_label or '1'} "
                f"round={next_round_display} "
                f"status={status_code} "
                f"body={response_text_preview}"
            )
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="bet_post_response",
                level="info",
                message=response_message,
                extra={
                    "url": runtime_config.browser.bet_api_url,
                    "slot": slot_label or "1",
                    "round": next_round_display,
                    "status": status_code,
                    "body_preview": response_text_preview,
                    "body_truncated": len(response_text) > 800,
                },
            )

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
            should_update_snapshot = True
            if status_code == 200:
                previous_total_bets = betting_state.get("total_bets_placed", 0)
                current_round_number = next_round_number
                betting_state["total_bet_amount"] += total_round_amount
                betting_state["total_bets_placed"] = previous_total_bets + len(normalized_targets)
                betting_state["total_bet_rounds"] = current_round_number
                betting_state["last_bet_round_number"] = current_round_number
                betting_state["pending_expected_bet_drop"] = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0) + total_round_amount
                betting_state["reconciliation_phase"] = "awaiting_bet_drop"
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
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status, slot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                            slot_number,
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
                    balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
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
                        _print_bet_system_log(
                            runtime_config=runtime_config,
                            event="auth_retry_after_token_refresh",
                            level="warning",
                            message="[AUTH] Повторяем batch-ставку один раз после обновления токена.",
                        )
                        runtime_context.jwt_token = get_jwt_token_func()
                        return await place_bets(
                            page,
                            normalized_targets,
                            amount,
                            allow_refresh_retry=False,
                            slot_label=slot_label,
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
                    betting_state["low_balance_api_fail_at"] = datetime.now(timezone.utc).isoformat()
                    pause_changed = _set_low_balance_pause_state(
                        betting_state,
                        amount=amount,
                        bet_targets=normalized_targets,
                        reason="api_insufficient_balance",
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
                        balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                        real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                        deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                        error_msg=betting_state["last_set_error"],
                        bets_count=next_round_display,
                    )
                    print(log_line, flush=True)
                    if pause_changed:
                        _print_bet_system_log(
                            runtime_config=runtime_config,
                            event="set_pause_api_insufficient_balance",
                            level="warning",
                            message="[SET-PAUSE] API вернул недостаточно средств, шаг стратегии не сдвигаем.",
                            extra={
                                "http_status": status_code,
                            },
                        )
                    else:
                        should_update_snapshot = False
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
                        balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                        real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                        deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
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
                            INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status, slot)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                datetime.now(timezone.utc),
                                target.outcome,
                                target.specifier,
                                amount,
                                betting_config.strategy_name,
                                step_for_history,
                                "error",
                                slot_number,
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
                "low_balance_pause_reason": betting_state.get("low_balance_pause_reason"),
            }
            conn.commit()
            cursor.close()
            conn.close()
            if should_update_snapshot:
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
                balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
                real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
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
            balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
            deposit_balance=f"{available_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
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


async def place_bets_combined_slots(
    page,
    *,
    slot1_targets: tuple[BetTarget, ...],
    slot1_amount: float,
    slot2_targets: tuple[BetTarget, ...],
    slot2_amount: float,
    allow_refresh_retry: bool = True,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    get_jwt_token_func,
    validate_base_bet_func,
    calculate_roi_func,
    calculate_roi_2_func,
    format_outcome_pretty_func,
    format_bet_log_func,
    get_balance_for_log_func,
    get_db_connection_func,
    is_forbidden_access_error_func,
    reload_page_and_refresh_token_func,
    advance_step_after_set_error_func,
    advance_step_2_after_set_error_func,
    update_runtime_snapshot_func,
    queue_telegram_notification_func,
) -> bool:
    betting_state_1 = runtime_context.betting_state
    betting_state_2 = runtime_context.betting_state_2
    strategy_1 = runtime_context.current_strategy or {}
    strategy_2 = runtime_context.current_strategy_2 or {}
    betting_config = runtime_config.betting
    telegram_config = runtime_config.telegram

    if betting_state_1 is None or betting_state_2 is None:
        return False
    if not slot1_targets or not slot2_targets:
        return False

    jwt_token = runtime_context.jwt_token
    if not jwt_token:
        print("[WARNING] JWT токен ещё не найден! Комбинированная ставка НЕ будет размещена.", flush=True)
        advance_step_after_set_error_func()
        advance_step_2_after_set_error_func()
        return False

    if not validate_base_bet_func(slot1_amount):
        print(f"[ERROR] Ставка slot1 {slot1_amount}р ДОЛЖНА делиться на 10 нацело!", flush=True)
        advance_step_after_set_error_func()
        return False

    if not validate_base_bet_func(slot2_amount):
        print(f"[ERROR] Ставка slot2 {slot2_amount}р ДОЛЖНА делиться на 10 нацело!", flush=True)
        advance_step_2_after_set_error_func()
        return False

    delay = random.uniform(betting_config.bet_delay_min, betting_config.bet_delay_max)
    await asyncio.sleep(delay)

    slot1_total_amount = slot1_amount * len(slot1_targets)
    slot2_total_amount = slot2_amount * len(slot2_targets)
    slot1_step_for_history = betting_state_1.get("current_step", 0)
    slot2_step_for_history = betting_state_2.get("current_step", 0)
    slot1_max_steps = len(strategy_1.get("coefficients", [1])) if strategy_1 else 15
    slot2_max_steps = len(strategy_2.get("coefficients", [1])) if strategy_2 else 15
    slot1_round_number = int(betting_state_1.get("total_bet_rounds", 0) or 0) + 1
    slot2_round_number = int(betting_state_2.get("total_bet_rounds", 0) or 0) + 1
    slot1_round_display = str(slot1_round_number).zfill(3)
    slot2_round_display = str(slot2_round_number).zfill(3)

    slot1_tokens = [target.token for target in slot1_targets]
    slot2_tokens = [target.token for target in slot2_targets]
    slot1_display = "[1]" + _format_bet_targets_pretty(slot1_targets, format_outcome_pretty_func)
    slot2_display = "[2]" + _format_bet_targets_pretty(slot2_targets, format_outcome_pretty_func)

    payload = {
        "bets": [
            *[_build_bet_payload(target, slot1_amount) for target in slot1_targets],
            *[_build_bet_payload(target, slot2_amount) for target in slot2_targets],
        ]
    }
    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    headers = {
        "Content-Type": "application/json",
        "Referer": "https://betboom.ru/game/nardsgame",
        "Origin": "https://betboom.ru",
        "X-Requested-With": "XMLHttpRequest",
    }
    if jwt_token:
        headers["X-Access-Token"] = jwt_token

    if betting_config.post_log_enabled:
        request_message = (
            "[POST-SET][REQ] "
            f"url={runtime_config.browser.bet_api_url} "
            "slot=1+2 "
            f"round={slot1_round_display}+{slot2_round_display} "
            f"targets_1={slot1_tokens} amount_per_target_1={slot1_amount:.0f} total_amount_1={slot1_total_amount:.0f} "
            f"targets_2={slot2_tokens} amount_per_target_2={slot2_amount:.0f} total_amount_2={slot2_total_amount:.0f} "
            f"payload={payload_text}"
        )
        _print_bet_system_log(
            runtime_config=runtime_config,
            event="bet_post_request_combined",
            level="info",
            message=request_message,
            extra={
                "url": runtime_config.browser.bet_api_url,
                "slot": "1+2",
                "round_1": slot1_round_display,
                "round_2": slot2_round_display,
                "target_tokens_1": slot1_tokens,
                "target_tokens_2": slot2_tokens,
                "amount_per_target_1": slot1_amount,
                "amount_per_target_2": slot2_amount,
                "total_amount_1": slot1_total_amount,
                "total_amount_2": slot2_total_amount,
                "payload": payload,
            },
        )

    try:
        response = await page.request.post(runtime_config.browser.bet_api_url, data=json.dumps(payload), headers=headers)
        status_code = response.status
        response_text = await response.text()
        response_text_preview = response_text
        if len(response_text_preview) > 800:
            response_text_preview = response_text_preview[:800] + "...(truncated)"

        try:
            response_json = json.loads(response_text)
            if isinstance(response_json, dict) and "code" in response_json:
                status_code = response_json["code"]
        except (json.JSONDecodeError, ValueError):
            pass

        if betting_config.post_log_enabled:
            response_message = (
                "[POST-SET][RES] "
                f"url={runtime_config.browser.bet_api_url} "
                "slot=1+2 "
                f"round={slot1_round_display}+{slot2_round_display} "
                f"status={status_code} "
                f"body={response_text_preview}"
            )
            _print_bet_system_log(
                runtime_config=runtime_config,
                event="bet_post_response_combined",
                level="info",
                message=response_message,
                extra={
                    "url": runtime_config.browser.bet_api_url,
                    "slot": "1+2",
                    "round_1": slot1_round_display,
                    "round_2": slot2_round_display,
                    "status": status_code,
                    "body_preview": response_text_preview,
                    "body_truncated": len(response_text) > 800,
                },
            )

        conn = get_db_connection_func()
        cursor = conn.cursor()
        try:
            should_refresh_token = is_forbidden_access_error_func(status_code, response_text)
            is_insufficient_balance = _is_insufficient_balance_response(status_code, response_text)

            if status_code == 200:
                previous_total_bets_1 = betting_state_1.get("total_bets_placed", 0)
                previous_total_bets_2 = betting_state_2.get("total_bets_placed", 0)

                betting_state_1["total_bet_amount"] += slot1_total_amount
                betting_state_1["total_bets_placed"] = previous_total_bets_1 + len(slot1_targets)
                betting_state_1["total_bet_rounds"] = slot1_round_number
                betting_state_1["last_bet_round_number"] = slot1_round_number
                betting_state_1["pending_expected_bet_drop"] = float(betting_state_1.get("pending_expected_bet_drop", 0.0) or 0.0) + slot1_total_amount
                betting_state_1["reconciliation_phase"] = "awaiting_bet_drop"
                betting_state_1["last_bet_amount"] = slot1_total_amount
                betting_state_1["last_set_amount"] = slot1_total_amount
                betting_state_1["last_set_status"] = "pending"
                betting_state_1["last_set_error"] = None

                betting_state_2["total_bet_amount"] += slot2_total_amount
                betting_state_2["total_bets_placed"] = previous_total_bets_2 + len(slot2_targets)
                betting_state_2["total_bet_rounds"] = slot2_round_number
                betting_state_2["last_bet_round_number"] = slot2_round_number
                betting_state_2["pending_expected_bet_drop"] = float(betting_state_2.get("pending_expected_bet_drop", 0.0) or 0.0) + slot2_total_amount
                betting_state_2["reconciliation_phase"] = "awaiting_bet_drop"
                betting_state_2["last_bet_amount"] = slot2_total_amount
                betting_state_2["last_set_amount"] = slot2_total_amount
                betting_state_2["last_set_status"] = "pending"
                betting_state_2["last_set_error"] = None

                pending_bets_1 = []
                for target in slot1_targets:
                    cursor.execute(
                        """
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status, slot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            datetime.now(timezone.utc),
                            target.outcome,
                            target.specifier,
                            slot1_amount,
                            betting_config.strategy_name,
                            slot1_step_for_history,
                            "pending",
                            1,
                        ),
                    )
                    history_id_row = cursor.fetchone()
                    history_id = history_id_row[0] if history_id_row else None
                    pending_bets_1.append(
                        {
                            "history_id": history_id,
                            "outcome": target.outcome,
                            "specifier": target.specifier,
                            "amount": slot1_amount,
                            "bet_step": slot1_step_for_history,
                            "token": target.token,
                            "round_number": slot1_round_number,
                        }
                    )
                betting_state_1["pending_bets"] = pending_bets_1

                pending_bets_2 = []
                for target in slot2_targets:
                    cursor.execute(
                        """
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status, slot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            datetime.now(timezone.utc),
                            target.outcome,
                            target.specifier,
                            slot2_amount,
                            betting_config.strategy_name_2,
                            slot2_step_for_history,
                            "pending",
                            2,
                        ),
                    )
                    history_id_row = cursor.fetchone()
                    history_id = history_id_row[0] if history_id_row else None
                    pending_bets_2.append(
                        {
                            "history_id": history_id,
                            "outcome": target.outcome,
                            "specifier": target.specifier,
                            "amount": slot2_amount,
                            "bet_step": slot2_step_for_history,
                            "token": target.token,
                            "round_number": slot2_round_number,
                        }
                    )
                betting_state_2["pending_bets"] = pending_bets_2

                payout_coeff_1 = strategy_1.get("payout_coefficient", 5.7)
                payout_coeff_2 = strategy_2.get("payout_coefficient", 5.7)
                potential_margin_1 = ((slot1_amount * payout_coeff_1) - slot1_amount) * len(slot1_targets)
                potential_margin_2 = ((slot2_amount * payout_coeff_2) - slot2_amount) * len(slot2_targets)


                # Получаем актуальные значения баланса для каждого слота
                slot1_balance = _normalize_account_balance(betting_state_1.get("deposit_balance")) if runtime_config.accounting.deposit_mode_enabled else betting_state_1.get("session_balance", 0)
                slot2_balance = _normalize_account_balance(betting_state_2.get("deposit_balance")) if runtime_config.accounting.deposit_mode_enabled else betting_state_2.get("session_balance", 0)

                log_line_1 = format_bet_log_func(
                    action="SET",
                    status_icon="✅",
                    outcome=slot1_display,
                    amount=f"{slot1_total_amount:.0f}р",
                    step=f"{slot1_step_for_history+1}/{slot1_max_steps}",
                    result="------",
                    profit=f"+{potential_margin_1:.0f}р",
                    roi=f"{calculate_roi_func():.2f}%",
                    balance=f"{slot1_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state_1.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state_1.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    deposit_balance=f"{slot1_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                    bets_count=slot1_round_display,
                )
                print(log_line_1, flush=True)

                log_line_2 = format_bet_log_func(
                    action="SET",
                    status_icon="✅",
                    outcome=slot2_display,
                    amount=f"{slot2_total_amount:.0f}р",
                    step=f"{slot2_step_for_history+1}/{slot2_max_steps}",
                    result="------",
                    profit=f"+{potential_margin_2:.0f}р",
                    roi=f"{calculate_roi_2_func():.2f}%",
                    balance=f"{slot2_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else f"{betting_state_2.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state_2.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    deposit_balance=f"{slot2_balance:.0f}р" if runtime_config.accounting.deposit_mode_enabled else "",
                    bets_count=slot2_round_display,
                )
                print(log_line_2, flush=True)

                conn.commit()
                update_runtime_snapshot_func(
                    "bet_set_combined",
                    {
                        "combined_post": True,
                        "http_status": status_code,
                        "last_set_status_1": betting_state_1.get("last_set_status"),
                        "last_set_status_2": betting_state_2.get("last_set_status"),
                        "pending_bets_count_1": len(betting_state_1.get("pending_bets", [])),
                        "pending_bets_count_2": len(betting_state_2.get("pending_bets", [])),
                        "targets_1": slot1_tokens,
                        "targets_2": slot2_tokens,
                    },
                )
                return True

            betting_state_1["pending_bets"] = []
            betting_state_2["pending_bets"] = []
            betting_state_1["last_bet_amount"] = 0.0
            betting_state_2["last_bet_amount"] = 0.0
            betting_state_1["last_set_amount"] = slot1_total_amount
            betting_state_2["last_set_amount"] = slot2_total_amount
            betting_state_1["last_set_status"] = "forbidden_refresh" if should_refresh_token else "error"
            betting_state_2["last_set_status"] = "forbidden_refresh" if should_refresh_token else "error"
            betting_state_1["last_set_error"] = response_text[:100] if response_text else "Unknown error"
            betting_state_2["last_set_error"] = response_text[:100] if response_text else "Unknown error"

            if should_refresh_token and allow_refresh_retry:
                token_refreshed = await reload_page_and_refresh_token_func(page)
                if token_refreshed:
                    betting_state_1["last_set_status"] = "retry_after_refresh"
                    betting_state_2["last_set_status"] = "retry_after_refresh"
                    betting_state_1["last_set_error"] = None
                    betting_state_2["last_set_error"] = None
                    conn.close()
                    runtime_context.jwt_token = get_jwt_token_func()
                    return await place_bets_combined_slots(
                        page,
                        slot1_targets=slot1_targets,
                        slot1_amount=slot1_amount,
                        slot2_targets=slot2_targets,
                        slot2_amount=slot2_amount,
                        allow_refresh_retry=False,
                        runtime_context=runtime_context,
                        runtime_config=runtime_config,
                        get_jwt_token_func=get_jwt_token_func,
                        validate_base_bet_func=validate_base_bet_func,
                        calculate_roi_func=calculate_roi_func,
                        calculate_roi_2_func=calculate_roi_2_func,
                        format_outcome_pretty_func=format_outcome_pretty_func,
                        format_bet_log_func=format_bet_log_func,
                        get_balance_for_log_func=get_balance_for_log_func,
                        get_db_connection_func=get_db_connection_func,
                        is_forbidden_access_error_func=is_forbidden_access_error_func,
                        reload_page_and_refresh_token_func=reload_page_and_refresh_token_func,
                        advance_step_after_set_error_func=advance_step_after_set_error_func,
                        advance_step_2_after_set_error_func=advance_step_2_after_set_error_func,
                        update_runtime_snapshot_func=update_runtime_snapshot_func,
                        queue_telegram_notification_func=queue_telegram_notification_func,
                    )

            if is_insufficient_balance:
                betting_state_1["low_balance_api_fail_at"] = datetime.now(timezone.utc).isoformat()
                betting_state_2["low_balance_api_fail_at"] = datetime.now(timezone.utc).isoformat()
                _set_low_balance_pause_state(
                    betting_state_1,
                    amount=slot1_amount,
                    bet_targets=slot1_targets,
                    reason="api_insufficient_balance",
                )
                _set_low_balance_pause_state(
                    betting_state_2,
                    amount=slot2_amount,
                    bet_targets=slot2_targets,
                    reason="api_insufficient_balance",
                )
                betting_state_1["last_set_status"] = "paused_low_balance"
                betting_state_2["last_set_status"] = "paused_low_balance"
            else:
                advance_step_after_set_error_func()
                advance_step_2_after_set_error_func()

                for target in slot1_targets:
                    cursor.execute(
                        """
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status, slot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            datetime.now(timezone.utc),
                            target.outcome,
                            target.specifier,
                            slot1_amount,
                            betting_config.strategy_name,
                            slot1_step_for_history,
                            "error",
                            1,
                        ),
                    )

                for target in slot2_targets:
                    cursor.execute(
                        """
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status, slot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            datetime.now(timezone.utc),
                            target.outcome,
                            target.specifier,
                            slot2_amount,
                            betting_config.strategy_name_2,
                            slot2_step_for_history,
                            "error",
                            2,
                        ),
                    )

            slot1_result = "PAUSE" if is_insufficient_balance else "ERROR"
            slot2_result = "PAUSE" if is_insufficient_balance else "ERROR"
            slot1_error = response_text[:100] if response_text else "Unknown error"
            slot2_error = response_text[:100] if response_text else "Unknown error"

            print(
                format_bet_log_func(
                    action="SET",
                    status_icon="❌",
                    outcome=slot1_display,
                    amount=f"{slot1_total_amount:.0f}р",
                    step=f"{slot1_step_for_history+1}/{slot1_max_steps}",
                    result=slot1_result,
                    profit="-",
                    roi=f"{calculate_roi_func():.2f}%",
                    balance=f"{betting_state_1.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state_1.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    error_msg=slot1_error,
                    bets_count=slot1_round_display,
                ),
                flush=True,
            )
            print(
                format_bet_log_func(
                    action="SET",
                    status_icon="❌",
                    outcome=slot2_display,
                    amount=f"{slot2_total_amount:.0f}р",
                    step=f"{slot2_step_for_history+1}/{slot2_max_steps}",
                    result=slot2_result,
                    profit="-",
                    roi=f"{calculate_roi_2_func():.2f}%",
                    balance=f"{betting_state_2.get('session_balance', 0):.0f}р",
                    real_balance=f"{betting_state_2.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    error_msg=slot2_error,
                    bets_count=slot2_round_display,
                ),
                flush=True,
            )

            conn.commit()
            update_runtime_snapshot_func(
                "bet_set_combined_error",
                {
                    "combined_post": True,
                    "http_status": status_code,
                    "last_set_status_1": betting_state_1.get("last_set_status"),
                    "last_set_status_2": betting_state_2.get("last_set_status"),
                    "last_set_error_1": betting_state_1.get("last_set_error"),
                    "last_set_error_2": betting_state_2.get("last_set_error"),
                    "targets_1": slot1_tokens,
                    "targets_2": slot2_tokens,
                },
            )
            return False
        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass

    except Exception as exc:
        betting_state_1["pending_bets"] = []
        betting_state_2["pending_bets"] = []
        betting_state_1["last_bet_amount"] = 0.0
        betting_state_2["last_bet_amount"] = 0.0
        betting_state_1["last_set_status"] = "request_error"
        betting_state_2["last_set_status"] = "request_error"
        betting_state_1["last_set_error"] = str(exc)[:100]
        betting_state_2["last_set_error"] = str(exc)[:100]

        print(
            format_bet_log_func(
                action="SET",
                status_icon="❌",
                outcome=slot1_display,
                amount=f"{slot1_total_amount:.0f}р",
                step="-",
                result="ERROR",
                profit="-",
                roi=f"{calculate_roi_func():.2f}%",
                balance=f"{betting_state_1.get('session_balance', 0):.0f}р",
                real_balance=f"{betting_state_1.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                error_msg=str(exc)[:100],
                bets_count=slot1_round_display,
            ),
            flush=True,
        )
        print(
            format_bet_log_func(
                action="SET",
                status_icon="❌",
                outcome=slot2_display,
                amount=f"{slot2_total_amount:.0f}р",
                step="-",
                result="ERROR",
                profit="-",
                roi=f"{calculate_roi_2_func():.2f}%",
                balance=f"{betting_state_2.get('session_balance', 0):.0f}р",
                real_balance=f"{betting_state_2.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                error_msg=str(exc)[:100],
                bets_count=slot2_round_display,
            ),
            flush=True,
        )

        queue_telegram_notification_func(
            "[BuyBayBye] Ошибка объединенного запроса ставки",
            (
                "Комбинированный POST для slot1+slot2 завершился ошибкой.\n"
                f"slot1: {slot1_display}, сумма: {slot1_total_amount:.0f}р\n"
                f"slot2: {slot2_display}, сумма: {slot2_total_amount:.0f}р\n"
                f"Ошибка: {str(exc)[:300]}"
            ),
            dedup_key="bet_request_error_combined",
            enabled=telegram_config.notify_bet_errors,
        )

        advance_step_after_set_error_func()
        advance_step_2_after_set_error_func()
        update_runtime_snapshot_func(
            "bet_set_combined_request_error",
            {
                "combined_post": True,
                "last_set_status_1": betting_state_1.get("last_set_status"),
                "last_set_status_2": betting_state_2.get("last_set_status"),
                "last_set_error_1": betting_state_1.get("last_set_error"),
                "last_set_error_2": betting_state_2.get("last_set_error"),
                "targets_1": slot1_tokens,
                "targets_2": slot2_tokens,
            },
        )
        return False


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
    update_dynamic_bet_2_func=None,
    generate_random_bet_func,
    calculate_bet_amount_func,
    place_bet_func,
    place_bets_func,
    place_bets_combined_slots_func=None,
    calculate_bet_amount_2_func=None,
    place_bets_2_func=None,
) -> None:
    betting_state = runtime_context.betting_state
    current_strategy = runtime_context.current_strategy
    configured_targets = runtime_context.get_configured_bet_targets()
    multi_target_mode = len(configured_targets) > 1
    dynamic_bet_mode = runtime_config.dynamic_betting.enabled and (
        not multi_target_mode or runtime_config.dynamic_betting.multi_target_enabled
    )
    bet_debug_enabled = runtime_config.betting.debug_enabled
    try:
        payload_text = format_ws_payload_func(payload)
        parsed_payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if not isinstance(parsed_payload, dict) or parsed_payload.get("status") != "rng_values":
        return

    game_id_value = parsed_payload.get("game_id")
    game_id = str(game_id_value).strip() if game_id_value is not None else None
    if game_id and betting_state.has_processed_round(game_id):
        if bet_debug_enabled:
            print(f"[DEBUG PROCESS] Пропускаем duplicate game_id={game_id}", flush=True)
        return
    if game_id:
        betting_state.mark_round_processed(game_id)

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
            history_ids: list[int] = []
            previous_consecutive_losses = int(betting_state.get("consecutive_losses", 0) or 0)

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
                betting_state.remember_recent_bet(combo=resolved_token, result=is_win)
                resolved_target_tokens.append(resolved_token)
                round_target_labels.append(format_outcome_pretty_func(target.outcome, target.specifier))

                if pending_bet.get("history_id") is not None:
                    history_ids.append(pending_bet["history_id"])
                    cursor.execute(
                        """
                        UPDATE bet_history
                        SET status = %s, result_dice_color = %s, result_dice_value = %s
                        WHERE id = %s
                        """,
                        (
                            WIN_PENDING_CONFIRMATION_STATUS if is_win else status,
                            stored_dice_color,
                            actual_dice_value,
                            pending_bet["history_id"],
                        ),
                    )

            max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
            betting_state["pending_bets"] = []
            betting_state["pending_expected_settlement_credit"] = settlement_credit
            betting_state["reconciliation_phase"] = "awaiting_settlement" if settlement_credit > 0.009 else "idle"

            restarted = False
            if round_margin > 0:
                if _pending_win_confirmation_is_enabled(runtime_config):
                    betting_state["pending_win_confirmation"] = {
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "expected_settlement_credit": settlement_credit,
                        "round_margin": round_margin,
                        "max_steps": max_steps,
                        "current_step_before_resolution": current_step_for_log,
                        "consecutive_losses_before_resolution": previous_consecutive_losses,
                        "history_ids": history_ids,
                        "resolved_target_tokens": resolved_target_tokens,
                        "result_display": actual_dice_representation,
                    }
                    betting_state["last_set_status"] = WIN_PENDING_CONFIRMATION_STATUS
                else:
                    betting_state["pending_win_confirmation"] = None
                    betting_state["pending_expected_settlement_credit"] = 0.0
                    betting_state["reconciliation_phase"] = "idle"
                    betting_state["current_step"] = 0
                    betting_state["consecutive_losses"] = 0
                    betting_state["last_set_status"] = "win"
                    betting_state["total_profit"] += round_margin
                    betting_state["session_balance"] += round_margin
            elif current_step_for_log + 1 >= max_steps:
                betting_state["current_step"] = 0
                betting_state["consecutive_losses"] = 0
                restarted = True
                betting_state["last_set_status"] = "loss"
            else:
                betting_state["current_step"] = current_step_for_log + 1
                betting_state["consecutive_losses"] = betting_state.get("consecutive_losses", 0) + 1
                betting_state["last_set_status"] = "loss"

            balance_for_log = betting_state["session_balance"]
            bet_result_status = "loss"
            if round_margin > 0:
                bet_result_status = WIN_PENDING_CONFIRMATION_STATUS if _pending_win_confirmation_is_enabled(runtime_config) else "win"
            else:
                betting_state["total_profit"] += round_margin
                betting_state["session_balance"] += round_margin
                balance_for_log = betting_state["session_balance"]

            roi = calculate_roi_func()
            total_bets = betting_state.get("total_bets_placed", 0)
            resolved_round_number = 0
            if pending_bets:
                resolved_round_number = int(pending_bets[0].get("round_number", 0) or 0)
            if resolved_round_number <= 0:
                resolved_round_number = int(betting_state.get("last_bet_round_number", 0) or 0)
            round_targets_display = "[1]" + ", ".join(round_target_labels)
            log_line = format_bet_log_func(
                action="RES",
                status_icon="✅" if round_margin > 0 else "❌",
                outcome=round_targets_display,
                amount=f"{betting_state.get('last_bet_amount', 0):.0f}р",
                step=(f"{current_step_for_log+1}/{max_steps}" if round_margin > 0 or not restarted else f"{max_steps}/{max_steps}"),
                result=actual_dice_representation,
                profit=f"{round_margin:+.0f}р",
                roi=f"{roi:.2f}%",
                balance=f"{balance_for_log:.0f}р",
                real_balance=f"{betting_state.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                bets_count=str(resolved_round_number or total_bets).zfill(3),
            )
            print(log_line, flush=True)

            if total_bets > 0 and total_bets % 50 == 0:
                print_session_stats_func(total_bets)
            if total_bets > 0 and total_bets % 20 == 0:
                print_dice_stats_20_func()

            result_snapshot_extra = {
                "bet_result_status": bet_result_status,
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

    # Обработка результата второго слота ставок
    betting_state_2 = runtime_context.betting_state_2
    current_strategy_2 = runtime_context.current_strategy_2
    if betting_state_2 is not None and current_strategy_2 is not None:
        pending_bets_2 = list(betting_state_2.get("pending_bets") or [])
        if pending_bets_2:
            try:
                conn_2 = get_db_connection_func()
                cursor_2 = conn_2.cursor()
                payout_coeff_2 = current_strategy_2.get("payout_coefficient", 5.7)
                round_margin_2 = 0.0
                current_step_2 = int(betting_state_2.get("current_step", 0) or 0)
                max_steps_2 = len(current_strategy_2.get("coefficients", [1]))
                settlement_credit_2 = 0.0
                round_target_labels_2: list[str] = []
                history_ids_2: list[int] = []
                previous_consecutive_losses_2 = int(betting_state_2.get("consecutive_losses", 0) or 0)

                for pending_bet in pending_bets_2:
                    target = BetTarget(outcome=pending_bet["outcome"], specifier=pending_bet.get("specifier", ""))
                    is_win, stored_dice_color_2, actual_dice_value_2 = _is_target_win(target, dice_results)
                    status = "win" if is_win else "loss"
                    bet_amount = float(pending_bet.get("amount", 0.0) or 0.0)
                    margin = (bet_amount * payout_coeff_2) - bet_amount if is_win else -bet_amount
                    if is_win:
                        settlement_credit_2 += bet_amount * payout_coeff_2
                    round_margin_2 += margin
                    round_target_labels_2.append(format_outcome_pretty_func(target.outcome, target.specifier))
                    if pending_bet.get("history_id") is not None:
                        history_ids_2.append(pending_bet["history_id"])
                        cursor_2.execute(
                            """
                            UPDATE bet_history
                            SET status = %s, result_dice_color = %s, result_dice_value = %s
                            WHERE id = %s
                            """,
                            (
                                WIN_PENDING_CONFIRMATION_STATUS if is_win else status,
                                stored_dice_color_2,
                                actual_dice_value_2,
                                pending_bet["history_id"],
                            ),
                        )

                betting_state_2["pending_bets"] = []
                betting_state_2["pending_expected_settlement_credit"] = settlement_credit_2
                betting_state_2["reconciliation_phase"] = "awaiting_settlement" if settlement_credit_2 > 0.009 else "idle"

                restarted_2 = False
                if round_margin_2 > 0:
                    if _pending_win_confirmation_is_enabled(runtime_config):
                        betting_state_2["pending_win_confirmation"] = {
                            "recorded_at": datetime.now(timezone.utc).isoformat(),
                            "expected_settlement_credit": settlement_credit_2,
                            "round_margin": round_margin_2,
                            "max_steps": max_steps_2,
                            "current_step_before_resolution": current_step_2,
                            "consecutive_losses_before_resolution": previous_consecutive_losses_2,
                            "history_ids": history_ids_2,
                            "resolved_target_tokens": [pending_bet.get("token") for pending_bet in pending_bets_2 if pending_bet.get("token")],
                            "result_display": actual_dice_representation,
                        }
                        betting_state_2["last_set_status"] = WIN_PENDING_CONFIRMATION_STATUS
                    else:
                        betting_state_2["pending_win_confirmation"] = None
                        betting_state_2["pending_expected_settlement_credit"] = 0.0
                        betting_state_2["reconciliation_phase"] = "idle"
                        betting_state_2["current_step"] = 0
                        betting_state_2["consecutive_losses"] = 0
                        betting_state_2["last_set_status"] = "win"
                        betting_state_2["total_profit"] += round_margin_2
                        betting_state_2["session_balance"] += round_margin_2
                elif current_step_2 + 1 >= max_steps_2:
                    betting_state_2["current_step"] = 0
                    betting_state_2["consecutive_losses"] = 0
                    restarted_2 = True
                    betting_state_2["last_set_status"] = "loss"
                else:
                    betting_state_2["current_step"] = current_step_2 + 1
                    betting_state_2["consecutive_losses"] = betting_state_2.get("consecutive_losses", 0) + 1
                    betting_state_2["last_set_status"] = "loss"

                balance_for_log_2 = betting_state_2.get("session_balance", 0)
                if round_margin_2 <= 0:
                    betting_state_2["total_profit"] += round_margin_2
                    betting_state_2["session_balance"] += round_margin_2
                    balance_for_log_2 = betting_state_2.get("session_balance", 0)

                round_targets_display_2 = "[2]" + ", ".join(round_target_labels_2)
                resolved_round_number_2 = int(pending_bets_2[0].get("round_number", 0) or 0) if pending_bets_2 else 0
                log_line_2 = format_bet_log_func(
                    action="RES",
                    status_icon="✅" if round_margin_2 > 0 else "❌",
                    outcome=round_targets_display_2,
                    amount=f"{betting_state_2.get('last_bet_amount', 0):.0f}р",
                    step=(f"{current_step_2+1}/{max_steps_2}" if round_margin_2 > 0 or not restarted_2 else f"{max_steps_2}/{max_steps_2}"),
                    result=actual_dice_representation,
                    profit=f"{round_margin_2:+.0f}р",
                    roi=f"{(betting_state_2.get('total_profit', 0) / betting_state_2.get('total_bet_amount', 1) * 100) if betting_state_2.get('total_bet_amount', 0) > 0 else 0:.2f}%",
                    balance=f"{balance_for_log_2:.0f}р",
                    real_balance=f"{betting_state_2.get('saved_real_balance', 0):.0f}р" if runtime_config.accounting.deposit_mode_enabled else get_balance_for_log_func(),
                    bets_count=str(resolved_round_number_2).zfill(3),
                )
                print(log_line_2, flush=True)
                conn_2.commit()
            except Exception as exc_2:
                print(f"[DB ERROR] Ошибка обновления результата ставки (слот 2): {exc_2}", flush=True)
            finally:
                try:
                    cursor_2.close()
                    conn_2.close()
                except Exception:
                    pass

    slot1_process_level_precheck_required = True
    slot2_process_level_precheck_required = betting_state_2 is not None
    slot1_fallback_active = False
    slot2_fallback_active = False

    pending_confirmation = betting_state.get("pending_win_confirmation")
    if isinstance(pending_confirmation, dict) and pending_confirmation:
        slot1_confirmation_outcome = await _wait_briefly_for_pending_win_confirmation(
            betting_state=betting_state,
            runtime_config=runtime_config,
            get_db_connection_func=get_db_connection_func,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            slot_label="1",
        )
        if slot1_confirmation_outcome == "pending":
            slot1_process_level_precheck_required = False
            slot1_fallback_active = True
            _set_pending_win_confirmation_set_fallback_checks(betting_state, checks_remaining=2)
            if bet_debug_enabled:
                print(
                    "[DEBUG PROCESS] Accounting не успел обновиться после RES слот 1; продолжаем SET без финализации pending win.",
                    flush=True,
                )

    if betting_state_2 is not None:
        pending_confirmation_2 = betting_state_2.get("pending_win_confirmation")
        if isinstance(pending_confirmation_2, dict) and pending_confirmation_2:
            slot2_confirmation_outcome = await _wait_briefly_for_pending_win_confirmation(
                betting_state=betting_state_2,
                runtime_config=runtime_config,
                get_db_connection_func=get_db_connection_func,
                update_runtime_snapshot_func=update_runtime_snapshot_func,
                slot_label="2",
            )
            if slot2_confirmation_outcome == "pending":
                slot2_process_level_precheck_required = False
                slot2_fallback_active = True
                _set_pending_win_confirmation_set_fallback_checks(betting_state_2, checks_remaining=2)
                if bet_debug_enabled:
                    print(
                        "[DEBUG PROCESS] Accounting не успел обновиться после RES слот 2; продолжаем SET без финализации pending win.",
                        flush=True,
                    )

    try:
        if slot1_process_level_precheck_required and not _run_pending_win_confirmation_precheck(
            betting_state=betting_state,
            runtime_config=runtime_config,
            get_db_connection_func=get_db_connection_func,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            slot_label="1",
        ):
            if bet_debug_enabled:
                print("[DEBUG PROCESS] Ждём подтверждения выигрыша по accounting перед новым SET слот 1.", flush=True)
            return

        if (
            betting_state_2 is not None
            and slot2_process_level_precheck_required
            and not _run_pending_win_confirmation_precheck(
                betting_state=betting_state_2,
                runtime_config=runtime_config,
                get_db_connection_func=get_db_connection_func,
                update_runtime_snapshot_func=update_runtime_snapshot_func,
                slot_label="2",
            )
        ):
            if bet_debug_enabled:
                print("[DEBUG PROCESS] Ждём подтверждения выигрыша по accounting перед новым SET слот 2.", flush=True)
            return

        slot2_configured_tokens = set(runtime_context.get_configured_target_tokens_2())
        if bet_debug_enabled:
            print(f"[DEBUG PROCESS] DYNAMIC_BET_MODE={dynamic_bet_mode}, calling _update_dynamic_bet", flush=True)
        if dynamic_bet_mode:
            if bet_debug_enabled:
                print("[DEBUG PROCESS] Entering if DYNAMIC_BET_MODE, calling function", flush=True)
            if place_bets_2_func is not None and not multi_target_mode and slot2_configured_tokens:
                update_dynamic_bet_func(excluded_tokens=slot2_configured_tokens)
            else:
                update_dynamic_bet_func()

        bet_targets_to_place: tuple[BetTarget, ...]
        if dynamic_bet_mode:
            if multi_target_mode:
                dynamic_target_tokens = list(betting_state.get("dynamic_targets") or [])
                resolved_dynamic_targets = list(_resolve_target_tokens(dynamic_target_tokens))
                if resolved_dynamic_targets:
                    bet_targets_to_place = tuple(resolved_dynamic_targets)
                else:
                    bet_targets_to_place = configured_targets
            else:
                current_outcome, current_specifier = runtime_context.get_current_bet_target()
                bet_targets_to_place = (
                    BetTarget(outcome=current_outcome, specifier="" if current_outcome == "double" else current_specifier),
                )
        else:
            bet_targets_to_place = configured_targets

        _finalize_pending_win_confirmation_for_set_calculation_if_ready(
            betting_state=betting_state,
            runtime_config=runtime_config,
            get_db_connection_func=get_db_connection_func,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            slot_label="1",
        )

        consecutive_losses = betting_state.get("consecutive_losses", 0)
        random_fallback_enabled = runtime_config.dynamic_betting.random_fallback_enabled
        random_fallback_loss_streak = runtime_config.dynamic_betting.random_fallback_loss_streak
        if random_fallback_enabled and len(bet_targets_to_place) == 1 and consecutive_losses >= random_fallback_loss_streak:
            print("", flush=True)
            new_outcome, new_specifier = generate_random_bet_func()
            runtime_context.set_current_bet_target(new_outcome, new_specifier)
            betting_state["consecutive_losses"] = 0
            print("", flush=True)
            bet_targets_to_place = (
                BetTarget(outcome=new_outcome, specifier="" if new_outcome == "double" else new_specifier),
            )

        bet_amount = calculate_bet_amount_func()
        if (
            dynamic_bet_mode
            and not multi_target_mode
            and len(bet_targets_to_place) == 1
            and place_bets_2_func is not None
            and slot2_configured_tokens
        ):
            _resolved_slot1 = bet_targets_to_place[0]
            if _resolved_slot1.token in slot2_configured_tokens:
                _updated_outcome, _updated_specifier = runtime_context.get_current_bet_target()
                _updated_target = BetTarget(
                    outcome=_updated_outcome,
                    specifier="" if _updated_outcome == "double" else _updated_specifier,
                )
                if _updated_target.token != _resolved_slot1.token:
                    bet_targets_to_place = (_updated_target,)
                    if bet_debug_enabled:
                        print(
                            f"[ANTI-OVERLAP][1] Цель слота 1 {_resolved_slot1.token} пересекалась со слотом 2; "
                            f"берем следующий target из dynamic top: {_updated_target.token}",
                            flush=True,
                        )

        if bet_debug_enabled:
            print(
                f"[DEBUG PROCESS_BET] Вызов place_bets для {[target.token for target in bet_targets_to_place]} по {bet_amount:.0f}р на цель",
                flush=True,
            )
        slot2_targets_to_place: tuple[BetTarget, ...] = ()
        slot2_amount = 0.0

        shared_balance_for_slots = _normalize_account_balance((runtime_context.betting_state or {}).get("account_balance"))
        shared_percent_limit_balance: float | None = None
        if (
            bool(getattr(runtime_config.betting, "max_stake_percent_of_bank_shared", False))
            and shared_balance_for_slots is not None
            and float(getattr(runtime_config.betting, "max_stake_percent_of_bank", 0.0) or 0.0) > 0
        ):
            # Use deposit_balance for percent limit in deposit mode, otherwise use account_balance
            balance_for_percent_calc = shared_balance_for_slots
            if runtime_config.accounting.deposit_mode_enabled:
                deposit_bal = float((runtime_context.betting_state or {}).get("deposit_balance", 0.0) or 0.0)
                if deposit_bal > 0:
                    balance_for_percent_calc = deposit_bal
            
            shared_percent_limit_balance = balance_for_percent_calc * (
                float(getattr(runtime_config.betting, "max_stake_percent_of_bank", 0.0) or 0.0) / 100.0
            )

        if place_bets_2_func is not None and calculate_bet_amount_2_func is not None:
            slot1_target_tokens = {target.token for target in bet_targets_to_place}
            slot2_targets = runtime_context.get_configured_bet_targets_2()
            slot2_dynamic_mode = runtime_config.dynamic_betting.enabled_2

            if slot2_dynamic_mode:
                multi_target_mode_2 = len(slot2_targets) > 1
                dynamic_multi_effective_2 = multi_target_mode_2 and runtime_config.dynamic_betting.multi_target_enabled

                if dynamic_multi_effective_2:
                    if update_dynamic_bet_2_func is not None:
                        update_dynamic_bet_2_func(excluded_tokens=slot1_target_tokens)
                    slot2_dynamic_tokens = list((runtime_context.betting_state_2 or {}).get("dynamic_targets") or [])
                    resolved_dynamic_targets_2 = _resolve_target_tokens(slot2_dynamic_tokens)
                    if resolved_dynamic_targets_2:
                        slot2_targets = resolved_dynamic_targets_2
                else:
                    if update_dynamic_bet_2_func is not None:
                        update_dynamic_bet_2_func(excluded_tokens=slot1_target_tokens)
                    slot2_outcome, slot2_specifier = runtime_context.get_current_bet_target_2()
                    slot2_targets = (
                        BetTarget(
                            outcome=slot2_outcome,
                            specifier="" if slot2_outcome == "double" else slot2_specifier,
                        ),
                    )

            slot2_targets = tuple(target for target in slot2_targets if target.token not in slot1_target_tokens)
            if slot2_targets:
                slot2_targets_to_place = slot2_targets
                _finalize_pending_win_confirmation_for_set_calculation_if_ready(
                    betting_state=runtime_context.betting_state_2,
                    runtime_config=runtime_config,
                    get_db_connection_func=get_db_connection_func,
                    update_runtime_snapshot_func=update_runtime_snapshot_func,
                    slot_label="2",
                )
                slot2_amount = calculate_bet_amount_2_func()
            else:
                print(
                    "[WARNING][2] Все цели второго слота пересекаются с целями слота 1 в текущем раунде; слот 2 пропущен.",
                    flush=True,
                )

        combine_slots_in_single_post = bool(getattr(runtime_config.betting, "combine_slots_in_single_post", False))
        slot1_ready_for_combined = bool(bet_targets_to_place)
        slot2_ready_for_combined = bool(slot2_targets_to_place)
        should_attempt_combined_precheck = (
            combine_slots_in_single_post
            and place_bets_combined_slots_func is not None
            and slot1_ready_for_combined
            and slot2_ready_for_combined
        )

        if should_attempt_combined_precheck:
            shared_account_balance = _normalize_account_balance((runtime_context.betting_state or {}).get("account_balance"))
            if shared_account_balance is not None and runtime_context.betting_state_2 is not None:
                runtime_context.betting_state_2["account_balance"] = shared_account_balance
                runtime_context.betting_state_2["account_balance_updated_at"] = (runtime_context.betting_state or {}).get(
                    "account_balance_updated_at"
                )
                # In deposit mode, sync deposit_balance and saved_real_balance to slot2
                if runtime_config.accounting.deposit_mode_enabled:
                    runtime_context.betting_state_2["deposit_balance"] = (runtime_context.betting_state or {}).get("deposit_balance", 0.0)
                    runtime_context.betting_state_2["saved_real_balance"] = (runtime_context.betting_state or {}).get("saved_real_balance", 0.0)

            slot1_step_for_history = int((runtime_context.betting_state or {}).get("current_step", 0) or 0)
            slot2_step_for_history = int((runtime_context.betting_state_2 or {}).get("current_step", 0) or 0)
            slot1_max_steps = len((runtime_context.current_strategy or {}).get("coefficients", [1])) if runtime_context.current_strategy else 15
            slot2_max_steps = len((runtime_context.current_strategy_2 or {}).get("coefficients", [1])) if runtime_context.current_strategy_2 else 15
            slot1_round_display = str(int((runtime_context.betting_state or {}).get("total_bet_rounds", 0) or 0) + 1).zfill(3)
            slot2_round_display = str(int((runtime_context.betting_state_2 or {}).get("total_bet_rounds", 0) or 0) + 1).zfill(3)

            slot1_precheck_ok, slot1_effective_targets, slot1_effective_amount = _run_set_precheck_for_slot(
                betting_state=runtime_context.betting_state,
                current_strategy=runtime_context.current_strategy or {},
                amount=bet_amount,
                bet_targets=bet_targets_to_place,
                requested_targets=bet_targets_to_place,
                slot_label="1",
                step_for_history=slot1_step_for_history,
                max_steps=slot1_max_steps,
                next_round_display=slot1_round_display,
                runtime_config=runtime_config,
                calculate_roi_func=calculate_roi_func,
                format_outcome_pretty_func=format_outcome_pretty_func,
                format_bet_log_func=format_bet_log_func,
                get_balance_for_log_func=get_balance_for_log_func,
                get_db_connection_func=get_db_connection_func,
                update_runtime_snapshot_func=update_runtime_snapshot_func,
                required_bank_base_bet=float(getattr(runtime_config.betting, "base_bet", 0.0) or 0.0),
                resume_base_bet=float(getattr(runtime_config.betting, "base_bet", 0.0) or 0.0),
                available_balance_override=shared_percent_limit_balance,
            )
            if slot1_precheck_ok:
                bet_targets_to_place = slot1_effective_targets
                bet_amount = slot1_effective_amount
            else:
                bet_targets_to_place = ()

            def slot2_calculate_roi_func() -> float:
                if runtime_context.betting_state_2 and runtime_context.betting_state_2.get("total_bet_amount", 0) > 0:
                    return (
                        runtime_context.betting_state_2.get("total_profit", 0)
                        / runtime_context.betting_state_2.get("total_bet_amount", 1)
                        * 100
                    )
                return 0.0

            slot2_balance_override = shared_percent_limit_balance
            if slot1_precheck_ok and shared_percent_limit_balance is not None:
                slot1_total_amount = float(slot1_effective_amount) * float(len(slot1_effective_targets))
                slot2_balance_override = max(0.0, shared_percent_limit_balance - slot1_total_amount)

            slot2_precheck_ok, slot2_effective_targets, slot2_effective_amount = _run_set_precheck_for_slot(
                betting_state=runtime_context.betting_state_2,
                current_strategy=runtime_context.current_strategy_2 or {},
                amount=slot2_amount,
                bet_targets=slot2_targets_to_place,
                requested_targets=slot2_targets_to_place,
                slot_label="2",
                step_for_history=slot2_step_for_history,
                max_steps=slot2_max_steps,
                next_round_display=slot2_round_display,
                runtime_config=runtime_config,
                calculate_roi_func=slot2_calculate_roi_func,
                format_outcome_pretty_func=format_outcome_pretty_func,
                format_bet_log_func=format_bet_log_func,
                get_balance_for_log_func=get_balance_for_log_func,
                get_db_connection_func=get_db_connection_func,
                update_runtime_snapshot_func=update_runtime_snapshot_func,
                required_bank_base_bet=float(getattr(runtime_config.betting, "base_bet_2", 0.0) or 0.0),
                resume_base_bet=float(getattr(runtime_config.betting, "base_bet_2", 0.0) or 0.0),
                available_balance_override=slot2_balance_override,
            )
            if slot2_precheck_ok:
                slot2_targets_to_place = slot2_effective_targets
                slot2_amount = slot2_effective_amount
            else:
                slot2_targets_to_place = ()

            slot1_ready_for_combined = bool(bet_targets_to_place)
            slot2_ready_for_combined = bool(slot2_targets_to_place)
        else:
            slot1_precheck_ok = False
            slot1_effective_targets: tuple[BetTarget, ...] = ()
            slot1_effective_amount = 0.0
            if bet_targets_to_place:
                slot1_step_for_history = int((runtime_context.betting_state or {}).get("current_step", 0) or 0)
                slot1_max_steps = len((runtime_context.current_strategy or {}).get("coefficients", [1])) if runtime_context.current_strategy else 15
                slot1_round_display = str(int((runtime_context.betting_state or {}).get("total_bet_rounds", 0) or 0) + 1).zfill(3)
                slot1_precheck_ok, slot1_effective_targets, slot1_effective_amount = _run_set_precheck_for_slot(
                    betting_state=runtime_context.betting_state,
                    current_strategy=runtime_context.current_strategy or {},
                    amount=bet_amount,
                    bet_targets=bet_targets_to_place,
                    requested_targets=bet_targets_to_place,
                    slot_label="1",
                    step_for_history=slot1_step_for_history,
                    max_steps=slot1_max_steps,
                    next_round_display=slot1_round_display,
                    runtime_config=runtime_config,
                    calculate_roi_func=calculate_roi_func,
                    format_outcome_pretty_func=format_outcome_pretty_func,
                    format_bet_log_func=format_bet_log_func,
                    get_balance_for_log_func=get_balance_for_log_func,
                    get_db_connection_func=get_db_connection_func,
                    update_runtime_snapshot_func=update_runtime_snapshot_func,
                    required_bank_base_bet=float(getattr(runtime_config.betting, "base_bet", 0.0) or 0.0),
                    resume_base_bet=float(getattr(runtime_config.betting, "base_bet", 0.0) or 0.0),
                    available_balance_override=shared_percent_limit_balance,
                )
                if slot1_precheck_ok:
                    bet_targets_to_place = slot1_effective_targets
                    bet_amount = slot1_effective_amount
                else:
                    bet_targets_to_place = ()

            if slot2_targets_to_place and runtime_context.betting_state_2 is not None:
                def slot2_calculate_roi_func() -> float:
                    if runtime_context.betting_state_2 and runtime_context.betting_state_2.get("total_bet_amount", 0) > 0:
                        return (
                            runtime_context.betting_state_2.get("total_profit", 0)
                            / runtime_context.betting_state_2.get("total_bet_amount", 1)
                            * 100
                        )
                    return 0.0

                slot2_step_for_history = int((runtime_context.betting_state_2 or {}).get("current_step", 0) or 0)
                slot2_max_steps = len((runtime_context.current_strategy_2 or {}).get("coefficients", [1])) if runtime_context.current_strategy_2 else 15
                slot2_round_display = str(int((runtime_context.betting_state_2 or {}).get("total_bet_rounds", 0) or 0) + 1).zfill(3)
                slot2_balance_override = shared_percent_limit_balance
                if slot1_precheck_ok and shared_percent_limit_balance is not None:
                    slot1_total_amount = float(slot1_effective_amount) * float(len(slot1_effective_targets))
                    slot2_balance_override = max(0.0, shared_percent_limit_balance - slot1_total_amount)

                slot2_precheck_ok, slot2_effective_targets, slot2_effective_amount = _run_set_precheck_for_slot(
                    betting_state=runtime_context.betting_state_2,
                    current_strategy=runtime_context.current_strategy_2 or {},
                    amount=slot2_amount,
                    bet_targets=slot2_targets_to_place,
                    requested_targets=slot2_targets_to_place,
                    slot_label="2",
                    step_for_history=slot2_step_for_history,
                    max_steps=slot2_max_steps,
                    next_round_display=slot2_round_display,
                    runtime_config=runtime_config,
                    calculate_roi_func=slot2_calculate_roi_func,
                    format_outcome_pretty_func=format_outcome_pretty_func,
                    format_bet_log_func=format_bet_log_func,
                    get_balance_for_log_func=get_balance_for_log_func,
                    get_db_connection_func=get_db_connection_func,
                    update_runtime_snapshot_func=update_runtime_snapshot_func,
                    required_bank_base_bet=float(getattr(runtime_config.betting, "base_bet_2", 0.0) or 0.0),
                    resume_base_bet=float(getattr(runtime_config.betting, "base_bet_2", 0.0) or 0.0),
                    available_balance_override=slot2_balance_override,
                )
                if slot2_precheck_ok:
                    slot2_targets_to_place = slot2_effective_targets
                    slot2_amount = slot2_effective_amount
                else:
                    slot2_targets_to_place = ()

        shared_balance_for_slots = _normalize_account_balance((runtime_context.betting_state or {}).get("account_balance"))
        if shared_balance_for_slots is not None and bet_targets_to_place and slot2_targets_to_place:
            slot1_total_amount = float(bet_amount) * float(len(bet_targets_to_place))
            slot2_total_amount = float(slot2_amount) * float(len(slot2_targets_to_place))
            combined_total_amount = slot1_total_amount + slot2_total_amount

            if combined_total_amount > shared_balance_for_slots + 1e-9:
                slot1_affordable = slot1_total_amount <= shared_balance_for_slots + 1e-9
                slot2_affordable = slot2_total_amount <= shared_balance_for_slots + 1e-9

                skipped_slot = ""
                keep_slot = ""
                skipped_required_total = 0.0

                if slot1_affordable and not slot2_affordable:
                    slot2_targets_to_place = ()
                    slot2_amount = 0.0
                    skipped_slot = "2"
                    keep_slot = "1"
                    skipped_required_total = slot2_total_amount
                elif slot2_affordable and not slot1_affordable:
                    bet_targets_to_place = ()
                    bet_amount = 0.0
                    skipped_slot = "1"
                    keep_slot = "2"
                    skipped_required_total = slot1_total_amount
                elif slot1_affordable and slot2_affordable:
                    slot2_targets_to_place = ()
                    slot2_amount = 0.0
                    skipped_slot = "2"
                    keep_slot = "1"
                    skipped_required_total = slot2_total_amount
                else:
                    bet_targets_to_place = ()
                    slot2_targets_to_place = ()
                    bet_amount = 0.0
                    slot2_amount = 0.0
                    skipped_slot = "1+2"
                    keep_slot = "none"
                    skipped_required_total = min(slot1_total_amount, slot2_total_amount)

                _print_bet_system_log(
                    runtime_config=runtime_config,
                    event="set_skip_slot_shared_balance_limit",
                    level="info",
                    message=(
                        "[SET-CHECK] Недостаточно shared balance для двух слотов; "
                        f"пропускаем slot={skipped_slot}, размещаем slot={keep_slot}."
                    ),
                    extra={
                        "account_balance": shared_balance_for_slots,
                        "combined_required_total": combined_total_amount,
                        "slot1_required_total": slot1_total_amount,
                        "slot2_required_total": slot2_total_amount,
                        "skipped_slot": skipped_slot,
                        "kept_slot": keep_slot,
                        "skipped_required_total": skipped_required_total,
                    },
                )

                if bet_debug_enabled:
                    print(
                        (
                            "[DEBUG SHARED-BALANCE] "
                            f"balance={shared_balance_for_slots:.0f}р, "
                            f"slot1_total={slot1_total_amount:.0f}р, "
                            f"slot2_total={slot2_total_amount:.0f}р, "
                            f"kept={keep_slot}, skipped={skipped_slot}"
                        ),
                        flush=True,
                    )

        slot1_ready_for_combined = bool(bet_targets_to_place)
        slot2_ready_for_combined = bool(slot2_targets_to_place)

        can_use_combined_post = (
            combine_slots_in_single_post
            and place_bets_combined_slots_func is not None
            and slot1_ready_for_combined
            and slot2_ready_for_combined
        )

        if can_use_combined_post:
            if bet_debug_enabled:
                print(
                    (
                        "[DEBUG PROCESS_BET-COMBINED] Вызов combined POST: "
                        f"slot1={[target.token for target in bet_targets_to_place]} ({bet_amount:.0f}р), "
                        f"slot2={[t.token for t in slot2_targets_to_place]} ({slot2_amount:.0f}р)"
                    ),
                    flush=True,
                )
            await place_bets_combined_slots_func(
                page,
                slot1_targets=bet_targets_to_place,
                slot1_amount=bet_amount,
                slot2_targets=slot2_targets_to_place,
                slot2_amount=slot2_amount,
            )
            return

        if bet_targets_to_place:
            await place_bets_func(page, bet_targets_to_place, bet_amount)
        if slot2_targets_to_place and place_bets_2_func is not None:
            if bet_debug_enabled:
                print(
                    f"[DEBUG PROCESS_BET-2] Вызов place_bets_2 для {[t.token for t in slot2_targets_to_place]} по {slot2_amount:.0f}р",
                    flush=True,
                )
            await place_bets_2_func(page, slot2_targets_to_place, slot2_amount)
    finally:
        if slot1_fallback_active:
            _clear_pending_win_confirmation_set_fallback_checks(betting_state)
        if slot2_fallback_active and betting_state_2 is not None:
            _clear_pending_win_confirmation_set_fallback_checks(betting_state_2)
