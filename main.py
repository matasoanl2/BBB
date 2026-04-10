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
import aiohttp
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
BET_MODE_OUTCOME = os.getenv("BET_OUTCOME", "red")  # red или black
BET_MODE_SPECIFIER = os.getenv("BET_SPECIFIER", "5")  # значение кубика (1-6)
BASE_BET = float(os.getenv("BASE_BET", "10"))  # базовая ставка (должна делиться на 10)
STRATEGY_NAME = os.getenv("STRATEGY", "martingale_classic")  # название стратегии

# Случайная задержка перед ставкой (в секундах)
BET_DELAY_MIN = float(os.getenv("BET_DELAY_MIN", "0.8"))
BET_DELAY_MAX = float(os.getenv("BET_DELAY_MAX", "1.5"))

# Хранилище загруженных стратегий
loaded_strategies = {}
current_strategy = None


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
    Разместить ставку через API betboom
    
    Args:
        page: Объект страницы Playwright для доступа к cookies
        outcome: "red" или "black"
        specifier: значение кубика (1-6)
        amount: сумма ставки
        
    Returns:
        True если ставка успешна, False иначе
    """
    # Валидировать, что ставка делится на 10 нацело
    if not _validate_base_bet(amount):
        print(f"[ERROR] Ставка {amount}р ДОЛЖНА делиться на 10 нацело! Ставка НЕ размещена.", flush=True)
        return False
    
    # Случайная задержка "человеческого" поведения
    delay = random.uniform(BET_DELAY_MIN, BET_DELAY_MAX)
    await asyncio.sleep(delay)
    
    try:
        # Получить cookies из браузера для аутентификации
        cookies = await page.context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        
        # Подготовить payload для ставки
        payload = {
            "bets": [
                {
                    "market": "value",
                    "outcome": outcome,
                    "specifier": specifier,
                    "sum": amount,
                    "balance_type": "balance"
                }
            ]
        }
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        
        # Отправить ставку
        async with aiohttp.ClientSession(cookies=cookie_dict) as session:
            async with session.post(BET_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                # Сохранить информацию о ставке в БД
                try:
                    conn = _get_db_connection()
                    cursor = conn.cursor()
                    
                    status = "pending"
                if resp.status == 200:
                        status = "pending"  # Статус будет обновлен при получении результата
                        max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                        print(f"[BET ✓] Ставка разм.: {outcome}={specifier}, сумма={amount}р (шаг {betting_state['current_step']+1}/{max_steps}, стратегия: {current_strategy.get('name', 'unknown')})", flush=True)
                    else:
                        status = "error"
                        error_text = await resp.text()
                        print(f"[BET ✗] Ошибка ({resp.status}): {error_text[:200]}", flush=True)
                    
                    cursor.execute("""
                        INSERT INTO bet_history (timestamp, outcome, specifier, amount, strategy, bet_step, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (datetime.now(timezone.utc), outcome, specifier, amount, BETTING_STRATEGY, betting_state['current_step'], status))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                except Exception as e:
                    print(f"[DB ERROR] Ошибка сохранения ставки: {e}", flush=True)
                
                return resp.status == 200
                    
    except asyncio.TimeoutError:
        print(f"[BET ✗] Timeout при отправке ставки", flush=True)
        return False
    except Exception as e:
        print(f"[BET ✗] Ошибка при размещении ставки: {e}", flush=True)
        return False


def _wire_ws_logging(page) -> None:
    def on_websocket(ws) -> None:
        is_target = ws.url.startswith(TARGET_WS_URL)
        tag = "TARGET-WS" if is_target else "WS"
        print(f"[{tag} OPEN] {ws.url}", flush=True)

        def on_sent(payload) -> None:
            print(f"[{tag} >>] {_format_ws_payload(payload)}", flush=True)

        def on_received(payload) -> None:
            print(f"[{tag} <<] {_format_ws_payload(payload)}", flush=True)
            if is_target:
                # Сохранить результат раунда
                _save_target_ws_message(payload)
                
                # Если включен режим ставок, заполнить результат предыдущей ставки + разместить новую
                if BET_MODE_ENABLED:
                    asyncio.create_task(_process_betting_round(page, payload))

        def on_close(*_) -> None:
            print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)


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
    matching_dice = None
    for dice in dice_results:
        if dice.get("color") == BET_MODE_OUTCOME:
            matching_dice = dice
            break
    
    # Обновить результат предыдущей ставки (если была)
    if betting_state["last_bet_amount"] > 0:
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()
            
            # Проверить, выиграла ли предыдущая ставка
            target_dice_value = int(BET_MODE_SPECIFIER)
            actual_dice_value = matching_dice.get("value") if matching_dice else None
            
            if actual_dice_value == target_dice_value:
                # Выигрыш
                status = "win"
                betting_state["consecutive_losses"] = 0
                betting_state["current_step"] = 0
                print(f"[RESULT ✓] Угадали! {BET_MODE_OUTCOME}={actual_dice_value}. Прогрессия сброшена.", flush=True)
            else:
                # Проигрыш
                status = "loss"
                betting_state["consecutive_losses"] += 1
                max_steps = len(current_strategy.get("coefficients", [1])) if current_strategy else 15
                betting_state["current_step"] = min(betting_state["current_step"] + 1, max_steps - 1)
                print(f"[RESULT ✗] Не угадали. {BET_MODE_OUTCOME}={actual_dice_value} (ставили на {target_dice_value}). Шаг {betting_state['current_step']+1}/{max_steps}", flush=True)
            
            # Обновить последнюю ставку в БД
            cursor.execute("""
                UPDATE bet_history 
                SET status = %s, result_dice_color = %s, result_dice_value = %s
                WHERE id = (SELECT MAX(id) FROM bet_history)
            """, (status, matching_dice.get("color") if matching_dice else None, actual_dice_value))
            
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
        context.on("page", _wire_ws_logging)

        page = context.pages[0] if context.pages else await context.new_page()
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
