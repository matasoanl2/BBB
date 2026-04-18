"""Shared DB, time-filter, and strategy helpers for offline scripts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
import yaml


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    user: str
    password: str
    host: str
    port: str
    name: str


def load_database_settings() -> DatabaseSettings:
    return DatabaseSettings(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        name=os.getenv("DB_NAME", "buybaybye"),
    )


def connect_postgres(settings: DatabaseSettings):
    return psycopg2.connect(
        user=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.name,
    )


def parse_time_filter(time_filter: str) -> tuple[bool, str | None]:
    if time_filter == "all":
        return False, None
    try:
        return True, f"{int(time_filter)} hours"
    except ValueError:
        pass

    match = re.match(r"^(\d+)\s*(hour|hours|day|days|week|weeks|month|months)$", time_filter.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(
            f"❌ Неверный формат периода: '{time_filter}'\n"
            "Поддерживаемые форматы:\n"
            "  - 'all'\n"
            "  - '3' или '3hours'\n"
            "  - '1day', '7days'\n"
            "  - '1week', '2weeks'\n"
            "  - '1month', '3months'"
        )

    unit = match.group(2).lower().rstrip("s")
    unit_map = {"hour": "hours", "day": "days", "week": "weeks", "month": "months"}
    return True, f"{match.group(1)} {unit_map.get(unit, unit + 's')}"


def row_to_round(timestamp: Any, player_name: str, dice_results: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
        "results": {
            **dice_results,
            "player": {
                **(dice_results.get("player", {}) if isinstance(dice_results, dict) else {}),
                "name": player_name,
            },
        },
    }


def load_rounds_from_db(*, settings: DatabaseSettings, time_filter: str = "all") -> list[dict[str, Any]]:
    use_filter, interval_str = parse_time_filter(time_filter)
    conn = connect_postgres(settings)
    cursor = conn.cursor()
    if use_filter:
        cursor.execute(
            "SELECT timestamp, player_name, dice_results FROM game_results WHERE timestamp >= NOW() - INTERVAL %s ORDER BY timestamp ASC",
            (interval_str,),
        )
    else:
        cursor.execute("SELECT timestamp, player_name, dice_results FROM game_results ORDER BY timestamp ASC")
    rows = [row_to_round(timestamp, player_name, dice_results) for timestamp, player_name, dice_results in cursor.fetchall()]
    cursor.close()
    conn.close()
    return rows


def load_yaml_strategies(strategies_dir: Path) -> dict[str, dict[str, Any]]:
    strategies: dict[str, dict[str, Any]] = {}
    for strategy_file in sorted(strategies_dir.glob("*.yaml")):
        with open(strategy_file, "r", encoding="utf-8") as handle:
            strategies[strategy_file.stem] = yaml.safe_load(handle)
    return strategies