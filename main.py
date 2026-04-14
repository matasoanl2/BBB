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
import random
import re
import threading
import importlib.util
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from patchright.async_api import async_playwright
import psycopg2
from psycopg2.extras import Json
import yaml

# Optional dependency for accurate terminal character widths (emoji/CJK).
# We import per-character wcwidth() rather than the string-level wcswidth().
_wcwidth_char = None
if importlib.util.find_spec("wcwidth") is not None:
    _wcmod = importlib.import_module("wcwidth")
    _wcwidth_char = getattr(_wcmod, "wcwidth", None)

# Force known emoji/symbols to occupy 2 cells regardless of wcwidth.
# Enabled by default — most modern terminals render these as 2 columns.
FORCE_DOUBLE_WIDTH_EMOJI = os.getenv("FORCE_DOUBLE_WIDTH_EMOJI", "true").lower() in {"1", "true", "yes", "on"}

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
telegram_notification_timestamps: dict[str, float] = {}


def _is_telegram_chat_id_mode() -> bool:
    if len(sys.argv) < 2:
        return False
    return sys.argv[1].strip().lower() in {"telegram-chat-id", "telegram_chat_id", "tg-chat-id", "tg_chat_id"}


async def _send_telegram_notification_async(title: str, message: str) -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"{title}\n{message}",
            disable_web_page_preview=True,
        )
    finally:
        await bot.session.close()


async def _run_telegram_chat_id_helper() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("[TELEGRAM] TELEGRAM_BOT_TOKEN не задан. Заполните его в .env и повторите команду.", flush=True)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    router = Router()

    @router.message(Command("start", "chatid", "id"))
    async def handle_chat_id_command(message: Message) -> None:
        chat_id = str(message.chat.id)
        chat_type = message.chat.type
        chat_title = getattr(message.chat, "title", None) or getattr(message.chat, "full_name", None) or "-"
        username = message.from_user.username if message.from_user else None

        print(
            f"[TELEGRAM] chat_id={chat_id} type={chat_type} title={chat_title} username={username or '-'}",
            flush=True,
        )
        await message.answer(
            "Ваш TELEGRAM_CHAT_ID:\n"
            f"{chat_id}\n\n"
            f"Тип чата: {chat_type}\n"
            f"Название: {chat_title}\n\n"
            "Добавьте в .env:\n"
            f"TELEGRAM_CHAT_ID={chat_id}"
        )

    @router.message()
    async def handle_any_message(message: Message) -> None:
        await handle_chat_id_command(message)

    dp.include_router(router)

    print("[TELEGRAM] Режим получения TELEGRAM_CHAT_ID запущен.", flush=True)
    print("[TELEGRAM] Напишите боту /chatid или любое сообщение, чтобы получить chat_id.", flush=True)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()


def _handle_response(response):
    """
    Обработать ответ и поискать JWT токен в теле ответа
    JWT всегда начинается с eyJ в base64 кодировании
    Запускает асинхронную обработку в фоне
    """
    # Создать асинхронную задачу для обработки ответа
    asyncio.create_task(_handle_response_async(response))


async def _handle_response_async(response):
    """
    Асинхронная обработка ответа для поиска JWT токена
    """
    global jwt_token_global
    try:
        # Проверить заголовки ответа (Authorization, Set-Cookie, etc)
        auth_header = response.headers.get("authorization", "")
        if "eyJ" in auth_header:
            # Извлечь Bearer token из Authorization заголовка
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                if "." in token:
                    jwt_token_global = token
                    print(f"{COLOR_CYAN}🔥 JWT НАЙДЕН в заголовке Authorization: {token[:50]}...{COLOR_RESET}", flush=True)
                    return
        
        # Проверить тело ответа
        text = await response.text()
        if "eyJ" in text:
            # Попробовать найти JWT токен в ответе
            start_idx = text.find("eyJ")
            if start_idx != -1:
                end_idx = start_idx
                while end_idx < len(text) and (text[end_idx].isalnum() or text[end_idx] in '_-'):
                    end_idx += 1
                
                potential_token = text[start_idx:end_idx]
                if potential_token.count('.') >= 1:
                    jwt_token_global = potential_token
                    print(f"{COLOR_CYAN}🔥 JWT НАЙДЕН в теле ответа: {potential_token[:50]}...{COLOR_RESET}", flush=True)
    except Exception:
        pass  # Игнорируем ошибки при обработке ответа


def _handle_request(request):
    """
    Перехватить запрос и поискать JWT токен в URL, заголовках и теле запроса
    """
    global jwt_token_global
    try:
        # Проверить URL параметры (особенно token=...)
        url = request.url
        if "token=" in url:
            start_idx = url.find("token=") + 6
            end_idx = url.find("&", start_idx)
            if end_idx == -1:
                end_idx = len(url)
            
            potential_token = url[start_idx:end_idx]
            if "eyJ" in potential_token and potential_token.count('.') >= 1:
                jwt_token_global = potential_token
                print(f"{COLOR_CYAN}🔥 JWT НАЙДЕН в URL параметре: {potential_token[:50]}...{COLOR_RESET}", flush=True)
                return
        
        # Проверить заголовки запроса (Authorization, Referer содержит token, etc)
        auth_header = request.headers.get("Authorization", "")
        if "Bearer eyJ" in auth_header:
            token = auth_header.replace("Bearer ", "").strip()
            if "." in token:
                jwt_token_global = token
                print(f"{COLOR_CYAN}🔥 JWT НАЙДЕН в заголовке Authorization запроса: {token[:50]}...{COLOR_RESET}", flush=True)
                return
        
        # Проверить Referer заголовок (может содержать token в URL)
        referer = request.headers.get("Referer", "")
        if "token=" in referer:
            start_idx = referer.find("token=") + 6
            end_idx = referer.find("&", start_idx)
            if end_idx == -1:
                end_idx = len(referer)
            
            potential_token = referer[start_idx:end_idx]
            if "eyJ" in potential_token and potential_token.count('.') >= 1:
                jwt_token_global = potential_token
                print(f"{COLOR_CYAN}🔥 JWT НАЙДЕН в Referer заголовке: {potential_token[:50]}...{COLOR_RESET}", flush=True)
                return
        
        # Проверить тело запроса (если есть JSON с токеном)
        try:
            post_data = request.post_data
            if post_data and "eyJ" in post_data:
                # Попробовать найти JWT в JSON payload
                start_idx = post_data.find("eyJ")
                if start_idx != -1:
                    end_idx = start_idx
                    while end_idx < len(post_data) and (post_data[end_idx].isalnum() or post_data[end_idx] in '_-'):
                        end_idx += 1
                    
                    potential_token = post_data[start_idx:end_idx]
                    if potential_token.count('.') >= 1:
                        jwt_token_global = potential_token
                        print(f"{COLOR_CYAN}🔥 JWT НАЙДЕН в теле запроса: {potential_token[:50]}...{COLOR_RESET}", flush=True)
        except Exception:
            pass
    except Exception:
        pass  # Игнорируем ошибки


def _subscribe_jwt_search_to_page(page) -> None:
    """
    Подписать поиск JWT токена на события ответов и запросов страницы
    """
    page.on("response", _handle_response)
    page.on("request", _handle_request)


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
        if page.is_closed():
            return False

        print(f"[ACCOUNTING] Баланс устарел, перезагружаем страницу для восстановления канала ({reason})...", flush=True)
        _queue_telegram_notification(
            "[BuyBayBye] Проблема с accounting balance",
            f"Запущено восстановление accounting_ws.\nПричина: {reason}\nПоследний real balance: {_get_balance_for_log()}",
            dedup_key=f"accounting_recovery_start:{reason}",
            enabled=TELEGRAM_NOTIFY_ACCOUNTING_ISSUES,
        )
        try:
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[ACCOUNTING] Ошибка перезагрузки страницы при восстановлении accounting_ws: {e}", flush=True)
            _queue_telegram_notification(
                "[BuyBayBye] Ошибка восстановления accounting_ws",
                f"Page reload завершился ошибкой.\nПричина: {reason}\nОшибка: {e}",
                dedup_key=f"accounting_recovery_error:{reason}",
                enabled=TELEGRAM_NOTIFY_ACCOUNTING_ISSUES,
            )
            return False

        betting_state["last_accounting_recovery_at"] = datetime.now(timezone.utc).isoformat()
        betting_state["accounting_recovery_attempts"] = int(betting_state.get("accounting_recovery_attempts", 0) or 0) + 1
        _update_runtime_snapshot("accounting_recovery", {
            "accounting_recovery_reason": reason,
            "accounting_recovery_attempts": betting_state.get("accounting_recovery_attempts"),
        })
        _queue_telegram_notification(
            "[BuyBayBye] accounting_ws восстановлен",
            f"Перезагрузка страницы завершилась успешно.\nПричина: {reason}\nТекущий real balance: {_get_balance_for_log()}",
            dedup_key=f"accounting_recovery_success:{reason}",
            enabled=TELEGRAM_NOTIFY_ACCOUNTING_ISSUES,
        )
        return True

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


def _validate_strategy_coefficients(strategy_name: str, coefficients: list, base_bet: float) -> tuple[bool, str]:
    """
    Проверить, что все коэффициенты в стратегии при умножении на BASE_BET дают значения, делящиеся на 10
    
    Args:
        strategy_name: Название стратегии
        coefficients: Список коэффициентов
        base_bet: Базовая ставка
        
    Returns:
        (is_valid, error_message)
    """
    invalid_coefficients = []
    
    for i, coeff in enumerate(coefficients):
        bet_amount = base_bet * coeff
        # Проверяем, делится ли на 10 с допуском на ошибки округления
        if abs(bet_amount - round(bet_amount / 10) * 10) > 0.01:
            invalid_coefficients.append(f"  Step {i+1}: {coeff} × {base_bet} = {bet_amount} (не делится на 10)")
    
    if invalid_coefficients:
        error_msg = f"[ERROR] Стратегия '{strategy_name}' имеет неправильные коэффициенты:\n"
        error_msg += "\n".join(invalid_coefficients)
        error_msg += "\nВсе коэффициенты должны быть целыми числами, чтобы при умножении на BASE_BET (кратную 10) давать кратное 10"
        return False, error_msg
    
    return True, ""


def _load_strategies() -> dict:
    """Загрузить все стратегии из папки strategies/"""
    try:
        if not STRATEGIES_DIR.exists():
            print(f"[ERROR] Папка стратегий не найдена: {STRATEGIES_DIR}", flush=True)
            sys.exit(1)
        
        strategies = {}
        yaml_files = sorted(STRATEGIES_DIR.glob("*.yaml"))
        
        if not yaml_files:
            print(f"[ERROR] Не найдено файлов стратегий в {STRATEGIES_DIR}", flush=True)
            sys.exit(1)
        
        for yaml_file in yaml_files:
            try:
                strategy_key = yaml_file.stem  # имя файла без расширения
                
                with open(yaml_file, "r", encoding="utf-8") as f:
                    strategy_data = yaml.safe_load(f)
                
                coefficients = strategy_data.get("coefficients", [1])
                
                # Валидировать коэффициенты стратегии (проверить для BASE_BET)
                is_valid, error_msg = _validate_strategy_coefficients(strategy_key, coefficients, BASE_BET)
                if not is_valid:
                    print(error_msg, flush=True)
                    print(f"[WARNING] Пропуск стратегии {strategy_key}", flush=True)
                    continue
                
                strategies[strategy_key] = {
                    "name": strategy_data.get("name", strategy_key),
                    "description": strategy_data.get("description", ""),
                    "coefficients": coefficients,
                    "payout_coefficient": strategy_data.get("payout_coefficient", 5.7),
                    "reset_condition": strategy_data.get("reset_condition", "win"),
                }
                print(f"[LOAD] Загружена стратегия: {strategy_key}", flush=True)
            except Exception as e:
                print(f"[WARNING] Ошибка загрузки {yaml_file}: {e}", flush=True)
                continue
        
        if not strategies:
            print("[ERROR] Не удалось загрузить ни одну стратегию", flush=True)
            sys.exit(1)
        
        return strategies
    except Exception as e:
        print(f"[ERROR] Ошибка при загрузке стратегий: {e}", flush=True)
        sys.exit(1)


def _init_betting_state(strategy: dict) -> dict:
    """Инициализировать состояние ставок для текущей стратегии"""
    return {
        "current_step": 0,
        "consecutive_losses": 0,
        "session_balance": 0.0,
        "account_balance": None,  # Баланс из accounting_ws (если получен)
        "account_balance_type": None,
        "account_balance_updated_at": None,
        "last_accounting_ws_message_at": None,
        "last_accounting_ws_opened_at": None,
        "last_accounting_ws_closed_at": None,
        "accounting_ws_connected": False,
        "last_accounting_rejection_reason": None,
        "last_accounting_recovery_at": None,
        "accounting_recovery_attempts": 0,
        "pending_expected_bet_drop": 0.0,
        "external_withdrawals_total": 0.0,
        "last_bet_amount": 0.0,
        "last_set_amount": 0.0,
        "last_set_status": None,
        "last_set_error": None,
        "total_bet_amount": 0.0,
        "total_profit": 0.0,
        "total_bets_placed": 0,  # Общее количество совершенных ставок
        "last_round_result": None,
        "last_round_game_id": None,
        "last_round_status": None,
        "last_round_timestamp": None,
        "last_round_player_name": None,
        "last_round_position": None,
        "combo_stats": {
            "red_1": 0, "red_2": 0, "red_3": 0, "red_4": 0, "red_5": 0, "red_6": 0,
            "yellow_1": 0, "yellow_2": 0, "yellow_3": 0, "yellow_4": 0, "yellow_5": 0, "yellow_6": 0
        },
        "double_stats": {"doubles": 0, "no_doubles": 0},
        "reported_20_rounds": [],
        "recent_bets": [],  # Последние ставки для анализа динамического режима
        "dynamic_outcome": BET_MODE_OUTCOME,  # Текущий выбор для динамического режима
        "dynamic_specifier": BET_MODE_SPECIFIER,  # Текущее значение для динамического режима
        "strategy": strategy
    }


# Глобальное состояние для отслеживания ставок
betting_state = {}


def _get_db_connection():
    """Получить подключение к PostgreSQL с автоматическим созданием таблиц"""
    conn = psycopg2.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME
    )
    
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_results (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE,
            player_name TEXT,
            dice_results JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp ON game_results(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_player ON game_results(player_name)
    """)
    
    # Таблица истории ставок
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bet_history (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE,
            outcome TEXT,
            specifier TEXT,
            amount FLOAT,
            strategy TEXT,
            bet_step INTEGER,
            status TEXT,  -- "pending", "win", "loss", "error"
            result_dice_color TEXT,
            result_dice_value INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_bet_timestamp ON bet_history(timestamp)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runtime_snapshot (
            snapshot_key TEXT PRIMARY KEY,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            payload JSONB NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runtime_events (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            event_type TEXT,
            payload JSONB NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_runtime_events_timestamp ON runtime_events(timestamp)
    """)
    
    conn.commit()
    cursor.close()
    
    return conn


def _format_ws_payload(payload: object) -> str:
    if isinstance(payload, bytes):
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload.hex()
    return str(payload)


def _save_target_ws_message(payload: object) -> None:
    """Сохранить сообщение в PostgreSQL"""
    payload_text = _format_ws_payload(payload)
    try:
        parsed_payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if not isinstance(parsed_payload, dict):
        return
    if parsed_payload.get("status") != "rng_values":
        return

    results = parsed_payload.get("results")
    if not isinstance(results, dict):
        return

    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        
        player_name = results.get("player", {}).get("name", "unknown")
        timestamp = datetime.now(timezone.utc)
        
        cursor.execute("""
            INSERT INTO game_results (timestamp, player_name, dice_results)
            VALUES (%s, %s, %s)
        """, (timestamp, player_name, Json(results)))
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] Ошибка сохранения в БД: {e}", flush=True)


def _build_runtime_snapshot(event_type: str = "heartbeat", extra: dict | None = None) -> dict:
    strategy_name = STRATEGY_NAME if BET_MODE_ENABLED else None
    strategy_display_name = current_strategy.get("name") if current_strategy else None
    max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else None

    snapshot = {
        "event_type": event_type,
        "bet_mode_enabled": BET_MODE_ENABLED,
        "dynamic_bet_mode": DYNAMIC_BET_MODE,
        "strategy_name": strategy_name,
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
        "account_balance_is_stale": _is_account_balance_stale() if betting_state else False,
        "last_accounting_rejection_reason": betting_state.get("last_accounting_rejection_reason") if betting_state else None,
        "last_accounting_recovery_at": betting_state.get("last_accounting_recovery_at") if betting_state else None,
        "accounting_recovery_attempts": betting_state.get("accounting_recovery_attempts") if betting_state else 0,
        "total_profit": betting_state.get("total_profit") if betting_state else 0.0,
        "total_bet_amount": betting_state.get("total_bet_amount") if betting_state else 0.0,
        "total_bets_placed": betting_state.get("total_bets_placed") if betting_state else 0,
        "pending_expected_bet_drop": betting_state.get("pending_expected_bet_drop") if betting_state else 0.0,
        "external_withdrawals_total": betting_state.get("external_withdrawals_total") if betting_state else 0.0,
        "current_outcome": BET_MODE_OUTCOME if BET_MODE_ENABLED else None,
        "current_specifier": BET_MODE_SPECIFIER if BET_MODE_ENABLED else None,
        "dynamic_outcome": betting_state.get("dynamic_outcome") if betting_state else None,
        "dynamic_specifier": betting_state.get("dynamic_specifier") if betting_state else None,
        "dynamic_use_average_value_selection": DYNAMIC_USE_AVERAGE_VALUE_SELECTION,
        "dynamic_include_double_selection": DYNAMIC_INCLUDE_DOUBLE_SELECTION,
        "dynamic_filter_by_player": DYNAMIC_FILTER_BY_PLAYER,
        "dynamic_filter_by_side": DYNAMIC_FILTER_BY_SIDE,
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


def _update_runtime_snapshot(event_type: str = "heartbeat", extra: dict | None = None) -> None:
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()
        snapshot = _build_runtime_snapshot(event_type=event_type, extra=extra)
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
    except Exception as e:
        print(f"[DB ERROR] Ошибка обновления runtime_snapshot: {e}", flush=True)


async def _place_bet(page, outcome: str, specifier: str, amount: float, allow_refresh_retry: bool = True) -> bool:
    """
    Разместить ставку через API betboom используя браузер (page.request)
    
    Преимущества использования браузера:
    - Автоматически передаются все cookies и токены
    - Используется правильный User-Agent
    - Следует всем редиректам
    - Избегает обнаружения как бот
    
    Args:
        page: Объект страницы Playwright
        outcome: "red" или "yellow"
        specifier: значение кубика (1-6)
        amount: сумма ставки
        
    Returns:
        True если ставка успешна, False иначе
    """
    requested_specifier = specifier

    # Проверить что JWT токен найден перед размещением ставки
    global jwt_token_global
    if not jwt_token_global:
        print("[WARNING] JWT токен ещё не найден! Ставка НЕ будет размещена.", flush=True)
        _advance_step_after_set_error()
        return False
    
    # Отладка: показать какую ставку мы размещаем
    if BET_DEBUG_ENABLED:
        print(f"[DEBUG PLACE_BET] outcome={outcome}, specifier={specifier}, amount={amount}", flush=True)
    
    # Валидировать, что ставка делится на 10 нацело
    if not _validate_base_bet(amount):
        print(f"[ERROR] Ставка {amount}р ДОЛЖНА делиться на 10 нацело! Ставка НЕ размещена.", flush=True)
        _advance_step_after_set_error()
        return False
    
    try:
        step_for_history = betting_state.get('current_step', 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15

        # Проверка доступного баланса перед отправкой ставки.
        # Важно: на первой ставке balance из accounting_ws может быть еще неизвестен.
        available_balance = betting_state.get("account_balance")
        if available_balance is None:
            if BET_DEBUG_ENABLED and betting_state.get("total_bets_placed", 0) == 0:
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
            roi = _calculate_roi()
            log_line = _format_bet_log(
                action="SET",
                status_icon="❌",
                outcome=_format_outcome_pretty(outcome, specifier),
                amount=f"{amount}р",
                step=f"{step_for_history+1}/{max_steps}",
                result="SKIP",
                profit="-",
                roi=f"{roi:.2f}%",
                balance=f"{betting_state.get('session_balance', 0):.0f}р",
                real_balance=_get_balance_for_log(),
                error_msg=f"Ставка пропущена: {amount:.0f}р > баланс {available_balance:.0f}р (accounting_ws)",
                bets_count=str(betting_state.get('total_bets_placed', 0)).zfill(3)
            )
            print(log_line, flush=True)

            try:
                conn = _get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (datetime.now(timezone.utc), outcome, specifier, amount, STRATEGY_NAME, step_for_history, "skipped_insufficient_balance"))
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as db_err:
                print(f"[DB ERROR] Ошибка сохранения пропущенной ставки: {db_err}", flush=True)

            old_step, max_steps, restarted = _advance_step_after_set_error()
            if BET_DEBUG_ENABLED:
                new_step = betting_state.get("current_step", 0)
                restart_note = " [♻️ RESTART]" if restarted else ""
                print(f"[SET-SKIP] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
            _update_runtime_snapshot("bet_skipped", {
                "last_set_amount": amount,
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
            })
            return False

    except Exception as e:
        betting_state["last_set_status"] = "precheck_error"
        betting_state["last_set_error"] = str(e)[:100]
        roi = _calculate_roi()
        log_line = _format_bet_log(
            action="SET",
            status_icon="❌",
            outcome="-",
            amount="-",
            step="-",
            result="ERROR",
            profit="-",
            roi=f"{roi:.2f}%",
            balance=f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=_get_balance_for_log(),
            error_msg=str(e)[:100],
            bets_count=str(betting_state.get('total_bets_placed', 0)).zfill(3)
        )
        print(log_line, flush=True)
        old_step, max_steps, restarted = _advance_step_after_set_error()
        if BET_DEBUG_ENABLED:
            new_step = betting_state.get("current_step", 0)
            restart_note = " [♻️ RESTART]" if restarted else ""
            print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
        _update_runtime_snapshot("bet_precheck_error", {
            "last_set_status": betting_state.get("last_set_status"),
            "last_set_error": betting_state.get("last_set_error"),
        })
        return False

    # Случайная задержка "человеческого" поведения
    delay = random.uniform(BET_DELAY_MIN, BET_DELAY_MAX)
    await asyncio.sleep(delay)
    
    try:
        step_for_history = betting_state.get('current_step', 0)
        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15

        # Подготовить payload для ставки
        # Проверить тип ставки (цвет или дубль)
        if outcome == "double":
            # Дубль ставка (любой дубль - когда оба кубика равны)
            bet_payload = {
                "market": "gtlt",
                "outcome": "double",
                "specifier": "",
                "sum": amount,
                "balance_type": "balance"
            }
            specifier = outcome
        else:
            # Цветная ставка
            bet_payload = {
                "market": "value",
                "outcome": outcome,
                "specifier": specifier,
                "sum": amount,
                "balance_type": "balance"
            }
        
        payload = {
            "bets": [bet_payload]
        }
        
        # Отправить ставку через браузер (page.request)
        # Это автоматически использует cookies и контекст браузера
        
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://betboom.ru/game/nardsgame",
            "Origin": "https://betboom.ru",
            "X-Requested-With": "XMLHttpRequest"
        }
        
        # Добавить JWT токен в заголовок если он найден
        if jwt_token_global:
            headers["X-Access-Token"] = jwt_token_global
        
        response = await page.request.post(
            BET_API_URL,
            data=json.dumps(payload),
            headers=headers
        )
        
        status_code = response.status
        response_text = await response.text()
        
        # Если API вернул ошибку в теле ответа (code в JSON), переопределить status_code ДО логирования
        try:
            response_json = json.loads(response_text)
            if isinstance(response_json, dict) and "code" in response_json:
                status_code = response_json["code"]
        except (json.JSONDecodeError, ValueError):
            pass  # Если не JSON или ошибка парсинга, используем HTTP status_code
        
        # Логирование отправленного запроса и ответа (если BET_DEBUG_ENABLED)
        if BET_DEBUG_ENABLED:
            print("[DEBUG] ========== BET REQUEST ==========", flush=True)
            print(f"[DEBUG] Page URL: {page.url}", flush=True)
            print(f"[DEBUG] API URL: {BET_API_URL}", flush=True)
            print(f"[DEBUG] Payload: {json.dumps(payload)}", flush=True)
            print(f"[DEBUG] Headers sent: {json.dumps({k: v[:50] + '...' if len(str(v)) > 50 else v for k, v in headers.items()})}", flush=True)
            print(f"[DEBUG] Response Status: {status_code}", flush=True)
            print(f"[DEBUG] Response Body: {response_text}", flush=True)
            print("[DEBUG] ==================================", flush=True)
            
            if status_code != 200:
                print(f"[DEBUG] Статус: {status_code}", flush=True)
                print(f"[DEBUG] Ответ: {response_text[:500]}", flush=True)
                print(f"[DEBUG] Headers: {dict(response.headers)}", flush=True)

        # Сохранить информацию о ставке в БД
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()
            should_refresh_token = _is_forbidden_access_error(status_code, response_text)
            
            if status_code == 200:
                bet_status = "pending"
                # Обновить общую сумму ставок для ROI расчета и счетчик ставок
                betting_state["total_bet_amount"] += amount
                betting_state["total_bets_placed"] += 1
                # В игре одновременно активна только одна ставка, поэтому ожидаем
                # только одно списание реального баланса на сумму текущего SET.
                betting_state["pending_expected_bet_drop"] = amount
                betting_state["last_set_amount"] = amount
                betting_state["last_set_status"] = "pending"
                betting_state["last_set_error"] = None

                payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
                potential_win = amount * payout_coeff
                potential_margin = potential_win - amount
                roi = _calculate_roi()
                
                # SET ✓ успешная установка ставки - вся строка желтая
                log_line = _format_bet_log(
                    action="SET",
                    status_icon="✅",
                    outcome=_format_outcome_pretty(outcome, specifier),
                    amount=f"{amount}р",
                    step=f"{step_for_history+1}/{max_steps}",
                    result="------",
                    profit=f"+{potential_margin:.0f}р",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=_get_balance_for_log(),
                    bets_count=str(betting_state.get('total_bets_placed', 0)).zfill(3)
                )
                print(log_line, flush=True)
            else:
                bet_status = "error"
                betting_state["last_set_amount"] = amount
                betting_state["last_set_status"] = "forbidden_refresh" if should_refresh_token else "error"
                betting_state["last_set_error"] = response_text[:100] if response_text else "Unknown error"

                if should_refresh_token and allow_refresh_retry:
                    token_refreshed = await _reload_page_and_refresh_token(page)
                    if token_refreshed:
                        betting_state["last_set_status"] = "retry_after_refresh"
                        betting_state["last_set_error"] = None
                        _update_runtime_snapshot("bet_token_refreshed", {
                            "last_set_amount": amount,
                            "last_set_status": betting_state.get("last_set_status"),
                            "token_refresh_triggered": True,
                        })
                        cursor.close()
                        conn.close()
                        print("[AUTH] Повторяем ставку один раз после обновления токена.", flush=True)
                        return await _place_bet(page, outcome, requested_specifier, amount, allow_refresh_retry=False)
                    _queue_telegram_notification(
                        "[BuyBayBye] Ошибка авторизации ставки",
                        f"403 FORBIDDEN, обновление JWT не помогло.\nСтавка: {_format_outcome_pretty(outcome, requested_specifier)}\nСумма: {amount:.0f}р",
                        dedup_key="auth_refresh_failed",
                        enabled=TELEGRAM_NOTIFY_AUTH_ISSUES,
                    )

                roi = _calculate_roi()
                log_line = _format_bet_log(
                    action="SET",
                    status_icon="❌",
                    outcome=_format_outcome_pretty(outcome, specifier),
                    amount=f"{amount}р",
                    step=f"{step_for_history+1}/{max_steps}",
                    result="ERROR",
                    profit="-",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state.get('session_balance', 0):.0f}р",
                    real_balance=_get_balance_for_log(),
                    error_msg=response_text[:100] if response_text else "Unknown error",
                    bets_count=str(betting_state.get('total_bets_placed', 0)).zfill(3)
                )
                print(log_line, flush=True)
                old_step, max_steps, restarted = _advance_step_after_set_error()
                if BET_DEBUG_ENABLED:
                    new_step = betting_state.get("current_step", 0)
                    restart_note = " [♻️ RESTART]" if restarted else ""
                    print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
                if should_refresh_token:
                    betting_state["last_set_error"] = "403 FORBIDDEN -> token refresh failed"

            _update_runtime_snapshot("bet_set", {
                "last_set_amount": amount,
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
                "http_status": status_code,
                "token_refresh_triggered": should_refresh_token,
            })
            
            cursor.execute("""
                INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (datetime.now(timezone.utc), outcome, specifier, amount, STRATEGY_NAME, step_for_history, bet_status))
            
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            betting_state["last_set_status"] = "db_error"
            betting_state["last_set_error"] = str(e)[:100]
            roi = _calculate_roi()
            log_line = _format_bet_log(
                action="SET",
                status_icon="❌",
                outcome="-",
                amount="-",
                step="-",
                result="DB_ERROR",
                profit="-",
                roi=f"{roi:.2f}%",
                balance=_get_balance_for_log(),
                error_msg=str(e)[:100],
                bets_count=str(betting_state.get('total_bets_placed', 0)).zfill(3)
            )
            print(log_line, flush=True)
            _queue_telegram_notification(
                "[BuyBayBye] Ошибка сохранения ставки",
                f"Не удалось записать ставку в БД.\nСтавка: {_format_outcome_pretty(outcome, specifier)}\nСумма: {amount:.0f}р\nОшибка: {str(e)[:300]}",
                dedup_key="bet_db_error",
                enabled=TELEGRAM_NOTIFY_BET_ERRORS,
            )
            _update_runtime_snapshot("bet_db_error", {
                "last_set_status": betting_state.get("last_set_status"),
                "last_set_error": betting_state.get("last_set_error"),
            })
        
        return status_code == 200
                    
    except Exception as e:
        betting_state["last_set_status"] = "request_error"
        betting_state["last_set_error"] = str(e)[:100]
        roi = _calculate_roi()
        log_line = _format_bet_log(
            action="SET",
            status_icon="❌",
            outcome="-",
            amount="-",
            step="-",
            result="ERROR",
            profit="-",
            roi=f"{roi:.2f}%",
            balance=f"{betting_state.get('session_balance', 0):.0f}р",
            real_balance=_get_balance_for_log(),
            error_msg=str(e)[:100],
            bets_count=str(betting_state.get('total_bets_placed', 0)).zfill(3)
        )
        print(log_line, flush=True)
        _queue_telegram_notification(
            "[BuyBayBye] Ошибка запроса ставки",
            f"Запрос на размещение ставки завершился ошибкой.\nСтавка: {_format_outcome_pretty(outcome, requested_specifier)}\nСумма: {amount:.0f}р\nОшибка: {str(e)[:300]}",
            dedup_key="bet_request_error",
            enabled=TELEGRAM_NOTIFY_BET_ERRORS,
        )
        old_step, max_steps, restarted = _advance_step_after_set_error()
        if BET_DEBUG_ENABLED:
            new_step = betting_state.get("current_step", 0)
            restart_note = " [♻️ RESTART]" if restarted else ""
            print(f"[SET-ERROR] Шаг сдвинут: {old_step+1}/{max_steps} -> {new_step+1}/{max_steps}{restart_note}", flush=True)
        _update_runtime_snapshot("bet_request_error", {
            "last_set_status": betting_state.get("last_set_status"),
            "last_set_error": betting_state.get("last_set_error"),
        })
        return False


def _wire_ws_logging(page) -> None:
    def on_websocket(ws) -> None:
        is_target = ws.url.startswith(TARGET_WS_URL)
        is_accounting = ws.url.startswith(ACCOUNTING_WS_URL)
        tag = "TARGET-WS" if is_target else "WS"
        if is_accounting:
            betting_state["accounting_ws_connected"] = True
            betting_state["last_accounting_ws_opened_at"] = datetime.now(timezone.utc).isoformat()
            _update_runtime_snapshot("accounting_ws_open")
        if WS_LOG_ENABLED:
            print(f"[{tag} OPEN] {ws.url}", flush=True)

        def on_sent(payload) -> None:
            if WS_LOG_ENABLED:
                print(f"[{tag} >>] {_format_ws_payload(payload)}", flush=True)

        def on_received(payload) -> None:
            if WS_LOG_ENABLED:
                print(f"[{tag} <<] {_format_ws_payload(payload)}", flush=True)

            if is_accounting:
                _update_balance_from_accounting_payload(payload)

            if is_target:
                # Сохранить результат раунда
                _save_target_ws_message(payload)
                
                # Если включен режим ставок, заполнить результат предыдущей ставки + разместить новую
                if BET_MODE_ENABLED:
                    asyncio.create_task(_process_betting_round(page, payload))

        def on_close(*_) -> None:
            if is_accounting:
                betting_state["accounting_ws_connected"] = False
                betting_state["last_accounting_ws_closed_at"] = datetime.now(timezone.utc).isoformat()
                _update_runtime_snapshot("accounting_ws_close")
            if WS_LOG_ENABLED:
                print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)


async def _monitor_accounting_ws_health(page) -> None:
    while True:
        await asyncio.sleep(3.0)

        if page.is_closed():
            return

        last_recovery_age = _get_accounting_age_seconds("last_accounting_recovery_at")
        if last_recovery_age is not None and last_recovery_age < ACCOUNTING_RECOVERY_COOLDOWN_SECONDS:
            continue

        ws_age = _get_accounting_age_seconds("last_accounting_ws_message_at")
        balance_age = _get_accounting_age_seconds("account_balance_updated_at")

        reason = None
        if betting_state.get("accounting_ws_connected") is False and betting_state.get("last_accounting_ws_closed_at"):
            reason = "accounting_ws closed"
        elif _is_account_balance_stale() and balance_age is not None and balance_age >= ACCOUNTING_RECOVERY_RELOAD_SECONDS:
            reason = f"balance_update stale for {balance_age:.0f}s"
        elif betting_state.get("account_balance") is not None and ws_age is not None and ws_age >= ACCOUNTING_RECOVERY_RELOAD_SECONDS and float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0) > 0:
            reason = f"no accounting messages for {ws_age:.0f}s"

        if reason:
            await _reload_page_for_accounting_recovery(page, reason)


def _calculate_roi() -> float:
    total_bet = betting_state.get("total_bet_amount", 0)
    total_profit = betting_state.get("total_profit", 0)

    if total_bet == 0:
        return 0.0
    
    return (total_profit / total_bet) * 100


def _get_accounting_age_seconds(reference_key: str) -> float | None:
    raw_value = betting_state.get(reference_key)
    if not raw_value:
        return None
    try:
        timestamp = datetime.fromisoformat(raw_value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())


def _is_account_balance_stale() -> bool:
    if not betting_state:
        return False
    if betting_state.get("account_balance") is None:
        return False
    if betting_state.get("accounting_ws_connected") is False and betting_state.get("last_accounting_ws_closed_at"):
        return True

    pending_drop = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0)
    if pending_drop <= 0:
        return False

    age_seconds = _get_accounting_age_seconds("account_balance_updated_at")
    if age_seconds is None:
        return True
    return age_seconds >= ACCOUNTING_BALANCE_STALE_SECONDS


def _record_accounting_rejection(reason: str, payload_preview: str | None = None) -> None:
    betting_state["last_accounting_rejection_reason"] = reason
    if ACCOUNTING_DEBUG_REJECTED_MESSAGES or BET_DEBUG_ENABLED:
        preview = f" | payload={payload_preview[:220]}" if payload_preview else ""
        print(f"[ACCOUNTING][SKIP] {reason}{preview}", flush=True)


def _send_telegram_notification_sync(title: str, message: str) -> None:
    if not TELEGRAM_NOTIFICATIONS_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        asyncio.run(_send_telegram_notification_async(title, message))
    except Exception as e:
        print(f"[TELEGRAM] Ошибка отправки уведомления: {e}", flush=True)


def _queue_telegram_notification(title: str, message: str, dedup_key: str, enabled: bool = True) -> None:
    if not enabled or not TELEGRAM_NOTIFICATIONS_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    last_ts = telegram_notification_timestamps.get(dedup_key)
    if last_ts is not None and now_ts - last_ts < TELEGRAM_NOTIFICATION_COOLDOWN_SECONDS:
        return

    telegram_notification_timestamps[dedup_key] = now_ts
    threading.Thread(
        target=_send_telegram_notification_sync,
        args=(title, message),
        daemon=True,
    ).start()


def _get_balance_for_log() -> str:
    """Вернуть баланс для логов: приоритет у real-time balance из accounting_ws."""
    account_balance = betting_state.get("account_balance")
    if account_balance is not None:
        suffix = " !" if _is_account_balance_stale() else ""
        return f"{account_balance:.0f}р{suffix}"
    return f"{betting_state.get('session_balance', 0):.0f}р"


def _update_balance_from_accounting_payload(payload: object) -> None:
    """Обновить баланс из сообщения accounting_ws вида balance_update."""
    global betting_state
    try:
        payload_text = _format_ws_payload(payload)
        data = json.loads(payload_text)
    except Exception:
        _record_accounting_rejection("payload is not valid JSON")
        return

    betting_state["last_accounting_ws_message_at"] = datetime.now(timezone.utc).isoformat()

    if not isinstance(data, dict):
        _record_accounting_rejection("payload root is not an object", payload_text)
        return
    if data.get("type") != "balance_update":
        _record_accounting_rejection(f"ignored message type={data.get('type')}", payload_text)
        return

    balance_update = data.get("balance_update")
    if not isinstance(balance_update, dict):
        _record_accounting_rejection("balance_update field is missing or not an object", payload_text)
        return
    if balance_update.get("code") != 200:
        _record_accounting_rejection(f"balance_update.code={balance_update.get('code')}", payload_text)
        return

    # По фактическим payload в этой сессии денежный баланс приходит как balance_type=1.
    # Поток с balance_type=0 может содержать нулевое значение и затирать реальный баланс.
    balance_type = balance_update.get("balance_type")
    try:
        normalized_balance_type = int(balance_type)
    except (TypeError, ValueError):
        _record_accounting_rejection(f"invalid balance_type={balance_type}", payload_text)
        return

    if normalized_balance_type != 1:
        _record_accounting_rejection(f"ignored balance_type={normalized_balance_type}", payload_text)
        return

    value = balance_update.get("value")
    if not isinstance(value, (int, float)):
        _record_accounting_rejection(f"non-numeric balance value={value}", payload_text)
        return

    new_balance = float(value)
    previous_balance = betting_state.get("account_balance")
    pending_expected_bet_drop = float(betting_state.get("pending_expected_bet_drop", 0.0) or 0.0)
    withdrawal_detected = False

    if isinstance(previous_balance, (int, float)) and new_balance < previous_balance:
        actual_drop = float(previous_balance) - new_balance
        covered_by_bet = min(actual_drop, pending_expected_bet_drop)
        pending_expected_bet_drop -= covered_by_bet
        withdrawal_amount = actual_drop - covered_by_bet

        if withdrawal_amount > 0.009:
            withdrawal_detected = True
            betting_state["session_balance"] -= withdrawal_amount
            betting_state["external_withdrawals_total"] = betting_state.get("external_withdrawals_total", 0.0) + withdrawal_amount
            print(f"[ACCOUNTING] Обнаружен вывод: -{withdrawal_amount:.0f}р, session_balance скорректирован до {betting_state['session_balance']:.0f}р", flush=True)
            _queue_telegram_notification(
                "[BuyBayBye] Обнаружен вывод средств",
                f"Accounting balance уменьшился вне ожидаемого списания ставки.\nСумма вывода: {withdrawal_amount:.0f}р\nНовый real balance: {new_balance:.0f}р\nSession balance: {betting_state['session_balance']:.0f}р",
                dedup_key="withdrawal_detected",
                enabled=TELEGRAM_NOTIFY_WITHDRAWALS,
            )

    betting_state["pending_expected_bet_drop"] = pending_expected_bet_drop
    betting_state["account_balance"] = new_balance
    betting_state["account_balance_type"] = normalized_balance_type
    betting_state["account_balance_updated_at"] = datetime.now(timezone.utc).isoformat()
    betting_state["last_accounting_rejection_reason"] = None
    _update_runtime_snapshot("balance_update", {
        "account_balance": new_balance,
        "withdrawal_detected": withdrawal_detected,
    })

    if BET_DEBUG_ENABLED:
        btype = betting_state.get("account_balance_type")
        print(f"[ACCOUNTING] Баланс обновлен: {new_balance} (balance_type={btype})", flush=True)


# Emoji / symbols used in bet logs that are rendered as 2 terminal columns
# on most modern terminals (Windows Terminal, VS Code, etc.).
# NOTE: ✓ and ✗ are 1-column wide (confirmed by wcwidth); do NOT add them here.
_DOUBLE_WIDTH_EMOJI = {"❌", "✅", "🧰", "🎲", "🔄", "♻", "🔴", "🟡", "💰"}


def _visible_length(s: str) -> int:
    """Получить видимую ширину строки для терминала (без ANSI кодов).

    Важно для выравнивания: эмодзи и wide-символы часто занимают 2 колонки,
    а combining-символы и variation selectors — 0.

    По умолчанию используем wcwidth (если доступен), чтобы совпадать с
    фактическим рендером текущего терминала.

    При FORCE_DOUBLE_WIDTH_EMOJI=true известные эмодзи принудительно считаются
    2-колоночными.
    """
    text = re.sub(r'\033\[[0-9;]*m', '', s)

    width = 0
    for ch in text:
        # Combining marks, variation selectors, ZWJ: zero-width.
        if unicodedata.combining(ch) or ch == "\ufe0f" or ch == "\u200d":
            continue
        if FORCE_DOUBLE_WIDTH_EMOJI and ch in _DOUBLE_WIDTH_EMOJI:
            width += 2
        elif _wcwidth_char is not None:
            cw = _wcwidth_char(ch)
            width += cw if cw >= 0 else 1
        elif ch in _DOUBLE_WIDTH_EMOJI:
            # Fallback when wcwidth is unavailable.
            width += 2
        elif unicodedata.east_asian_width(ch) in {"W", "F"}:
            width += 2
        else:
            width += 1
    return width


def _ansi_emoji_compensation(s: str) -> int:
    """Компенсация бага терминала: ANSI-цвет + несколько emoji в одном span
    рендерятся шире на (N-1) колонок, где N — количество emoji."""
    if '\033[' not in s:
        return 0
    text = re.sub(r'\033\[[0-9;]*m', '', s)
    emoji_count = sum(1 for ch in text if ch in _DOUBLE_WIDTH_EMOJI)
    return max(0, emoji_count - 1)


def _pad_width(s: str, width: int) -> str:
    """Добавить пробелы для выравнивания, учитывая ANSI коды и баг терминала с emoji"""
    visible = _visible_length(s)
    compensation = _ansi_emoji_compensation(s)
    padding = width - visible - compensation
    if padding > 0:
        return s + ' ' * padding
    return s


def _pad_width_center(s: str, width: int) -> str:
    """Добавить пробелы для центрирования, учитывая ANSI коды и баг терминала с emoji."""
    visible = _visible_length(s)
    compensation = _ansi_emoji_compensation(s)
    padding = width - visible - compensation
    if padding > 0:
        left = padding // 2
        right = padding - left
        return (' ' * left) + s + (' ' * right)
    return s


def _print_session_stats(checkpoint: int = 0) -> None:
    """
    Вывести промежуточную или финальную статистику сессии
    
    Args:
        checkpoint: номер контрольной точки (0 для финальной статистики)
    """
    global betting_state
    if not betting_state:
        return
    
    total_bets = betting_state.get("total_bets_placed", 0)
    total_profit = betting_state.get("total_profit", 0)
    roi = _calculate_roi()
    
    header = "📊 СТАТИСТИКА СЕССИИ" + (f" (ставка {checkpoint})" if checkpoint > 0 else " (ИТОГОВАЯ)")
    print("\n" + "="*60, flush=True)
    print(f"{COLOR_CYAN}{header}{COLOR_RESET}", flush=True)
    print("="*60, flush=True)
    print(f"  Ставок совершено: {COLOR_MAGENTA}{total_bets}{COLOR_RESET}", flush=True)
    print(f"  Общая сумма ставок: {COLOR_YELLOW}{betting_state.get('total_bet_amount', 0):.0f}р{COLOR_RESET}", flush=True)
    profit_color = COLOR_GREEN if total_profit >= 0 else COLOR_RED
    print(f"  Общий профит: {profit_color}{total_profit:.0f}р{COLOR_RESET}", flush=True)
    roi_color = COLOR_GREEN if roi >= 0 else COLOR_RED
    print(f"  ROI: {roi_color}{roi:.2f}%{COLOR_RESET}", flush=True)
    print("="*60 + "\n", flush=True)


def _format_outcome(outcome: str, specifier: str = "") -> str:
    """Отформатировать тип ставки для вывода. Заменяет 'double' на 🎲"""
    if outcome == "double":
        return "🎲"
    elif specifier:
        return f"{outcome}({specifier})"
    else:
        return outcome


def _format_combo_pretty(combo: str) -> str:
    """Отформатировать комбинацию для красивого вывода (только иконка + число)
    
    Примеры:
    - "red_3" → "🔴 3"
    - "yellow_5" → "🟡 5"
    - "double" → "🎲"
    """
    if combo == "double":
        return "🎲"
    elif combo.startswith("red_"):
        value = combo.split("_")[1]
        return f"🔴 {value}"
    elif combo.startswith("yellow_"):
        value = combo.split("_")[1]
        return f"🟡 {value}"
    else:
        return combo


def _format_outcome_pretty(outcome: str, specifier: str = "") -> str:
    """Отформатировать ставку для красивого вывода (outcome + specifier вместе)
    
    Примеры:
    - ("red", "3") → "🔴 3"
    - ("yellow", "5") → "🟡 5"
    - ("double", "") → "🎲"
    """
    if outcome == "double":
        return "🎲"
    elif outcome == "red":
        return f"🔴 {specifier}"
    elif outcome == "yellow":
        return f"🟡 {specifier}"
    else:
        return _format_outcome(outcome, specifier)


def _format_result_pretty(result: str) -> str:
    """Отформатировать результат (что выпало) в эмодзи
    
    Примеры:
    - "no_double" → "❌"
    - "no_red" → "❌"
    - "no_yellow" → "❌"
    - "double" → "🎲"
    - "red_3" → "🔴 3"
    """
    if result.startswith("no_"):
        return "❌"  # Не выпало ставленное
    elif result == "double":
        return "🎲"
    elif "_" in result:
        # Это комбинация вида "red_3" или "yellow_5"
        return _format_combo_pretty(result)
    else:
        return result


def _format_rolled_dice_pretty(dice_results: list) -> str:
    """Отформатировать оба выпавших кубика для вывода в RESULT.

    Пример:
    - [{"color": "red", "value": 3}, {"color": "yellow", "value": 5}] -> "🔴 3 🟡 5"
    """
    if not isinstance(dice_results, list) or len(dice_results) == 0:
        return "-"

    parts = []
    for dice in dice_results[:2]:
        color = dice.get("color") if isinstance(dice, dict) else None
        value = dice.get("value") if isinstance(dice, dict) else None

        if color in {"red", "yellow"} and value is not None:
            parts.append(_format_combo_pretty(f"{color}_{value}"))
        else:
            parts.append("❔")

    return " ".join(parts)


def _format_round_result_pretty(dice_results: list) -> str:
    """Отформатировать результат раунда для колонки RESULT.

    Если выпал дубль, показываем компактно: "🎲 N".
    Иначе показываем оба кубика: "🔴 N 🟡 M".
    """
    if not isinstance(dice_results, list) or len(dice_results) < 2:
        return _format_rolled_dice_pretty(dice_results)

    v1 = dice_results[0].get("value") if isinstance(dice_results[0], dict) else None
    v2 = dice_results[1].get("value") if isinstance(dice_results[1], dict) else None

    if isinstance(v1, int) and isinstance(v2, int) and v1 == v2:
        return f"🎲 {v1}"

    return _format_rolled_dice_pretty(dice_results)


def _print_dice_stats_20() -> None:
    """
    Вывести статистику комбинаций цвет+значение каждые 20 ходов
    Показывает НАРАСТАЮЩИЙ итог за всю сессию
    """
    global betting_state
    if not betting_state:
        return
    
    total_bets = betting_state.get("total_bets_placed", 0)
    if total_bets % 20 != 0 or total_bets == 0:
        return
    
    # Проверить, уже ли был отчет для этого количества ставок
    reported = betting_state.get("reported_20_rounds", [])
    if total_bets in reported:
        return
    
    combo_stats = betting_state.get("combo_stats", {})
    double_stats = betting_state.get("double_stats", {})
    
    # Найти наиболее часто выпавшую комбинацию
    max_count = max(combo_stats.values()) if combo_stats else 0
    most_common_combos = [k for k, v in combo_stats.items() if v == max_count] if max_count > 0 else []
    
    print("\n" + "="*80, flush=True)
    print(f"{COLOR_CYAN}🎲 СТАТИСТИКА КОМБИНАЦИЙ ЦВЕТ+ЗНАЧЕНИЕ (всего ходов: {total_bets}) — НАРАСТАЮЩИЙ ИТОГ{COLOR_RESET}", flush=True)
    print("="*80, flush=True)
    
    # Таблица комбинаций
    print(f"\n{COLOR_MAGENTA}📊 КОМБИНАЦИИ (цвет_значение):{COLOR_RESET}", flush=True)
    print("-" * 80, flush=True)
    
    # RED комбинации
    print(f"{COLOR_RED}🔴 RED:{COLOR_RESET}", flush=True)
    for value in range(1, 7):
        combo_key = f"red_{value}"
        count = combo_stats.get(combo_key, 0)
        percentage = (count / total_bets) * 100 if total_bets > 0 else 0
        
        if combo_key in most_common_combos:
            marker = " ← НАИБОЛЕЕ ЧАСТОЕ"
            color = COLOR_GREEN
        else:
            marker = ""
            color = COLOR_RESET
        
        pretty_combo = _format_combo_pretty(combo_key)
        print(f"  {color}{pretty_combo:8} {count:3d} ({percentage:5.1f}%){COLOR_RESET}{marker}", flush=True)
    
    # YELLOW комбинации
    print(f"\n{COLOR_YELLOW}🟡 YELLOW:{COLOR_RESET}", flush=True)
    for value in range(1, 7):
        combo_key = f"yellow_{value}"
        count = combo_stats.get(combo_key, 0)
        percentage = (count / total_bets) * 100 if total_bets > 0 else 0
        
        if combo_key in most_common_combos:
            marker = " ← НАИБОЛЕЕ ЧАСТОЕ"
            color = COLOR_GREEN
        else:
            marker = ""
            color = COLOR_RESET
        
        pretty_combo = _format_combo_pretty(combo_key)
        print(f"  {color}{pretty_combo:8} {count:3d} ({percentage:5.1f}%){COLOR_RESET}{marker}", flush=True)
    
    # Итоговая статистика
    print("\n" + "-" * 80, flush=True)
    
    print(f"{COLOR_CYAN}📈 ИТОГО ЗА СЕССИЮ:{COLOR_RESET}", flush=True)
    
    # Статистика по дублям
    total_doubles = double_stats.get("doubles", 0)
    total_no_doubles = double_stats.get("no_doubles", 0)
    total_rounds = total_doubles + total_no_doubles
    
    if total_rounds > 0:
        doubles_pct = (total_doubles / total_rounds) * 100
        no_doubles_pct = (total_no_doubles / total_rounds) * 100
        print(f"\n{COLOR_YELLOW}🔱 ДУБЛИ:{COLOR_RESET}", flush=True)
        print(f"  ✓ Дубли:      {total_doubles:3d} раз ({doubles_pct:5.1f}%)", flush=True)
        print(f"  ✗ Не дубли:    {total_no_doubles:3d} раз ({no_doubles_pct:5.1f}%)", flush=True)
    
    print("="*80 + "\n", flush=True)
    
    # Добавить в список отчетов
    reported.append(total_bets)
    betting_state["reported_20_rounds"] = reported


def _format_bet_log(action: str, status_icon: str, outcome: str = "-", amount: str = "-", step: str = "-", 
                   result: str = "-", profit: str = "-", roi: str = "-", balance: str = "-",
                   real_balance: str = "-",
                   error_msg: str = "", bets_count: str = "") -> str:
    """
    Унифицированное форматирование логов ставок с цветовым кодированием:
    [TIME] | [BET] | [#N] | [STEP] | [ACTION] | [STATUS_ICON] | outcome | amount | result | profit | roi | 🧰 balance
    
    Правила окраски:
    - SET ✓: вся строка ЖЕЛТАЯ, результат как "------", шаг БЕЗ ЦВЕТА
    - RES ✓: вся строка ЗЕЛЕНАЯ, шаг БЕЗ ЦВЕТА
    - RES ✗: вся строка КРАСНАЯ, шаг БЕЗ ЦВЕТА
    - SET ✗: вся строка ФИОЛЕТОВАЯ, шаг БЕЗ ЦВЕТА
    - amount: ВСЕГДА ФИОЛЕТОВАЯ (во всех случаях)
    - 🧰: зеленый если положительный, красный если отрицательный
    
    Args:
        action: "SET", "RES"
        status_icon: "✅", "❌"
        outcome: целевой/полученный результат (напр. red(5), double)
        amount: размер ставки (напр. 100р)
        step: текущий шаг (напр. 1/15)
        result: полученный результат (напр. red(5), no_double) или "------" для SET
        profit: прибыль/убыток (напр. +470р, -100р)
        roi: ROI в процентах (напр. 12.5%)
        balance: баланс сессии (напр. 1350р)
        real_balance: реальный баланс аккаунта из accounting_ws (напр. 5000р)
        error_msg: полный текст ошибки при необходимости
    
    Returns:
        Форматированная строка лога
    """
    time_str = datetime.now().strftime("%H:%M:%S")
    reset_full = COLOR_RESET

    # Фиксированная ширина колонки result — объявляем здесь,
    # чтобы использовать при формировании плейсхолдера "---…---".
    # Делаем колонку result на 2 символа шире: плейсхолдер для SET
    # будет длиннее (например, "-------------" вместо "-----------").
    _result_col_width = 13

    # Определить цвет для всей строки по action и status_icon
    if action == "SET" and status_icon == "✅":
        line_color = COLOR_YELLOW  # SET ✓ - вся желтая
        result_display = "-" * _result_col_width  # дефисы заполняют всю ширину колонки
    elif action == "RES" and status_icon == "✅":
        line_color = COLOR_GREEN  # Выигрыш - вся зеленая
        result_display = result
    elif action == "RES" and status_icon == "❌":
        line_color = COLOR_RED  # Проигрыш - вся красная
        result_display = result
    else:
        # Ошибка (SET ✗)
        line_color = COLOR_MAGENTA  # Ошибка - вся фиолетовая
        result_display = result
    
    # Применить цвет к time и bet
    time_part = f"{line_color}[{time_str}]{reset_full}"
    bet_part = f"{line_color}[BET]{reset_full}"

    # Номер ставки отдельной колонкой
    if bets_count and bets_count.strip():
        bet_number_part = f"{COLOR_CYAN}[#{bets_count}]{reset_full}"
    else:
        bet_number_part = "[#---]"
    step_part = step  # БЕЗ ЦВЕТА
    
    # Форматировать результат красиво (преобразовать "no_double" в "❌")
    result_display_fmt = _format_result_pretty(result_display)
    
    # Форматировать баланс с префиксом эмодзи сундука и цветной индикацией
    try:
        balance_value = float(balance.replace('р', '').strip())
        if balance_value > 0:
            balance_colored = f"{COLOR_GREEN}🧰 {balance}{reset_full}"
        elif balance_value < 0:
            balance_colored = f"{COLOR_RED}🧰 {balance}{reset_full}"
        else:
            balance_colored = f"🧰 {balance}"
    except (ValueError, AttributeError):
        balance_colored = f"🧰 {balance}"

    # Форматировать реальный баланс из accounting_ws
    try:
        float(real_balance.replace('р', '').strip())
        real_balance_colored = f"{COLOR_CYAN}💰 {real_balance}{reset_full}"
    except (ValueError, AttributeError):
        real_balance_colored = f"💰 {real_balance}"
    
    # Построить части строки с применением цвета к нужным элементам
    # Шаг - БЕЗ ЦВЕТА
    # Остальное - с цветом линии
    status_icon_colored = f"{line_color}{status_icon}{reset_full}"
    action_colored = f"{line_color}{action}{reset_full}"
    outcome_colored = f"{line_color}{outcome}{reset_full}"
    amount_colored = f"{COLOR_MAGENTA}{amount}{reset_full}"  # ВСЕГДА ФИОЛЕТОВАЯ
    result_colored = f"{line_color}{result_display_fmt}{reset_full}"
    profit_colored = f"{line_color}{profit}{reset_full}"
    roi_colored = f"{line_color}{roi}{reset_full}"
    
    # Фиксированные ширины колонок, чтобы SET/RES строки оставались одной сеткой.
    time_width = 10
    bet_width = 5
    bet_number_width = 6
    step_width = 6
    action_width = 4
    status_width = 2
    outcome_width = 6
    amount_width = 7
    result_width = _result_col_width
    profit_width = 7
    roi_width = 9
    balance_width = 10
    real_balance_width = 12

    # Формировать основную строку лога с выравниванием столбцов
    log_parts = [
        _pad_width_center(time_part, time_width),             # [HH:MM:SS]
        _pad_width_center(status_icon_colored, status_width), # ✅/❌
        _pad_width_center(bet_part, bet_width),               # [BET]
        _pad_width_center(bet_number_part, bet_number_width), # [#001]
        _pad_width_center(step_part, step_width),             # 1/15
        _pad_width_center(action_colored, action_width),      # SET/RES
        _pad_width_center(outcome_colored, outcome_width),    # 🎲, 🔴 5
        _pad_width_center(amount_colored, amount_width),      # 10.0р, 100.0р (ФИОЛЕТОВАЯ)
        _pad_width_center(result_colored, result_width),      # RESULT
        _pad_width_center(profit_colored, profit_width),      # +57р, -100р
        _pad_width_center(roi_colored, roi_width),            # 5.70%
        _pad_width_center(balance_colored, balance_width),    # 🧰 ...р
        _pad_width_center(real_balance_colored, real_balance_width), # 💰 ...р
    ]
    
    log_line = " | ".join(log_parts)
    
    # Если есть текст ошибки, добавить его на новой строке
    if error_msg:
        log_line += f"\n{COLOR_MAGENTA}↳ ERROR: {error_msg}{reset_full}"
    
    return log_line


async def _process_betting_round(page, payload: object) -> None:
    """
    Обработать раунд: обновить результат предыдущей ставки и разместить новую
    """
    global BET_MODE_OUTCOME, BET_MODE_SPECIFIER, betting_state
    
    try:
        payload_text = _format_ws_payload(payload)
        parsed_payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return
    
    if not isinstance(parsed_payload, dict) or parsed_payload.get("status") != "rng_values":
        return
    
    results = parsed_payload.get("results")
    if not isinstance(results, dict):
        return
    
    # Извлечь результат кубика из раунда
    dice_results = results.get("dice", [])
    
    # Собрать статистику комбинаций цвет+значение для каждого кубика
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
        if values[0] == values[1] and values[0] is not None:
            double_stats = betting_state.get("double_stats", {})
            double_stats["doubles"] = double_stats.get("doubles", 0) + 1
        else:
            double_stats = betting_state.get("double_stats", {})
            double_stats["no_doubles"] = double_stats.get("no_doubles", 0) + 1
    
    # Подготовить отображение результата для колонки RESULT.
    # Для дубля будет формат "🎲 N".
    rolled_dice_representation = _format_round_result_pretty(dice_results)
    betting_state["last_round_result"] = rolled_dice_representation
    betting_state["last_round_game_id"] = parsed_payload.get("game_id")
    betting_state["last_round_status"] = parsed_payload.get("status")
    betting_state["last_round_timestamp"] = datetime.now(timezone.utc).isoformat()
    player_info = results.get("player", {}) if isinstance(results.get("player"), dict) else {}
    betting_state["last_round_player_name"] = player_info.get("name")
    betting_state["last_round_position"] = player_info.get("position")

    # Проверить тип ставки (цвет или дубль)
    matching_dice = None
    is_win = False
    actual_dice_representation = None
    dice_colors_appeared = []  # Цвета, которые выпали в раунде
    
    if BET_MODE_OUTCOME == "double":
        # Ставка на любой дубль (когда оба кубика равны друг другу)
        dice_values = [d.get("value") for d in dice_results]
        dice_colors_appeared = [d.get("color") for d in dice_results]
        # Дубль: оба кубика одного значения
        is_double = len(dice_values) == 2 and dice_values[0] == dice_values[1]
        actual_dice_value = dice_values[0] if is_double else None
        # В логах показываем оба выпавших кубика, а не только double/no_double.
        actual_dice_representation = rolled_dice_representation
        is_win = is_double
    else:
        # Ставка на цвет
        for dice in dice_results:
            if dice.get("color") == BET_MODE_OUTCOME:
                matching_dice = dice
                break
        
        # Собрать все цвета которые выпали
        dice_colors_appeared = [d.get("color") for d in dice_results]
        
        target_dice_value = int(BET_MODE_SPECIFIER)
        actual_dice_value = matching_dice.get("value") if matching_dice else None
        
        # В логах всегда показываем оба выпавших кубика.
        actual_dice_representation = rolled_dice_representation
        
        is_win = (actual_dice_value == target_dice_value)
    
    # Обновить результат предыдущей ставки (если была)
    if betting_state["last_bet_amount"] > 0:
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()
            
            # Проверить, выиграла ли предыдущая ставка
            
            
            # Сохранить текущий шаг ДО обновления для логирования (для обоих случаев выигрыша и проигрыша)
            current_step_for_log = betting_state["current_step"]
            
            if is_win:
                # Выигрыш
                status = "win"
                betting_state["consecutive_losses"] = 0
                betting_state["current_step"] = 0
                payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
                bet_amount = betting_state['last_bet_amount']
                winnings = bet_amount * payout_coeff
                margin = winnings - bet_amount
                betting_state["total_profit"] += margin
                betting_state["session_balance"] += margin
                roi = _calculate_roi()
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                
                total_bets = betting_state.get("total_bets_placed", 0)
                log_line = _format_bet_log(
                    action="RES",
                    status_icon="✅",
                    outcome=_format_outcome_pretty(BET_MODE_OUTCOME, BET_MODE_SPECIFIER),
                    amount=f"{bet_amount}р",
                    step=f"{current_step_for_log+1}/{max_steps}",
                    result=actual_dice_representation,
                    profit=f"+{margin:.0f}р",
                    roi=f"{roi:.2f}%",
                    balance=f"{betting_state['session_balance']:.0f}р",
                    real_balance=_get_balance_for_log(),
                    bets_count=str(total_bets).zfill(3)
                )
                print(log_line, flush=True)
                
                # Проверить, нужно ли вывести промежуточную статистику (каждые 50 ставок)
                if total_bets % 50 == 0:
                    _print_session_stats(total_bets)
            else:
                # Проигрыш
                status = "loss"
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                bet_amount = betting_state['last_bet_amount']
                margin = -bet_amount
                betting_state["total_profit"] += margin
                betting_state["session_balance"] += margin
                
                roi = _calculate_roi()
                
                if betting_state["current_step"] + 1 == max_steps:
                    betting_state["consecutive_losses"] = 0
                    betting_state["current_step"] = 0
                    total_bets = betting_state.get("total_bets_placed", 0)
                    log_line = _format_bet_log(
                        action="RES",
                        status_icon="❌",
                        outcome=_format_outcome_pretty(BET_MODE_OUTCOME, BET_MODE_SPECIFIER),
                        amount=f"{bet_amount}р",
                        step=f"{max_steps}/{max_steps}",
                        result=actual_dice_representation,
                        profit=f"{margin:.0f}р",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state['session_balance']:.0f}р",
                        real_balance=_get_balance_for_log(),
                        bets_count=str(total_bets).zfill(3)
                    )
                    print(log_line + f" {COLOR_RESET}[♻️ RESTART]", flush=True)
                    
                    # Проверить, нужно ли вывести промежуточную статистику (каждые 50 ставок)
                    if total_bets % 50 == 0:
                        _print_session_stats(total_bets)
                else:
                    betting_state["consecutive_losses"] += 1
                    betting_state["current_step"] = min(betting_state["current_step"] + 1, max_steps - 1)
                    total_bets = betting_state.get("total_bets_placed", 0)
                    log_line = _format_bet_log(
                        action="RES",
                        status_icon="❌",
                        outcome=_format_outcome_pretty(BET_MODE_OUTCOME, BET_MODE_SPECIFIER),
                        amount=f"{bet_amount}р",
                        step=f"{current_step_for_log+1}/{max_steps}",
                        result=actual_dice_representation,
                        profit=f"{margin:.0f}р",
                        roi=f"{roi:.2f}%",
                        balance=f"{betting_state['session_balance']:.0f}р",
                        real_balance=_get_balance_for_log(),
                        bets_count=str(total_bets).zfill(3)
                    )
                    print(log_line, flush=True)
                    
                    # Проверить, нужно ли вывести промежуточную статистику (каждые 50 ставок)
                    if total_bets % 50 == 0:
                        _print_session_stats(total_bets)
            
            # Проверить, нужно ли вывести статистику каждые 20 ходов
            total_bets_now = betting_state.get("total_bets_placed", 0)
            if total_bets_now > 0 and total_bets_now % 20 == 0:
                _print_dice_stats_20()
            
            # Обновить последнюю ставку в БД
            # Сохранить цвет первого кубика (или "double" если дубль)
            stored_dice_color = dice_colors_appeared[0] if dice_colors_appeared else "unknown"
            if BET_MODE_OUTCOME == "double":
                stored_dice_color = "double"
            
            cursor.execute("""
                UPDATE bet_history 
                SET status = %s, result_dice_color = %s, result_dice_value = %s
                WHERE id = (SELECT MAX(id) FROM bet_history)
            """, (status, stored_dice_color, actual_dice_value))
            
            conn.commit()
            cursor.close()
            conn.close()
            _update_runtime_snapshot("bet_result", {
                "bet_result_status": status,
                "bet_result_value": actual_dice_value,
                "bet_result_display": actual_dice_representation,
            })
        except Exception as e:
            print(f"[DB ERROR] Ошибка обновления результата ставки: {e}", flush=True)
    
    # Обновить динамическую ставку если режим включен
    if BET_DEBUG_ENABLED:
        print(f"[DEBUG PROCESS] DYNAMIC_BET_MODE={DYNAMIC_BET_MODE}, calling _update_dynamic_bet", flush=True)
    if DYNAMIC_BET_MODE:
        if BET_DEBUG_ENABLED:
            print("[DEBUG PROCESS] Entering if DYNAMIC_BET_MODE, calling function", flush=True)
        _update_dynamic_bet()
    
    # Проверить полосу проигрышей: если 15+ проигрышей подряд, генерировать СЛУЧАЙНУЮ ставку
    consecutive_losses = betting_state.get("consecutive_losses", 0)
    if consecutive_losses >= 15:
        print("", flush=True)  # Пустая строка для разделения
        BET_MODE_OUTCOME, BET_MODE_SPECIFIER = _generate_random_bet()
        betting_state["consecutive_losses"] = 0  # Сбросить счётчик после генерации
        print("", flush=True)  # Пустая строка для разделения
    
    # Разместить новую ставку
    bet_amount = _calculate_bet_amount()
    if BET_DEBUG_ENABLED:
        print(f"[DEBUG PROCESS_BET] Вызов _place_bet с outcome={BET_MODE_OUTCOME}, specifier={BET_MODE_SPECIFIER}", flush=True)
    await _place_bet(page, BET_MODE_OUTCOME, BET_MODE_SPECIFIER, bet_amount)


def _analyze_recent_bets_stats() -> dict:
    """
    Анализировать последние N ставок и вернуть статистику по комбинациям
    Возвращает словарь: {комбинация: {'wins': кол-во побед, 'total': кол-во попыток, 'win_rate': процент}}
    """
    global betting_state
    
    recent_bets = betting_state.get("recent_bets", [])
    if not recent_bets:
        return {}
    
    stats = {}
    
    for bet in recent_bets:
        combo = bet.get("combo")  # "red_3", "yellow_5", "double"
        result = bet.get("result")  # True/False
        
        if combo not in stats:
            stats[combo] = {"wins": 0, "total": 0, "win_rate": 0}
        
        stats[combo]["total"] += 1
        if result:
            stats[combo]["wins"] += 1
        
        stats[combo]["win_rate"] = (stats[combo]["wins"] / stats[combo]["total"]) * 100 if stats[combo]["total"] > 0 else 0
    
    return stats


def _analyze_all_results_frequency() -> dict:
    """
    Анализировать ЧАСТОТУ ВЫПАДЕНИЙ всех комбинаций из последних N результатов БД
    (не выигрыши размещённых ставок, а просто выпадения кубиков)
    Возвращает словарь: {комбинация: {'freq': кол-во выпадений, 'total': всего результатов, 'frequency': процент}}
    """
    global betting_state
    
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor()
        
        # Получить последние DYNAMIC_WINDOW_SIZE результатов из БД
        # dice_results содержит JSON с массивом кубиков
        current_player_name = betting_state.get("last_round_player_name")
        current_position = betting_state.get("last_round_position")

        where_clauses = []
        query_params = []

        if DYNAMIC_FILTER_BY_PLAYER and current_player_name:
            where_clauses.append("player_name = %s")
            query_params.append(current_player_name)

        if DYNAMIC_FILTER_BY_SIDE and current_position:
            where_clauses.append("dice_results->'player'->>'position' = %s")
            query_params.append(current_position)

        query = "SELECT player_name, dice_results FROM game_results"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY timestamp DESC LIMIT %s"
        query_params.append(DYNAMIC_WINDOW_SIZE)

        cursor.execute(query, tuple(query_params))
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not results:
            return {}
        
        # Рассчитать частоту выпадений
        stats = {}
        total_results = len(results)
        
        for (_, dice_results_json) in results:
            if not dice_results_json:
                continue
            
            # dice_results это JSON с массивом кубиков
            dice_data = dice_results_json.get("dice", []) if isinstance(dice_results_json, dict) else []
            
            if len(dice_data) >= 2:
                dice_1 = dice_data[0]
                dice_2 = dice_data[1]
                
                dice_1_color = dice_1.get("color") if isinstance(dice_1, dict) else None
                dice_1_value = dice_1.get("value") if isinstance(dice_1, dict) else None
                dice_2_color = dice_2.get("color") if isinstance(dice_2, dict) else None
                dice_2_value = dice_2.get("value") if isinstance(dice_2, dict) else None
                
                # Проверить красный кубик
                if dice_1_color == "red" and isinstance(dice_1_value, int) and 1 <= dice_1_value <= 6:
                    combo = f"red_{dice_1_value}"
                    if combo not in stats:
                        stats[combo] = {"freq": 0}
                    stats[combo]["freq"] += 1
                
                # Проверить жёлтый кубик
                if dice_2_color == "yellow" and isinstance(dice_2_value, int) and 1 <= dice_2_value <= 6:
                    combo = f"yellow_{dice_2_value}"
                    if combo not in stats:
                        stats[combo] = {"freq": 0}
                    stats[combo]["freq"] += 1
                
                # Проверить дубль
                if isinstance(dice_1_value, int) and isinstance(dice_2_value, int) and dice_1_value == dice_2_value:
                    combo = "double"
                    if combo not in stats:
                        stats[combo] = {"freq": 0}
                    stats[combo]["freq"] += 1
        
        # Добавить процентные значения
        for combo in stats:
            stats[combo]["frequency"] = (stats[combo]["freq"] / total_results) * 100

        if BET_DEBUG_ENABLED and (DYNAMIC_FILTER_BY_PLAYER or DYNAMIC_FILTER_BY_SIDE):
            applied_filters = []
            if DYNAMIC_FILTER_BY_PLAYER and current_player_name:
                applied_filters.append(f"player={current_player_name}")
            if DYNAMIC_FILTER_BY_SIDE and current_position:
                applied_filters.append(f"side={current_position}")
            if applied_filters:
                print(f"[DEBUG DYNAMIC] Применены фильтры анализа: {', '.join(applied_filters)}", flush=True)
        
        return stats
        
    except Exception as e:
        if BET_DEBUG_ENABLED:
            print(f"[DEBUG] Error analyzing all results: {e}", flush=True)
        return {}


def _get_best_combination(stats: dict | None = None) -> tuple[str, str]:
    """
    Найти лучшую комбинацию для динамической ставки.

    Для red/yellow выбираем значение, ближайшее к среднему значению кубика
    этого цвета за окно анализа. Для double оставляем отдельного кандидата,
    потому что у дубля нет собственного "среднего значения".

    Итоговый выбор делается между тремя кандидатами:
    - red_<rounded mean>
    - yellow_<rounded mean>
    - double

    Побеждает кандидат с наибольшей частотой выпадения в окне.
    Возвращает кортеж (outcome, specifier): ("red", "3"), ("yellow", "5"), ("double", "")
    """
    if stats is None:
        # Анализировать только фактические выпадения из БД, а не размещённые ставки.
        stats = _analyze_all_results_frequency()

    if not stats:
        return (BET_MODE_OUTCOME, BET_MODE_SPECIFIER)

    selectable_stats = dict(stats)
    if not DYNAMIC_INCLUDE_DOUBLE_SELECTION:
        selectable_stats.pop("double", None)

    if not selectable_stats:
        return (BET_MODE_OUTCOME, BET_MODE_SPECIFIER)

    if not DYNAMIC_USE_AVERAGE_VALUE_SELECTION:
        best_combo = max(selectable_stats.items(), key=lambda x: (
            x[1]["frequency"],
            x[1]["freq"],
        ))

        combo_key = best_combo[0]

        if BET_DEBUG_ENABLED:
            freq = best_combo[1]["frequency"]
            freq_count = best_combo[1]["freq"]
            print(f"[DEBUG DYNAMIC] Average selection disabled; best combo by frequency: {combo_key} (freq={freq:.1f}%, count={freq_count})", flush=True)

        if combo_key == "double":
            return ("double", "")

        parts = combo_key.split("_")
        return (parts[0], parts[1])

    candidates: list[tuple[str, dict]] = []

    for color in ("red", "yellow"):
        weighted_sum = 0
        total_hits = 0

        for value in range(1, 7):
            combo_key = f"{color}_{value}"
            combo_stats = stats.get(combo_key)
            if not combo_stats:
                continue
            freq_count = int(combo_stats.get("freq", 0) or 0)
            weighted_sum += value * freq_count
            total_hits += freq_count

        if total_hits <= 0:
            continue

        avg_value = weighted_sum / total_hits
        rounded_value = max(1, min(6, int(avg_value + 0.5)))
        candidate_key = f"{color}_{rounded_value}"
        candidate_stats = stats.get(candidate_key, {"freq": 0, "frequency": 0.0})
        candidates.append((candidate_key, {
            "freq": int(candidate_stats.get("freq", 0) or 0),
            "frequency": float(candidate_stats.get("frequency", 0.0) or 0.0),
            "avg_value": avg_value,
            "rounded_value": rounded_value,
        }))

    if DYNAMIC_INCLUDE_DOUBLE_SELECTION and "double" in selectable_stats:
        double_stats = selectable_stats["double"]
        candidates.append(("double", {
            "freq": int(double_stats.get("freq", 0) or 0),
            "frequency": float(double_stats.get("frequency", 0.0) or 0.0),
            "avg_value": None,
            "rounded_value": None,
        }))

    if not candidates:
        return (BET_MODE_OUTCOME, BET_MODE_SPECIFIER)

    best_combo = max(candidates, key=lambda x: (
        x[1]["frequency"],
        x[1]["freq"],
    ))

    combo_key = best_combo[0]

    if BET_DEBUG_ENABLED:
        for candidate_key, candidate_data in candidates:
            if candidate_key == "double":
                print(
                    f"[DEBUG DYNAMIC] candidate={candidate_key} freq={candidate_data['frequency']:.1f}% count={candidate_data['freq']}",
                    flush=True,
                )
            else:
                print(
                    f"[DEBUG DYNAMIC] candidate={candidate_key} avg={candidate_data['avg_value']:.2f} rounded={candidate_data['rounded_value']} freq={candidate_data['frequency']:.1f}% count={candidate_data['freq']}",
                    flush=True,
                )

    if combo_key == "double":
        return ("double", "")

    parts = combo_key.split("_")
    return (parts[0], parts[1])


def _update_dynamic_bet() -> None:
    """
    Обновить BET_MODE_OUTCOME и BET_MODE_SPECIFIER на основе анализа последних ставок
    """
    global BET_MODE_OUTCOME, BET_MODE_SPECIFIER, betting_state
    
    if BET_DEBUG_ENABLED:
        print(f"[DEBUG UPDATE_DYN] Function entered. DYNAMIC_BET_MODE={DYNAMIC_BET_MODE}", flush=True)
    
    if not DYNAMIC_BET_MODE:
        if BET_DEBUG_ENABLED:
            print("[DEBUG UPDATE_DYN] Early return: DYNAMIC_BET_MODE is False", flush=True)
        return
    
    total_bets = betting_state.get("total_bets_placed", 0)
    next_trigger = ((total_bets // DYNAMIC_RECALC_INTERVAL) + 1) * DYNAMIC_RECALC_INTERVAL
    if BET_DEBUG_ENABLED:
        print(f"[DEBUG UPDATE_DYN] total_bets={total_bets}, DYNAMIC_RECALC_INTERVAL={DYNAMIC_RECALC_INTERVAL}, modulo result={total_bets % DYNAMIC_RECALC_INTERVAL if DYNAMIC_RECALC_INTERVAL > 0 else 'ERROR'}, next trigger at {next_trigger}", flush=True)
    
    # Пересчитывать только если количество ставок делится на DYNAMIC_RECALC_INTERVAL
    if total_bets > 0 and total_bets % DYNAMIC_RECALC_INTERVAL == 0:
        stats = _analyze_all_results_frequency()
        if BET_DEBUG_ENABLED:
            print(f"[DEBUG DYNAMIC] Проверка на ходу {total_bets}: results_window={DYNAMIC_WINDOW_SIZE}, interval={DYNAMIC_RECALC_INTERVAL}, analyzed_combos={len(stats)}", flush=True)

        if not stats:
            if BET_DEBUG_ENABLED:
                print("[DEBUG DYNAMIC] Нет данных game_results для анализа, пропускаем обновление", flush=True)
            return

        best_outcome, best_specifier = _get_best_combination(stats)
        old_outcome = BET_MODE_OUTCOME
        old_specifier = BET_MODE_SPECIFIER
        
        # Если выбранная ставка отличается от текущей, обновить
        if best_outcome != BET_MODE_OUTCOME or best_specifier != BET_MODE_SPECIFIER:
            # Обновить глобальные переменные
            BET_MODE_OUTCOME = best_outcome
            BET_MODE_SPECIFIER = best_specifier if best_specifier else "5"
            
            # Обновить также в betting_state
            betting_state["dynamic_outcome"] = BET_MODE_OUTCOME
            betting_state["dynamic_specifier"] = BET_MODE_SPECIFIER
            
            if BET_DEBUG_ENABLED:
                print(f"[DEBUG DYNAMIC] ✅ СМЕНА: {_format_outcome_pretty(old_outcome, old_specifier)} → {_format_outcome_pretty(BET_MODE_OUTCOME, BET_MODE_SPECIFIER)}", flush=True)
            
            # Вывести информацию об обновлении
            if stats:
                print(f"\n{COLOR_CYAN}📊 ДИНАМИЧЕСКОЕ ОБНОВЛЕНИЕ СТАВКИ (ход {total_bets}):{COLOR_RESET}", flush=True)
                # Показать топ-3 комбинации
                sorted_stats = sorted(stats.items(), key=lambda x: x[1]["frequency"], reverse=True)
                for i, (combo, data) in enumerate(sorted_stats[:3], 1):
                    display_combo = _format_combo_pretty(combo)
                    print(f"  {i}. {display_combo:20} выпал {data['freq']:2d} раз ({data['frequency']:5.1f}%)", flush=True)
                # Форматировать выбранную ставку
                selected_combo = f"{BET_MODE_OUTCOME}_{BET_MODE_SPECIFIER}" if BET_MODE_OUTCOME != "double" else "double"
                display_outcome = _format_combo_pretty(selected_combo)
                print(f"  ➜ Выбрана: {display_outcome}", flush=True)
                print("", flush=True)
        else:
            if BET_DEBUG_ENABLED:
                print(f"[DEBUG DYNAMIC] Ставка не изменилась: {_format_outcome(BET_MODE_OUTCOME, BET_MODE_SPECIFIER)} оптимальна", flush=True)
            
            # Вывести полную статистику даже если ставка не изменилась
            if stats:
                print(f"\n{COLOR_CYAN}📊 АНАЛИЗ ДИНАМИЧЕСКОЙ СТАВКИ (ход {total_bets}):{COLOR_RESET}", flush=True)
                sorted_stats = sorted(stats.items(), key=lambda x: x[1]["frequency"], reverse=True)
                for i, (combo, data) in enumerate(sorted_stats[:5], 1):
                    display_combo = _format_combo_pretty(combo)
                    is_current = "⭐" if combo == f"{BET_MODE_OUTCOME}_{BET_MODE_SPECIFIER}" or (combo == "double" and BET_MODE_OUTCOME == "double") else "  "
                    print(f"  {is_current} {i}. {display_combo:18} выпал {data['freq']:2d} раз ({data['frequency']:5.1f}%)", flush=True)
                print("", flush=True)


def _generate_random_bet() -> tuple[str, str]:
    """
    Сгенерировать случайную ставку из всех доступных комбинаций
    Используется при полосе в 15+ проигрышей подряд
    Возвращает кортеж (outcome, specifier): ("red", "3"), ("yellow", "5"), ("double", "")
    """
    combos = [
        # Красные комбинации
        ("red", "1"), ("red", "2"), ("red", "3"), ("red", "4"), ("red", "5"), ("red", "6"),
        # Жёлтые комбинации
        ("yellow", "1"), ("yellow", "2"), ("yellow", "3"), ("yellow", "4"), ("yellow", "5"), ("yellow", "6"),
        # Дубль
        ("double", "")
    ]
    
    selected = random.choice(combos)
    outcome, specifier = selected
    
    print(f"{COLOR_MAGENTA}⚠️  ПОЛОСА ИЗ 15 ПРОИГРЫШЕЙ! Генерируем СЛУЧАЙНУЮ ставку: {_format_outcome_pretty(outcome, specifier)}{COLOR_RESET}", flush=True)
    
    return outcome, specifier


def _calculate_bet_amount() -> float:
    """
    Вычислить размер ставки на основе текущей стратегии и шага прогрессии
    """
    global betting_state, current_strategy
    
    if not current_strategy or not betting_state:
        return BASE_BET
    
    # Получить коэффициент для текущего шага
    current_step = betting_state.get("current_step", 0)
    coefficients = current_strategy.get("coefficients", [1])
    
    # Убедиться, что шаг не превышает длину последовательности
    step_index = min(current_step, len(coefficients) - 1)
    coefficient = coefficients[step_index]
    
    # Вычислить ставку: базовая ставка * коэффициент
    amount = BASE_BET * coefficient
    
    betting_state["last_bet_amount"] = amount
    return amount


async def _wait_for_exit_signal() -> None:
    if sys.stdin.isatty():
        try:
            await asyncio.to_thread(input)
        except EOFError:
            pass
        return

    # In non-interactive environments like docker compose up, keep the process
    # alive until it is stopped from the outside.
    await asyncio.Event().wait()


async def main() -> None:
    global loaded_strategies, current_strategy, betting_state, page_reload_lock
    
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    
    # Загрузить все стратегии из YAML
    loaded_strategies = _load_strategies()
    
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
        betting_state = _init_betting_state(current_strategy)
        _update_runtime_snapshot("startup")
        print(f"[STRATEGY] Загружена стратегия: {current_strategy['name']}", flush=True)
        print(f"[STRATEGY] Описание: {current_strategy['description']}", flush=True)
        print(f"[STRATEGY] Шагов: {len(current_strategy['coefficients'])}, базовая ставка: {BASE_BET}р", flush=True)
        
        # Показать примеры расчетов ставок
        print("[STRATEGY] Примеры ставок (BASE_BET × коэффициент):", flush=True)
        for i in range(min(5, len(current_strategy['coefficients']))):
            coeff = current_strategy['coefficients'][i]
            bet_amount = BASE_BET * coeff
            print(f"  Step {i+1}: {BASE_BET}р × {coeff} = {bet_amount}р ✓", flush=True)
        
        # Вывести информацию о динамическом режиме
        if DYNAMIC_BET_MODE:
            print("\n[DYNAMIC] 🔄 ДИНАМИЧЕСКИЙ РЕЖИМ ВКЛЮЧЕН", flush=True)
            print(f"[DYNAMIC] Окно анализа: {DYNAMIC_WINDOW_SIZE} ставок", flush=True)
            print(f"[DYNAMIC] Пересчет: каждые {DYNAMIC_RECALC_INTERVAL} ставок", flush=True)
            print(f"[DYNAMIC] Выбор по среднему значению: {'ON' if DYNAMIC_USE_AVERAGE_VALUE_SELECTION else 'OFF'}", flush=True)
            print(f"[DYNAMIC] Учитывать double: {'ON' if DYNAMIC_INCLUDE_DOUBLE_SELECTION else 'OFF'}", flush=True)
            print(f"[DYNAMIC] Фильтр по игроку: {'ON' if DYNAMIC_FILTER_BY_PLAYER else 'OFF'}", flush=True)
            print(f"[DYNAMIC] Фильтр по стороне: {'ON' if DYNAMIC_FILTER_BY_SIDE else 'OFF'}", flush=True)
            print(f"[DYNAMIC] Начальная ставка: {_format_outcome_pretty(BET_MODE_OUTCOME, BET_MODE_SPECIFIER)}", flush=True)

    args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--no-first-run",
            "--no-service-autorun",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--disable-translate",
            "--mute-audio",
            "--disable-notifications",
            "--disable-logging",
            "--metrics-recording-only",
            "--disable-hang-monitor",
            "--password-store=basic",
            "--autoplay-policy=no-user-gesture-required",
        ]

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
        
        status_line = "Браузер открыт. Профиль сессии: {}\n".format(SESSION_DIR)
        if BET_MODE_ENABLED:
            status_line += "🎲 РЕЖИМ СТАВОК ВКЛЮЧЕН\n"
            status_line += "  - Стратегия: {}\n".format(current_strategy['name'])
            status_line += "  - Цель: {} = {}\n".format(BET_MODE_OUTCOME, BET_MODE_SPECIFIER)
            status_line += "  - Базовая ставка: {}р\n".format(BASE_BET)
            status_line += "  - Коэффициентов в прогрессии: {}\n".format(len(current_strategy['coefficients']))
            status_line += "  - Задержка перед ставкой: {:.1f}-{:.1f}с\n".format(BET_DELAY_MIN, BET_DELAY_MAX)
        status_line += "  - Accounting stale timeout: {:.0f}с\n".format(ACCOUNTING_BALANCE_STALE_SECONDS)
        status_line += "  - Accounting recovery reload: {:.0f}с\n".format(ACCOUNTING_RECOVERY_RELOAD_SECONDS)
        status_line += "Закройте окно браузера или нажмите Enter здесь - сессия сохранится."
        
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
