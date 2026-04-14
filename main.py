"""
Patchright с одной постоянной сессией: данные профиля лежат в каталоге SESSION_DIR.
При каждом запуске используется тот же профиль; после закрытия браузера состояние остается на диске.
Сохранение данных в PostgreSQL вместо JSON.
Поддержка автоматического размещения ставок с различными стратегиями из YAML.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from buybaybye.betting import calculate_bet_amount as _betting_calculate_bet_amount
from buybaybye.betting import format_bet_log as _betting_format_bet_log
from buybaybye.betting import place_bet as _betting_place_bet
from buybaybye.betting import process_betting_round as _betting_process_betting_round
from buybaybye.accounting import get_accounting_age_seconds as _accounting_get_accounting_age_seconds
from buybaybye.accounting import get_balance_for_log as _accounting_get_balance_for_log
from buybaybye.accounting import is_account_balance_stale as _accounting_is_account_balance_stale
from buybaybye.accounting import monitor_accounting_ws_health as _accounting_monitor_accounting_ws_health
from buybaybye.accounting import record_accounting_rejection as _accounting_record_accounting_rejection
from buybaybye.accounting import reload_page_for_accounting_recovery as _accounting_reload_page_for_accounting_recovery
from buybaybye.accounting import update_balance_from_accounting_payload as _accounting_update_balance_from_accounting_payload
from buybaybye.browser_ws import wire_ws_logging as _browser_wire_ws_logging
from buybaybye.db import get_db_connection as _db_get_db_connection
from buybaybye.db import save_target_ws_message as _db_save_target_ws_message
from buybaybye.dynamic_betting import analyze_all_results_frequency as _dynamic_analyze_all_results_frequency
from buybaybye.dynamic_betting import analyze_recent_bets_stats as _dynamic_analyze_recent_bets_stats
from buybaybye.dynamic_betting import generate_random_bet as _dynamic_generate_random_bet
from buybaybye.dynamic_betting import get_best_combination as _dynamic_get_best_combination
from buybaybye.dynamic_betting import update_dynamic_bet as _dynamic_update_dynamic_bet
from buybaybye.jwt_capture import handle_request as _jwt_handle_request
from buybaybye.jwt_capture import handle_response as _jwt_handle_response
from buybaybye.jwt_capture import handle_response_async as _jwt_handle_response_async
from buybaybye.jwt_capture import subscribe_jwt_search_to_page as _jwt_subscribe_jwt_search_to_page
from buybaybye.log_formatting import format_combo_pretty as _format_combo_pretty
from buybaybye.log_formatting import format_outcome_pretty as _format_outcome_pretty
from buybaybye.log_formatting import format_result_pretty as _format_result_pretty
from buybaybye.log_formatting import format_round_result_pretty as _format_round_result_pretty
from buybaybye.log_formatting import pad_width_center as _pad_width_center
from buybaybye.notifications import is_telegram_chat_id_mode as _notifications_is_telegram_chat_id_mode
from buybaybye.notifications import queue_telegram_notification as _notifications_queue_telegram_notification
from buybaybye.notifications import run_telegram_chat_id_helper as _notifications_run_telegram_chat_id_helper
from buybaybye.reporting import print_dice_stats_20 as _reporting_print_dice_stats_20
from buybaybye.reporting import print_session_stats as _reporting_print_session_stats
from buybaybye.runtime_bootstrap import build_runtime_status_line as _runtime_build_status_line
from buybaybye.runtime_bootstrap import get_browser_launch_args as _runtime_get_browser_launch_args
from buybaybye.runtime_bootstrap import print_strategy_startup_info as _runtime_print_strategy_startup_info
from buybaybye.runtime_bootstrap import wait_for_exit_signal as _runtime_wait_for_exit_signal
from buybaybye.notifications import send_telegram_notification_sync as _notifications_send_telegram_notification_sync
from buybaybye.runtime_snapshot import build_runtime_snapshot as _runtime_build_snapshot
from buybaybye.runtime_snapshot import update_runtime_snapshot as _runtime_update_snapshot
from buybaybye.strategies import init_betting_state, load_strategies
from patchright.async_api import async_playwright

SESSION_DIR = Path(__file__).resolve().parent / "profile"
STRATEGIES_DIR = Path(__file__).resolve().parent / "strategies"
TARGET_WS_URL = "wss://ws.betboom.ru:444/api/nards_studio_ws/v1"
ACCOUNTING_WS_URL = "wss://ws.betboom.ru:444/api/accounting_ws/v1"
BET_API_URL = "https://game.betboom.ru/api/nards_studio_client/v1/bet"
HEADLESS = os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes", "on"}

# PostgreSQL config
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "buybaybye")

# Режим ставок
BET_MODE_ENABLED = os.getenv("BET_MODE", "false").lower() in {"1", "true", "yes", "on"}
BET_MODE_OUTCOME = os.getenv("BET_OUTCOME", "red")  # red или yellow
BET_MODE_SPECIFIER = os.getenv("BET_SPECIFIER", "5")  # значение кубика (1-6)
BASE_BET = float(os.getenv("BASE_BET", "10"))  # базовая ставка (должна делиться на 10)
STRATEGY_NAME = os.getenv("STRATEGY", "balanced")  # название стратегии

# Динамический режим изменения ставок на основе статистики
DYNAMIC_BET_MODE = os.getenv("DYNAMIC_BET_MODE", "false").lower() in {"1", "true", "yes", "on"}
DYNAMIC_WINDOW_SIZE = int(os.getenv("DYNAMIC_WINDOW_SIZE", "40"))  # размер окна анализа
DYNAMIC_RECALC_INTERVAL = int(os.getenv("DYNAMIC_RECALC_INTERVAL", "5"))  # как часто пересчитывать
DYNAMIC_USE_AVERAGE_VALUE_SELECTION = os.getenv("DYNAMIC_USE_AVERAGE_VALUE_SELECTION", "true").lower() in {"1", "true", "yes", "on"}
DYNAMIC_INCLUDE_DOUBLE_SELECTION = os.getenv("DYNAMIC_INCLUDE_DOUBLE_SELECTION", "true").lower() in {"1", "true", "yes", "on"}
DYNAMIC_FILTER_BY_PLAYER = os.getenv("DYNAMIC_FILTER_BY_PLAYER", "false").lower() in {"1", "true", "yes", "on"}
DYNAMIC_FILTER_BY_SIDE = os.getenv("DYNAMIC_FILTER_BY_SIDE", "false").lower() in {"1", "true", "yes", "on"}

# Accounting WS: stale-balance diagnostics and recovery
ACCOUNTING_BALANCE_STALE_SECONDS = float(os.getenv("ACCOUNTING_BALANCE_STALE_SECONDS", "15"))
ACCOUNTING_RECOVERY_RELOAD_SECONDS = float(os.getenv("ACCOUNTING_RECOVERY_RELOAD_SECONDS", "25"))
ACCOUNTING_RECOVERY_COOLDOWN_SECONDS = float(os.getenv("ACCOUNTING_RECOVERY_COOLDOWN_SECONDS", "30"))
ACCOUNTING_DEBUG_REJECTED_MESSAGES = os.getenv("ACCOUNTING_DEBUG_REJECTED_MESSAGES", "false").lower() in {"1", "true", "yes", "on"}

# Telegram notifications
TELEGRAM_NOTIFICATIONS_ENABLED = os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_REQUEST_TIMEOUT_SECONDS = float(os.getenv("TELEGRAM_REQUEST_TIMEOUT_SECONDS", "5"))
TELEGRAM_NOTIFICATION_COOLDOWN_SECONDS = float(os.getenv("TELEGRAM_NOTIFICATION_COOLDOWN_SECONDS", "60"))
TELEGRAM_NOTIFY_WITHDRAWALS = os.getenv("TELEGRAM_NOTIFY_WITHDRAWALS", "true").lower() in {"1", "true", "yes", "on"}
TELEGRAM_NOTIFY_ACCOUNTING_ISSUES = os.getenv("TELEGRAM_NOTIFY_ACCOUNTING_ISSUES", "true").lower() in {"1", "true", "yes", "on"}
TELEGRAM_NOTIFY_BET_ERRORS = os.getenv("TELEGRAM_NOTIFY_BET_ERRORS", "true").lower() in {"1", "true", "yes", "on"}
TELEGRAM_NOTIFY_AUTH_ISSUES = os.getenv("TELEGRAM_NOTIFY_AUTH_ISSUES", "true").lower() in {"1", "true", "yes", "on"}

# Случайная задержка перед ставкой (в секундах)
BET_DELAY_MIN = float(os.getenv("BET_DELAY_MIN", "0.8"))
BET_DELAY_MAX = float(os.getenv("BET_DELAY_MAX", "1.5"))

# Логирование WebSocket
WS_LOG_ENABLED = os.getenv("WS_LOG_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

# Логирование отладки ставок
BET_DEBUG_ENABLED = os.getenv("BET_DEBUG_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

# Цветной вывод в консоль
COLOR_ENABLED = os.getenv("COLOR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

# ANSI цветовые коды для консоли (будут использоваться только если COLOR_ENABLED=true)
COLOR_GREEN = "\033[92m" if COLOR_ENABLED else ""
COLOR_RED = "\033[91m" if COLOR_ENABLED else ""
COLOR_YELLOW = "\033[93m" if COLOR_ENABLED else ""
COLOR_CYAN = "\033[96m" if COLOR_ENABLED else ""
COLOR_BLUE = "\033[94m" if COLOR_ENABLED else ""
COLOR_MAGENTA = "\033[95m" if COLOR_ENABLED else ""
COLOR_RESET = "\033[0m" if COLOR_ENABLED else ""

# Хранилище загруженных стратегий
loaded_strategies = {}
current_strategy = None
jwt_token_global = None  # Глобальное хранилище найденного JWT токена
page_reload_lock: asyncio.Lock | None = None


def _set_jwt_token_global(token: str) -> None:
    global jwt_token_global
    jwt_token_global = token


def _get_jwt_token_global() -> str | None:
    return jwt_token_global


def _is_telegram_chat_id_mode() -> bool:
    return _notifications_is_telegram_chat_id_mode(sys.argv)


async def _run_telegram_chat_id_helper() -> None:
    await _notifications_run_telegram_chat_id_helper(TELEGRAM_BOT_TOKEN)


def _handle_response(response):
    _jwt_handle_response(response, handle_response_async_func=_handle_response_async)


async def _handle_response_async(response):
    await _jwt_handle_response_async(
        response,
        set_jwt_token_func=_set_jwt_token_global,
        color_cyan=COLOR_CYAN,
        color_reset=COLOR_RESET,
    )


def _handle_request(request):
    _jwt_handle_request(
        request,
        set_jwt_token_func=_set_jwt_token_global,
        color_cyan=COLOR_CYAN,
        color_reset=COLOR_RESET,
    )


def _subscribe_jwt_search_to_page(page) -> None:
    _jwt_subscribe_jwt_search_to_page(page, response_handler=_handle_response, request_handler=_handle_request)


def _is_forbidden_access_error(status_code: int, response_text: str) -> bool:
    """Проверить, является ли ответ ошибкой авторизации 403 FORBIDDEN."""
    if status_code != 403:
        return False

    try:
        payload = json.loads(response_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False

    if not isinstance(payload, dict):
        return False

    error = payload.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return payload.get("code") == 403 and payload.get("status") == "FORBIDDEN" and message == "Доступ запрещён"


async def _reload_page_and_refresh_token(page) -> bool:
    """Перезагрузить страницу и дождаться повторного получения JWT токена."""
    global jwt_token_global, page_reload_lock

    if page_reload_lock is None:
        page_reload_lock = asyncio.Lock()

    async with page_reload_lock:
        old_token = jwt_token_global
        jwt_token_global = None
        print("[AUTH] Получен 403 FORBIDDEN, перезагружаем страницу и обновляем JWT токен...", flush=True)

        try:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[AUTH] Ошибка перезагрузки страницы при обновлении токена: {e}", flush=True)
            return False

        deadline = asyncio.get_running_loop().time() + 20.0
        while asyncio.get_running_loop().time() < deadline:
            if jwt_token_global:
                token_changed = old_token is None or jwt_token_global != old_token
                change_note = "новый" if token_changed else "повторно получен"
                print(f"[AUTH] JWT токен {change_note} после перезагрузки страницы.", flush=True)
                return True
            await asyncio.sleep(0.25)

        print("[AUTH] JWT токен не был получен после перезагрузки страницы.", flush=True)
        return False


async def _reload_page_for_accounting_recovery(page, reason: str) -> bool:
    global page_reload_lock

    if page_reload_lock is None:
        page_reload_lock = asyncio.Lock()

    async with page_reload_lock:
        return await _accounting_reload_page_for_accounting_recovery(
            page,
            reason,
            betting_state=betting_state,
            get_balance_for_log_func=_get_balance_for_log,
            queue_telegram_notification_func=_queue_telegram_notification,
            notify_accounting_issues=TELEGRAM_NOTIFY_ACCOUNTING_ISSUES,
            update_runtime_snapshot_func=_update_runtime_snapshot,
        )

def _validate_base_bet(bet_amount: float) -> bool:
    """Проверить, делится ли ставка на 10 нацело"""
    return bet_amount % 10 == 0


def _advance_step_after_set_error() -> tuple[int, int, bool]:
    """Сдвинуть шаг стратегии после ошибки SET без изменения маржи.

    Деньги по неуспешной SET возвращаются, поэтому прибыль/баланс не трогаем,
    двигаем только прогрессию шагов.
    """
    max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
    curr = betting_state.get("current_step", 0)

    restarted = False
    if curr + 1 >= max_steps:
        betting_state["current_step"] = 0
        betting_state["consecutive_losses"] = 0
        restarted = True
    else:
        betting_state["current_step"] = curr + 1
        betting_state["consecutive_losses"] = betting_state.get("consecutive_losses", 0) + 1

    # Ставка фактически не была принята, не должна участвовать в RES следующего раунда.
    betting_state["last_bet_amount"] = 0
    return curr, max_steps, restarted


# Глобальное состояние для отслеживания ставок
betting_state = {}


def _get_db_connection():
    """Получить подключение к PostgreSQL с автоматическим созданием таблиц."""
    return _db_get_db_connection(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )


def _format_ws_payload(payload: object) -> str:
    if isinstance(payload, bytes):
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload.hex()
    return str(payload)


def _save_target_ws_message(payload: object) -> None:
    """Сохранить сообщение в PostgreSQL."""
    _db_save_target_ws_message(
        payload_text=_format_ws_payload(payload),
        get_db_connection_func=_get_db_connection,
    )


def _build_runtime_snapshot(event_type: str = "heartbeat", extra: dict | None = None) -> dict:
    return _runtime_build_snapshot(
        event_type=event_type,
        extra=extra,
        betting_state=betting_state,
        current_strategy=current_strategy,
        strategy_name=STRATEGY_NAME,
        bet_mode_enabled=BET_MODE_ENABLED,
        dynamic_bet_mode=DYNAMIC_BET_MODE,
        bet_mode_outcome=BET_MODE_OUTCOME,
        bet_mode_specifier=BET_MODE_SPECIFIER,
        dynamic_use_average_value_selection=DYNAMIC_USE_AVERAGE_VALUE_SELECTION,
        dynamic_include_double_selection=DYNAMIC_INCLUDE_DOUBLE_SELECTION,
        dynamic_filter_by_player=DYNAMIC_FILTER_BY_PLAYER,
        dynamic_filter_by_side=DYNAMIC_FILTER_BY_SIDE,
        is_account_balance_stale_func=_is_account_balance_stale,
    )


def _update_runtime_snapshot(event_type: str = "heartbeat", extra: dict | None = None) -> None:
    snapshot = _build_runtime_snapshot(event_type=event_type, extra=extra)
    _runtime_update_snapshot(
        get_db_connection_func=_get_db_connection,
        snapshot=snapshot,
        event_type=event_type,
    )


def _get_current_bet_target() -> tuple[str, str]:
    return BET_MODE_OUTCOME, BET_MODE_SPECIFIER


def _set_current_bet_target(outcome: str, specifier: str) -> None:
    global BET_MODE_OUTCOME, BET_MODE_SPECIFIER
    BET_MODE_OUTCOME = outcome
    BET_MODE_SPECIFIER = specifier


async def _place_bet(page, outcome: str, specifier: str, amount: float, allow_refresh_retry: bool = True) -> bool:
    return await _betting_place_bet(
        page,
        outcome,
        specifier,
        amount,
        allow_refresh_retry=allow_refresh_retry,
        betting_state=betting_state,
        current_strategy=current_strategy,
        strategy_name=STRATEGY_NAME,
        bet_api_url=BET_API_URL,
        jwt_token=jwt_token_global,
        get_jwt_token_func=_get_jwt_token_global,
        bet_delay_min=BET_DELAY_MIN,
        bet_delay_max=BET_DELAY_MAX,
        bet_debug_enabled=BET_DEBUG_ENABLED,
        telegram_notify_bet_errors=TELEGRAM_NOTIFY_BET_ERRORS,
        telegram_notify_auth_issues=TELEGRAM_NOTIFY_AUTH_ISSUES,
        validate_base_bet_func=_validate_base_bet,
        calculate_roi_func=_calculate_roi,
        format_outcome_pretty_func=_format_outcome_pretty,
        format_bet_log_func=_format_bet_log,
        get_balance_for_log_func=_get_balance_for_log,
        get_db_connection_func=_get_db_connection,
        is_forbidden_access_error_func=_is_forbidden_access_error,
        reload_page_and_refresh_token_func=_reload_page_and_refresh_token,
        advance_step_after_set_error_func=_advance_step_after_set_error,
        update_runtime_snapshot_func=_update_runtime_snapshot,
        queue_telegram_notification_func=_queue_telegram_notification,
    )


def _wire_ws_logging(page) -> None:
    _browser_wire_ws_logging(
        page,
        betting_state=betting_state,
        target_ws_url=TARGET_WS_URL,
        accounting_ws_url=ACCOUNTING_WS_URL,
        ws_log_enabled=WS_LOG_ENABLED,
        update_runtime_snapshot_func=_update_runtime_snapshot,
        format_ws_payload_func=_format_ws_payload,
        update_balance_from_accounting_payload_func=_update_balance_from_accounting_payload,
        save_target_ws_message_func=_save_target_ws_message,
        bet_mode_enabled=BET_MODE_ENABLED,
        process_betting_round_func=_process_betting_round,
    )


async def _monitor_accounting_ws_health(page) -> None:
    await _accounting_monitor_accounting_ws_health(
        page,
        betting_state=betting_state,
        recovery_cooldown_seconds=ACCOUNTING_RECOVERY_COOLDOWN_SECONDS,
        recovery_reload_seconds=ACCOUNTING_RECOVERY_RELOAD_SECONDS,
        get_accounting_age_seconds_func=_get_accounting_age_seconds,
        is_account_balance_stale_func=_is_account_balance_stale,
        reload_page_for_accounting_recovery_func=_reload_page_for_accounting_recovery,
    )


def _calculate_roi() -> float:
    total_bet = betting_state.get("total_bet_amount", 0)
    total_profit = betting_state.get("total_profit", 0)

    if total_bet == 0:
        return 0.0
    
    return (total_profit / total_bet) * 100


def _get_accounting_age_seconds(reference_key: str) -> float | None:
    return _accounting_get_accounting_age_seconds(betting_state=betting_state, reference_key=reference_key)


def _is_account_balance_stale() -> bool:
    return _accounting_is_account_balance_stale(
        betting_state=betting_state,
        stale_seconds=ACCOUNTING_BALANCE_STALE_SECONDS,
        get_accounting_age_seconds_func=_get_accounting_age_seconds,
    )


def _record_accounting_rejection(reason: str, payload_preview: str | None = None) -> None:
    _accounting_record_accounting_rejection(
        betting_state=betting_state,
        reason=reason,
        payload_preview=payload_preview,
        debug_rejected_messages=ACCOUNTING_DEBUG_REJECTED_MESSAGES,
        bet_debug_enabled=BET_DEBUG_ENABLED,
    )


def _send_telegram_notification_sync(title: str, message: str) -> None:
    _notifications_send_telegram_notification_sync(
        TELEGRAM_NOTIFICATIONS_ENABLED,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
        title,
        message,
    )


def _queue_telegram_notification(title: str, message: str, dedup_key: str, enabled: bool = True) -> None:
    _notifications_queue_telegram_notification(
        title=title,
        message=message,
        dedup_key=dedup_key,
        enabled=enabled,
        notifications_enabled=TELEGRAM_NOTIFICATIONS_ENABLED,
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
        cooldown_seconds=TELEGRAM_NOTIFICATION_COOLDOWN_SECONDS,
    )


def _get_balance_for_log() -> str:
    return _accounting_get_balance_for_log(
        betting_state=betting_state,
        is_account_balance_stale_func=_is_account_balance_stale,
    )


def _update_balance_from_accounting_payload(payload: object) -> None:
    _accounting_update_balance_from_accounting_payload(
        payload,
        betting_state=betting_state,
        format_ws_payload_func=_format_ws_payload,
        record_accounting_rejection_func=_record_accounting_rejection,
        update_runtime_snapshot_func=_update_runtime_snapshot,
        queue_telegram_notification_func=_queue_telegram_notification,
        notify_withdrawals=TELEGRAM_NOTIFY_WITHDRAWALS,
        bet_debug_enabled=BET_DEBUG_ENABLED,
    )


def _print_session_stats(checkpoint: int = 0) -> None:
    _reporting_print_session_stats(
        betting_state=betting_state,
        checkpoint=checkpoint,
        calculate_roi_func=_calculate_roi,
        color_cyan=COLOR_CYAN,
        color_magenta=COLOR_MAGENTA,
        color_yellow=COLOR_YELLOW,
        color_green=COLOR_GREEN,
        color_red=COLOR_RED,
        color_reset=COLOR_RESET,
    )


def _print_dice_stats_20() -> None:
    _reporting_print_dice_stats_20(
        betting_state=betting_state,
        color_cyan=COLOR_CYAN,
        color_magenta=COLOR_MAGENTA,
        color_red=COLOR_RED,
        color_yellow=COLOR_YELLOW,
        color_green=COLOR_GREEN,
        color_reset=COLOR_RESET,
        format_combo_pretty_func=_format_combo_pretty,
    )


def _format_bet_log(action: str, status_icon: str, outcome: str = "-", amount: str = "-", step: str = "-", 
                   result: str = "-", profit: str = "-", roi: str = "-", balance: str = "-",
                   real_balance: str = "-",
                   error_msg: str = "", bets_count: str = "") -> str:
    return _betting_format_bet_log(
        action=action,
        status_icon=status_icon,
        outcome=outcome,
        amount=amount,
        step=step,
        result=result,
        profit=profit,
        roi=roi,
        balance=balance,
        real_balance=real_balance,
        error_msg=error_msg,
        bets_count=bets_count,
        color_reset=COLOR_RESET,
        color_yellow=COLOR_YELLOW,
        color_green=COLOR_GREEN,
        color_red=COLOR_RED,
        color_magenta=COLOR_MAGENTA,
        color_cyan=COLOR_CYAN,
        pad_width_center_func=_pad_width_center,
        format_result_pretty_func=_format_result_pretty,
    )


async def _process_betting_round(page, payload: object) -> None:
    await _betting_process_betting_round(
        page,
        payload,
        betting_state=betting_state,
        current_strategy=current_strategy,
        dynamic_bet_mode=DYNAMIC_BET_MODE,
        bet_debug_enabled=BET_DEBUG_ENABLED,
        format_ws_payload_func=_format_ws_payload,
        get_db_connection_func=_get_db_connection,
        get_current_bet_target_func=_get_current_bet_target,
        set_current_bet_target_func=_set_current_bet_target,
        format_round_result_pretty_func=_format_round_result_pretty,
        format_outcome_pretty_func=_format_outcome_pretty,
        format_bet_log_func=_format_bet_log,
        get_balance_for_log_func=_get_balance_for_log,
        calculate_roi_func=_calculate_roi,
        update_runtime_snapshot_func=_update_runtime_snapshot,
        print_session_stats_func=_print_session_stats,
        print_dice_stats_20_func=_print_dice_stats_20,
        update_dynamic_bet_func=_update_dynamic_bet,
        generate_random_bet_func=_generate_random_bet,
        calculate_bet_amount_func=_calculate_bet_amount,
        place_bet_func=_place_bet,
    )


def _analyze_recent_bets_stats() -> dict:
    return _dynamic_analyze_recent_bets_stats(betting_state=betting_state)


def _analyze_all_results_frequency() -> dict:
    return _dynamic_analyze_all_results_frequency(
        betting_state=betting_state,
        db_host=DB_HOST,
        db_port=DB_PORT,
        db_user=DB_USER,
        db_password=DB_PASSWORD,
        db_name=DB_NAME,
        dynamic_window_size=DYNAMIC_WINDOW_SIZE,
        dynamic_filter_by_player=DYNAMIC_FILTER_BY_PLAYER,
        dynamic_filter_by_side=DYNAMIC_FILTER_BY_SIDE,
        bet_debug_enabled=BET_DEBUG_ENABLED,
    )


def _get_best_combination(stats: dict | None = None) -> tuple[str, str]:
    return _dynamic_get_best_combination(
        stats=stats,
        default_outcome=BET_MODE_OUTCOME,
        default_specifier=BET_MODE_SPECIFIER,
        dynamic_include_double_selection=DYNAMIC_INCLUDE_DOUBLE_SELECTION,
        dynamic_use_average_value_selection=DYNAMIC_USE_AVERAGE_VALUE_SELECTION,
        bet_debug_enabled=BET_DEBUG_ENABLED,
        analyze_all_results_frequency_func=_analyze_all_results_frequency,
    )


def _update_dynamic_bet() -> None:
    global BET_MODE_OUTCOME, BET_MODE_SPECIFIER
    BET_MODE_OUTCOME, BET_MODE_SPECIFIER = _dynamic_update_dynamic_bet(
        current_outcome=BET_MODE_OUTCOME,
        current_specifier=BET_MODE_SPECIFIER,
        betting_state=betting_state,
        dynamic_bet_mode=DYNAMIC_BET_MODE,
        dynamic_recalc_interval=DYNAMIC_RECALC_INTERVAL,
        dynamic_window_size=DYNAMIC_WINDOW_SIZE,
        dynamic_use_average_value_selection=DYNAMIC_USE_AVERAGE_VALUE_SELECTION,
        dynamic_include_double_selection=DYNAMIC_INCLUDE_DOUBLE_SELECTION,
        bet_debug_enabled=BET_DEBUG_ENABLED,
        color_cyan=COLOR_CYAN,
        color_reset=COLOR_RESET,
        analyze_all_results_frequency_func=_analyze_all_results_frequency,
        get_best_combination_func=_get_best_combination,
        format_outcome_pretty_func=_format_outcome_pretty,
        format_combo_pretty_func=_format_combo_pretty,
    )


def _generate_random_bet() -> tuple[str, str]:
    return _dynamic_generate_random_bet(
        color_magenta=COLOR_MAGENTA,
        color_reset=COLOR_RESET,
        format_outcome_pretty_func=_format_outcome_pretty,
    )


def _calculate_bet_amount() -> float:
    return _betting_calculate_bet_amount(
        base_bet=BASE_BET,
        betting_state=betting_state,
        current_strategy=current_strategy,
    )


async def _wait_for_exit_signal() -> None:
    await _runtime_wait_for_exit_signal()


async def main() -> None:
    global loaded_strategies, current_strategy, betting_state, page_reload_lock
    
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    
    # Загрузить все стратегии из YAML
    loaded_strategies = load_strategies(STRATEGIES_DIR, BASE_BET)
    
    # Валидировать базовую ставку
    if not _validate_base_bet(BASE_BET):
        print(f"[ERROR] BASE_BET ({BASE_BET}) должна делиться на 10 нацело", flush=True)
        sys.exit(1)
    
    # Выбрать текущую стратегию
    if BET_MODE_ENABLED:
        if STRATEGY_NAME not in loaded_strategies:
            print(f"[ERROR] Стратегия '{STRATEGY_NAME}' не найдена. Доступные:", flush=True)
            for name in loaded_strategies.keys():
                print(f"  - {name}: {loaded_strategies[name]['description']}", flush=True)
            sys.exit(1)
        
        current_strategy = loaded_strategies[STRATEGY_NAME]
        betting_state = init_betting_state(current_strategy, BET_MODE_OUTCOME, BET_MODE_SPECIFIER)
        _update_runtime_snapshot("startup")
        _runtime_print_strategy_startup_info(
            current_strategy=current_strategy,
            strategy_name=STRATEGY_NAME,
            base_bet=BASE_BET,
            dynamic_bet_mode=DYNAMIC_BET_MODE,
            dynamic_window_size=DYNAMIC_WINDOW_SIZE,
            dynamic_recalc_interval=DYNAMIC_RECALC_INTERVAL,
            dynamic_use_average_value_selection=DYNAMIC_USE_AVERAGE_VALUE_SELECTION,
            dynamic_include_double_selection=DYNAMIC_INCLUDE_DOUBLE_SELECTION,
            dynamic_filter_by_player=DYNAMIC_FILTER_BY_PLAYER,
            dynamic_filter_by_side=DYNAMIC_FILTER_BY_SIDE,
            bet_mode_outcome=BET_MODE_OUTCOME,
            bet_mode_specifier=BET_MODE_SPECIFIER,
            format_outcome_pretty_func=_format_outcome_pretty,
        )

    args = _runtime_get_browser_launch_args()

    playwright = await async_playwright().start()
    page_reload_lock = asyncio.Lock()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=HEADLESS,
        args=args,
    )
    accounting_monitor_task = None
    try:
        for existing_page in context.pages:
            _wire_ws_logging(existing_page)
            _subscribe_jwt_search_to_page(existing_page)
        
        context.on("page", _wire_ws_logging)
        context.on("page", _subscribe_jwt_search_to_page)

        page = context.pages[0] if context.pages else await context.new_page()
        
        print("[DEBUG] Поиск JWT токена в ответах...", flush=True)
        await page.goto("https://betboom.ru/game/nardsgame")
        accounting_monitor_task = asyncio.create_task(_monitor_accounting_ws_health(page))
        
        status_line = _runtime_build_status_line(
            session_dir=SESSION_DIR,
            bet_mode_enabled=BET_MODE_ENABLED,
            current_strategy=current_strategy,
            bet_mode_outcome=BET_MODE_OUTCOME,
            bet_mode_specifier=BET_MODE_SPECIFIER,
            base_bet=BASE_BET,
            bet_delay_min=BET_DELAY_MIN,
            bet_delay_max=BET_DELAY_MAX,
            accounting_balance_stale_seconds=ACCOUNTING_BALANCE_STALE_SECONDS,
            accounting_recovery_reload_seconds=ACCOUNTING_RECOVERY_RELOAD_SECONDS,
        )
        
        print(status_line, flush=True)
        await _wait_for_exit_signal()
    finally:
        if accounting_monitor_task is not None:
            accounting_monitor_task.cancel()
            try:
                await accounting_monitor_task
            except asyncio.CancelledError:
                pass
        await context.close()
        await playwright.stop()

    # Вывести итоговую статистику сессии
    if BET_MODE_ENABLED and betting_state:
        _print_session_stats()

    print("Контекст закрыт, профиль записан. Следующий запуск продолжит ту же сессию.", flush=True)


if __name__ == "__main__":
    try:
        if _is_telegram_chat_id_mode():
            asyncio.run(_run_telegram_chat_id_helper())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
