"""Вспомогательные функции PostgreSQL для рантайма и служебных утилит."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json

from buybaybye.core.runtime_config import DatabaseConfig


_INITIALIZED_DATABASES: set[tuple[str, str, str, str, str]] = set()


def connect_postgres_with_retry(*, fatal_context: str = "postgresql", **connect_kwargs):
    """Подключиться к PostgreSQL с ретраями и аварийным выходом после 10 одинаковых ошибок."""

    last_error_signature: tuple[str, str] | None = None
    repeated_error_count = 0

    while True:
        try:
            return psycopg2.connect(**connect_kwargs)
        except psycopg2.Error as exc:
            error_signature = (type(exc).__name__, str(exc).strip())
            if error_signature == last_error_signature:
                repeated_error_count += 1
            else:
                last_error_signature = error_signature
                repeated_error_count = 1

            print(
                (
                    f"[DB ERROR] Ошибка подключения к PostgreSQL ({fatal_context}); "
                    f"повтор {repeated_error_count}/10: {exc}"
                ),
                flush=True,
            )

            if repeated_error_count >= 10:
                print(
                    (
                        f"[FATAL] Приложение завершает работу: не удалось подключиться к PostgreSQL "
                        f"после 10 одинаковых ошибок ({fatal_context}): {exc}"
                    ),
                    flush=True,
                )
                raise SystemExit(1) from exc

            time.sleep(1)


def _database_identity(database_config: DatabaseConfig) -> tuple[str, str, str, str, str]:
    return (
        database_config.host,
        database_config.port,
        database_config.user,
        database_config.password,
        database_config.name,
    )


def ensure_runtime_schema(*, database_config: DatabaseConfig) -> None:
    """Initialize runtime schema once per configured database."""

    identity = _database_identity(database_config)
    if identity in _INITIALIZED_DATABASES:
        return

    conn = connect_postgres_with_retry(
        fatal_context="runtime schema initialization",
        user=database_config.user,
        password=database_config.password,
        host=database_config.host,
        port=database_config.port,
        database=database_config.name,
    )

    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS game_results (
            id SERIAL PRIMARY KEY,
            game_id TEXT,
            timestamp TIMESTAMP WITH TIME ZONE,
            player_name TEXT,
            dice_results JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
        """
    )
    cursor.execute("""ALTER TABLE game_results ADD COLUMN IF NOT EXISTS game_id TEXT""")
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_game_results_game_id ON game_results(game_id)""")
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
    cursor.execute("""ALTER TABLE bet_history ADD COLUMN IF NOT EXISTS slot INTEGER DEFAULT 1""")

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
    cursor.execute("""CREATE INDEX IF NOT EXISTS idx_runtime_events_id ON runtime_events(id)""")
    conn.commit()
    cursor.close()
    conn.close()
    _INITIALIZED_DATABASES.add(identity)


def get_db_connection(*, database_config: DatabaseConfig):
    """Создать подключение к PostgreSQL и гарантировать наличие runtime-схемы."""
    return psycopg2.connect(
        user=database_config.user,
        password=database_config.password,
        host=database_config.host,
        port=database_config.port,
        database=database_config.name,
    )


def save_target_ws_message(*, payload_text: str, get_db_connection_func) -> None:
    """Сохранить одно rng_values websocket-сообщение в PostgreSQL."""
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

        game_id_value = parsed_payload.get("game_id")
        game_id = str(game_id_value).strip() or None if game_id_value is not None else None
        player_name = results.get("player", {}).get("name", "unknown")
        timestamp = datetime.now(timezone.utc)

        cursor.execute(
            """
            INSERT INTO game_results (game_id, timestamp, player_name, dice_results)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (game_id) DO NOTHING
            """,
            (game_id, timestamp, player_name, Json(results)),
        )

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as exc:
        print(f"[DB ERROR] Ошибка сохранения в БД: {exc}", flush=True)