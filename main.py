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
from datetime import datetime, timezone
from pathlib import Path
from patchright.async_api import async_playwright
import psycopg2
from psycopg2.extras import Json
import yaml

SESSION_DIR = Path(__file__).resolve().parent / "profile"
STRATEGIES_DIR = Path(__file__).resolve().parent / "strategies"
TARGET_WS_URL = "wss://ws.betboom.ru:444/api/nards_studio_ws/v1"
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
STRATEGY_NAME = os.getenv("STRATEGY", "martingale_classic")  # название стратегии

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
COLOR_RESET = "\033[0m" if COLOR_ENABLED else ""

# Хранилище загруженных стратегий
loaded_strategies = {}
current_strategy = None
jwt_token_global = None  # Глобальное хранилище найденного JWT токена


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
    except Exception as e:
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
        except:
            pass
    except Exception as e:
        pass  # Игнорируем ошибки


def _subscribe_jwt_search_to_page(page) -> None:
    """
    Подписать поиск JWT токена на события ответов и запросов страницы
    """
    page.on("response", _handle_response)
    page.on("request", _handle_request)

def _validate_base_bet(bet_amount: float) -> bool:
    """Проверить, делится ли ставка на 10 нацело"""
    return bet_amount % 10 == 0


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
        error_msg += f"\nВсе коэффициенты должны быть целыми числами, чтобы при умножении на BASE_BET (кратную 10) давать кратное 10"
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
            print(f"[ERROR] Не удалось загрузить ни одну стратегию", flush=True)
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
        "last_bet_amount": 0.0,
        "total_bet_amount": 0.0,
        "total_profit": 0.0,
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


async def _place_bet(page, outcome: str, specifier: str, amount: float) -> bool:
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
    # Проверить что JWT токен найден перед размещением ставки
    global jwt_token_global
    if not jwt_token_global:
        print(f"[WARNING] JWT токен ещё не найден! Ставка НЕ будет размещена.", flush=True)
        return False
    
    # Валидировать, что ставка делится на 10 нацело
    if not _validate_base_bet(amount):
        print(f"[ERROR] Ставка {amount}р ДОЛЖНА делиться на 10 нацело! Ставка НЕ размещена.", flush=True)
        return False
    
    # Случайная задержка "человеческого" поведения
    delay = random.uniform(BET_DELAY_MIN, BET_DELAY_MAX)
    await asyncio.sleep(delay)
    
    try:
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
            print(f"[DEBUG] ========== BET REQUEST ==========", flush=True)
            print(f"[DEBUG] Page URL: {page.url}", flush=True)
            print(f"[DEBUG] API URL: {BET_API_URL}", flush=True)
            print(f"[DEBUG] Payload: {json.dumps(payload)}", flush=True)
            print(f"[DEBUG] Headers sent: {json.dumps({k: v[:50] + '...' if len(str(v)) > 50 else v for k, v in headers.items()})}", flush=True)
            print(f"[DEBUG] Response Status: {status_code}", flush=True)
            print(f"[DEBUG] Response Body: {response_text}", flush=True)
            print(f"[DEBUG] ==================================", flush=True)
            
            if status_code != 200:
                print(f"[DEBUG] Статус: {status_code}", flush=True)
                print(f"[DEBUG] Ответ: {response_text[:500]}", flush=True)
                print(f"[DEBUG] Headers: {dict(response.headers)}", flush=True)
        # Сохранить информацию о ставке в БД
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()
            
            if status_code == 200:
                bet_status = "pending"
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15

                payout_coeff = current_strategy.get("payout_coefficient", 5.7) if current_strategy else 5.7
                potential_win = amount * payout_coeff
                potential_margin = potential_win - amount
                roi = _calculate_roi()
                time_str = datetime.now().strftime("%H:%M:%S")

                print(
                    f"[{time_str}] [BET] [SET ✓] {outcome}={specifier} | "
                    f"Ставка: {COLOR_YELLOW}{amount}р{COLOR_RESET} | "
                    f"Шаг: {betting_state.get('current_step', 0)+1}/{max_steps} | "
                    f"Профит: +{potential_margin:.0f}р | "
                    f"ROI: {COLOR_CYAN}{roi:.2f}%{COLOR_RESET}",
                    flush=True
                )
            else:
                bet_status = "error"
                time_str = datetime.now().strftime("%H:%M:%S")
                print(f"{COLOR_RED}[{time_str}] [BET] [SET ✗] Ошибка {status_code}: {response_text[:200]}{COLOR_RESET}", flush=True)
            
            cursor.execute("""
                INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (datetime.now(timezone.utc), outcome, specifier, amount, STRATEGY_NAME, betting_state.get('current_step', 0), bet_status))
            
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[DB ERROR] Ошибка сохранения ставки: {e}", flush=True)
        
        return status_code == 200
                    
    except Exception as e:
        time_str = datetime.now().strftime("%H:%M:%S")
        print(f"{COLOR_RED}[{time_str}] [BET] [SET ✗] Ошибка при размещении ставки: {e}{COLOR_RESET}", flush=True)
        return False


def _wire_ws_logging(page) -> None:
    def on_websocket(ws) -> None:
        is_target = ws.url.startswith(TARGET_WS_URL)
        tag = "TARGET-WS" if is_target else "WS"
        if WS_LOG_ENABLED:
            print(f"[{tag} OPEN] {ws.url}", flush=True)

        def on_sent(payload) -> None:
            if WS_LOG_ENABLED:
                print(f"[{tag} >>] {_format_ws_payload(payload)}", flush=True)

        def on_received(payload) -> None:
            if WS_LOG_ENABLED:
                print(f"[{tag} <<] {_format_ws_payload(payload)}", flush=True)
            if is_target:
                # Сохранить результат раунда
                _save_target_ws_message(payload)
                
                # Если включен режим ставок, заполнить результат предыдущей ставки + разместить новую
                if BET_MODE_ENABLED:
                    asyncio.create_task(_process_betting_round(page, payload))

        def on_close(*_) -> None:
            if WS_LOG_ENABLED:
                print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)


def _calculate_roi() -> float:
    total_bet = betting_state.get("total_bet_amount", 0)
    total_profit = betting_state.get("total_profit", 0)

    if total_bet == 0:
        return 0.0
    
    return (total_profit / total_bet) * 100


async def _process_betting_round(page, payload: object) -> None:
    """
    Обработать раунд: обновить результат предыдущей ставки и разместить новую
    """
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
    
    # Проверить тип ставки (цвет или дубль)
    matching_dice = None
    is_win = False
    actual_dice_representation = None
    
    if BET_MODE_OUTCOME == "double":
        # Ставка на любой дубль (когда оба кубика равны друг другу)
        dice_values = [d.get("value") for d in dice_results]
        # Дубль: оба кубика одного значения
        is_double = len(dice_values) == 2 and dice_values[0] == dice_values[1]
        actual_dice_value = dice_values[0] if is_double else None
        actual_dice_representation = f"double({actual_dice_value})" if is_double else "no_double"
        is_win = is_double
    else:
        # Ставка на цвет
        for dice in dice_results:
            if dice.get("color") == BET_MODE_OUTCOME:
                matching_dice = dice
                break
        target_dice_value = int(BET_MODE_SPECIFIER)
        actual_dice_value = matching_dice.get("value") if matching_dice else None
        actual_dice_representation = f"{BET_MODE_OUTCOME}({actual_dice_value})" if actual_dice_value else f"no_{BET_MODE_OUTCOME}"
        is_win = (actual_dice_value == target_dice_value)
    
    # Обновить результат предыдущей ставки (если была)
    if betting_state["last_bet_amount"] > 0:
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()
            
            # Проверить, выиграла ли предыдущая ставка
            
            
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
                time_str = datetime.now().strftime("%H:%M:%S")
                print(
                    f"{COLOR_GREEN}[{time_str}] [BET] [RESULT ✓] {actual_dice_representation} | "
                    f"Ставка: {COLOR_YELLOW}{bet_amount}р{COLOR_GREEN} | "
                    f"Выигрыш: {COLOR_YELLOW}{winnings:.0f}р{COLOR_GREEN} | "
                    f"Профит: +{margin:.0f}р | "
                    f"ROI: {COLOR_CYAN}{roi:.2f}%{COLOR_GREEN} | "
                    f"Баланс: {COLOR_CYAN}{betting_state['session_balance']:.0f}р | "
                    f"Прогрессия сброшена{COLOR_RESET}",
                    flush=True
                )
            else:
                # Проигрыш
                status = "loss"
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                bet_amount = betting_state['last_bet_amount']
                margin = -bet_amount
                betting_state["total_profit"] += margin
                betting_state["session_balance"] += margin
                if betting_state["current_step"] + 1 == max_steps:
                    betting_state["consecutive_losses"] = 0
                    betting_state["current_step"] = 0
                    roi = _calculate_roi()
                    time_str = datetime.now().strftime("%H:%M:%S")

                    print(
                        f"{COLOR_RED}[{time_str}] [BET] [RESULT ✗] {actual_dice_representation} | "
                        f"Ставка: {COLOR_YELLOW}{bet_amount}р{COLOR_RED} | "
                        f"Профит: {margin:.0f}р | "
                        f"ROI: {COLOR_CYAN}{roi:.2f}%{COLOR_RED} | "
                        f"Баланс: {COLOR_CYAN}{betting_state['session_balance']:.0f}р | "
                        f"Достигнут максимум шагов. Прогрессия сброшена{COLOR_RESET}",
                        flush=True
                    )
                else:
                    status = "loss"
                    betting_state["consecutive_losses"] += 1
                    betting_state["current_step"] = min(betting_state["current_step"] + 1, max_steps - 1)
                    roi = _calculate_roi()
                    time_str = datetime.now().strftime("%H:%M:%S")

                    print(
                        f"{COLOR_RED}[{time_str}] [BET] [RESULT ✗] {actual_dice_representation} | "
                        f"Ставка: {COLOR_YELLOW}{bet_amount}р{COLOR_RED} | "
                        f"Профит: {margin:.0f}р | "
                        f"ROI: {COLOR_CYAN}{roi:.2f}%{COLOR_RED} | "
                        f"Баланс: {COLOR_CYAN}{betting_state['session_balance']:.0f}р | "
                        f"Шаг {betting_state['current_step']+1}/{max_steps}{COLOR_RESET}",
                        flush=True
                    )
            
            # Обновить последнюю ставку в БД
            cursor.execute("""
                UPDATE bet_history 
                SET status = %s, result_dice_color = %s, result_dice_value = %s
                WHERE id = (SELECT MAX(id) FROM bet_history)
            """, (status, 
                  matching_dice.get("color") if matching_dice else "double", 
                  actual_dice_value))
            
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[DB ERROR] Ошибка обновления результата ставки: {e}", flush=True)
    
    # Разместить новую ставку
    bet_amount = _calculate_bet_amount()
    await _place_bet(page, BET_MODE_OUTCOME, BET_MODE_SPECIFIER, bet_amount)


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
    global loaded_strategies, current_strategy, betting_state
    
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
        print(f"[STRATEGY] Загружена стратегия: {current_strategy['name']}", flush=True)
        print(f"[STRATEGY] Описание: {current_strategy['description']}", flush=True)
        print(f"[STRATEGY] Шагов: {len(current_strategy['coefficients'])}, базовая ставка: {BASE_BET}р", flush=True)
        
        # Показать примеры расчетов ставок
        print(f"[STRATEGY] Примеры ставок (BASE_BET × коэффициент):", flush=True)
        for i in range(min(5, len(current_strategy['coefficients']))):
            coeff = current_strategy['coefficients'][i]
            bet_amount = BASE_BET * coeff
            print(f"  Step {i+1}: {BASE_BET}р × {coeff} = {bet_amount}р ✓", flush=True)

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
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=HEADLESS,
        args=args,
    )
    try:
        for existing_page in context.pages:
            _wire_ws_logging(existing_page)
            _subscribe_jwt_search_to_page(existing_page)
        
        context.on("page", _wire_ws_logging)
        context.on("page", _subscribe_jwt_search_to_page)

        page = context.pages[0] if context.pages else await context.new_page()
        
        print(f"[DEBUG] Поиск JWT токена в ответах...", flush=True)
        await page.goto("https://betboom.ru/game/nardsgame")
        
        status_line = "Браузер открыт. Профиль сессии: {}\n".format(SESSION_DIR)
        if BET_MODE_ENABLED:
            status_line += "🎲 РЕЖИМ СТАВОК ВКЛЮЧЕН\n"
            status_line += "  - Стратегия: {}\n".format(current_strategy['name'])
            status_line += "  - Цель: {} = {}\n".format(BET_MODE_OUTCOME, BET_MODE_SPECIFIER)
            status_line += "  - Базовая ставка: {}р\n".format(BASE_BET)
            status_line += "  - Коэффициентов в прогрессии: {}\n".format(len(current_strategy['coefficients']))
            status_line += "  - Задержка перед ставкой: {:.1f}-{:.1f}с\n".format(BET_DELAY_MIN, BET_DELAY_MAX)
        status_line += "Закройте окно браузера или нажмите Enter здесь - сессия сохранится."
        
        print(status_line, flush=True)
        await _wait_for_exit_signal()
    finally:
        await context.close()
        await playwright.stop()

    print("Контекст закрыт, профиль записан. Следующий запуск продолжит ту же сессию.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
