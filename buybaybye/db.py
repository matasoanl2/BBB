from __future__ import annotations

from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json


def get_db_connection(*, user: str, password: str, host: str, port: str, database: str):
    """Получить подключение к PostgreSQL с автоматическим созданием таблиц."""
    conn = psycopg2.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )

    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS game_results (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE,
            player_name TEXT,
            dice_results JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """
    )
    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_timestamp ON game_results(timestamp)""")
    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_player ON game_results(player_name)""")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bet_history (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE,
            outcome TEXT,
            specifier TEXT,
            amount FLOAT,
            strategy TEXT,
            bet_step INTEGER,
            status TEXT,
            result_dice_color TEXT,
            result_dice_value INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """
    )
    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_bet_timestamp ON bet_history(timestamp)""")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_snapshot (
            snapshot_key TEXT PRIMARY KEY,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            payload JSONB NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_events (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            event_type TEXT,
            payload JSONB NOT NULL
        )
        """
    )
    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_runtime_events_timestamp ON runtime_events(timestamp)""")

    conn.commit()
    cursor.close()
    return conn


def save_target_ws_message(*, payload_text: str, get_db_connection_func) -> None:
    """Сохранить rng_values сообщение в PostgreSQL."""
    import json

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
        conn = get_db_connection_func()
        cursor = conn.cursor()

        player_name = results.get("player", {}).get("name", "unknown")
        timestamp = datetime.now(timezone.utc)

        cursor.execute(
            """
            INSERT INTO game_results (timestamp, player_name, dice_results)
            VALUES (%s, %s, %s)
            """,
            (timestamp, player_name, Json(results)),
        )

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        print(f"[DB ERROR] Ошибка сохранения в БД: {exc}", flush=True)