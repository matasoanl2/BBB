"""
Patchright с одной постоянной сессией: данные профиля лежат в каталоге SESSION_DIR.
При каждом запуске используется тот же профиль; после закрытия браузера состояние остается на диске.
Сохранение данных в PostgreSQL вместо JSON.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from patchright.async_api import async_playwright
import psycopg2
from psycopg2.extras import Json

SESSION_DIR = Path(__file__).resolve().parent / "profile"
TARGET_WS_URL = "wss://ws.betboom.ru:444/api/nards_studio_ws/v1"
HEADLESS = os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes", "on"}

# PostgreSQL config
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "buybaybye")


def _get_db_connection():
    """Получить подключение к PostgreSQL с автоматическим созданием таблицы"""
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
                _save_target_ws_message(payload)

        def on_close(*_) -> None:
            print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)


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
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

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
        print(
            f"Браузер открыт. Профиль сессии: {SESSION_DIR}\n"
            "Закройте окно браузера или нажмите Enter здесь - сессия сохранится.",
            flush=True,
        )
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
