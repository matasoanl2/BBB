"""FastAPI-дашборд для текущего состояния рантайма и недавней истории ставок."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="BuyBayBye Dashboard")


DEFAULT_SNAPSHOT = {
    "event_type": "boot",
    "updated_at": None,
    "snapshot_key": None,
    "runtime_role": None,
    "bet_mode_enabled": False,
    "dynamic_bet_mode": False,
    "strategy_display_name": None,
    "current_step": None,
    "max_steps": None,
    "consecutive_losses": 0,
    "session_balance": 0.0,
    "account_balance": None,
    "total_profit": 0.0,
    "total_bets_placed": 0,
    "external_deposits_total": 0.0,
    "external_withdrawals_total": 0.0,
    "configured_outcome": None,
    "configured_targets": [],
    "current_outcome": None,
    "current_specifier": None,
    "configured_specifiers": [],
    "configured_specifier_index": 0,
    "specifier_rotation_enabled": False,
    "multi_bet_enabled": False,
    "last_round_result": None,
    "last_set_status": None,
    "last_set_error": None,
}

RUNTIME_ROLE_FIELDS = (
    "runtime_role",
    "role",
    "service_role",
    "instance_role",
    "container_role",
    "app_role",
)


def _build_default_snapshot() -> dict[str, Any]:
    """Создать новый словарь snapshot defaults без разделяемых mutable-значений."""

    snapshot = dict(DEFAULT_SNAPSHOT)
    snapshot["configured_targets"] = []
    snapshot["configured_specifiers"] = []
    return snapshot


def _get_db_connection():
    """Создать подключение к PostgreSQL для dashboard-запросов."""

    return psycopg2.connect(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "buybaybye"),
        cursor_factory=RealDictCursor,
    )


def _ensure_dashboard_schema() -> None:
    """Гарантировать наличие таблиц, которые читает и заполняет dashboard."""

    conn = _get_db_connection()
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
    conn.commit()
    cursor.close()
    conn.close()


@app.on_event("startup")
def _startup() -> None:
    """Подготовить dashboard schema при старте FastAPI-приложения."""

    _ensure_dashboard_schema()


def _fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Выполнить SQL-запрос и вернуть одну строку в виде словаря."""

    conn = _get_db_connection()
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return dict(row) if row else None


def _fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Выполнить SQL-запрос и вернуть все строки как список словарей."""

    conn = _get_db_connection()
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return rows


def _iso(value: Any) -> str | None:
    """Преобразовать datetime или произвольное значение в строку для JSON-ответа."""

    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _format_target(outcome: str | None, specifier: str | None) -> str:
    """Собрать компактную подпись цели ставки или результата для dashboard UI."""

    if not outcome:
        return "-"
    if outcome == "double":
        return "DOUBLE"
    if specifier:
        return f"{outcome.upper()} {specifier}"
    return outcome.upper()


def _normalize_runtime_role(value: Any) -> str | None:
    """Привести возможные варианты role-маркера к bettor или collector."""

    if not isinstance(value, str):
        return None

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return None
    if "bettor" in normalized or "betting" in normalized:
        return "bettor"
    if "collector" in normalized or normalized.startswith("collect"):
        return "collector"
    return None


def _extract_runtime_role(payload: dict[str, Any] | None, snapshot_key: str | None = None) -> str | None:
    """Определить runtime role из payload metadata или из имени snapshot key."""

    if isinstance(payload, dict):
        for field_name in RUNTIME_ROLE_FIELDS:
            role = _normalize_runtime_role(payload.get(field_name))
            if role:
                return role
    return _normalize_runtime_role(snapshot_key)


def _snapshot_priority(snapshot_key: str | None, runtime_role: str | None) -> int:
    """Вернуть приоритет snapshot-источника: bettor -> collector -> legacy live -> прочее."""

    if runtime_role == "bettor":
        return 0
    if runtime_role == "collector":
        return 1
    if snapshot_key == "live":
        return 2
    return 3


def _snapshot_updated_at_sort_value(value: Any) -> datetime:
    """Нормализовать updated_at для стабильного сравнения snapshot-строк."""

    if isinstance(value, datetime):
        return value
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _select_runtime_event_rows(limit: int, preferred_role: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Выбрать согласованный поток runtime events без смешивания bettor и collector."""

    fetch_limit = max(limit * 6, limit)
    rows = _fetch_all(
        """
        SELECT id, timestamp, event_type, payload
        FROM runtime_events
        ORDER BY id DESC
        LIMIT %s
        """,
        (fetch_limit,),
    )

    annotated_rows = []
    tagged_roles: set[str] = set()
    for row in rows:
        payload = row.get("payload") or {}
        runtime_role = _extract_runtime_role(payload)
        if runtime_role:
            tagged_roles.add(runtime_role)
        annotated = dict(row)
        annotated["payload"] = payload
        annotated["runtime_role"] = runtime_role
        annotated_rows.append(annotated)

    selected_role = None
    if preferred_role in tagged_roles:
        selected_role = preferred_role
    elif "bettor" in tagged_roles:
        selected_role = "bettor"
    elif "collector" in tagged_roles:
        selected_role = "collector"

    if selected_role is None:
        filtered_rows = annotated_rows[:limit]
    else:
        filtered_rows = [row for row in annotated_rows if row.get("runtime_role") == selected_role][:limit]

    filtered_rows.reverse()
    return filtered_rows, selected_role


def _parse_round(row: dict[str, Any]) -> dict[str, Any]:
    """Преобразовать строку game_results в сериализованное представление раунда."""

    dice_results = row.get("dice_results") or {}
    dice = dice_results.get("dice", []) if isinstance(dice_results, dict) else []
    player = dice_results.get("player", {}) if isinstance(dice_results, dict) else {}
    position = player.get("position") if isinstance(player, dict) else None

    # Всегда явно сериализуем оба значения кубиков
    red_value = None
    yellow_value = None

    # Собираем значения кубиков по цвету
    for die in dice:
        if not isinstance(die, dict):
            continue
        color = die.get("color")
        value = die.get("value")
        if color == "red":
            red_value = value
        elif color == "yellow":
            yellow_value = value

    # Если какого-то кубика нет, явно выставляем None
    if red_value is None:
        red_value = None
    if yellow_value is None:
        yellow_value = None

    is_double = red_value is not None and yellow_value is not None and red_value == yellow_value
    if red_value is None and yellow_value is None:
        display = "-"
    elif is_double:
        display = f"DOUBLE {red_value}"
    else:
        display = f"RED {red_value if red_value is not None else '-'} / YELLOW {yellow_value if yellow_value is not None else '-'}"

    return {
        "id": row.get("id"),
        "timestamp": _iso(row.get("timestamp")),
        "player_name": row.get("player_name") or "unknown",
        "position": position or "-",
        "red_value": red_value,
        "yellow_value": yellow_value,
        "is_double": is_double,
        "display": display,
    }


def _get_snapshot() -> dict[str, Any]:
    """Вернуть наиболее подходящий runtime snapshot: bettor, затем collector, затем legacy live."""

    rows = _fetch_all(
        """
        SELECT snapshot_key, updated_at, payload
        FROM runtime_snapshot
        ORDER BY updated_at DESC NULLS LAST, snapshot_key ASC
        """
    )
    if not rows:
        return _build_default_snapshot()

    ranked_rows = []
    for index, row in enumerate(rows):
        payload = row.get("payload") or {}
        snapshot_key = row.get("snapshot_key")
        runtime_role = _extract_runtime_role(payload, snapshot_key)
        ranked_rows.append((
            _snapshot_updated_at_sort_value(row.get("updated_at")),
            -_snapshot_priority(snapshot_key, runtime_role),
            index,
            row,
            runtime_role,
        ))

    _, _, _, selected_row, runtime_role = sorted(
        ranked_rows,
        key=lambda item: (item[0], item[1], item[2]),
        reverse=True,
    )[0]

    payload = _build_default_snapshot()
    payload.update(selected_row.get("payload") or {})
    payload["updated_at"] = _iso(selected_row.get("updated_at"))
    payload["snapshot_key"] = selected_row.get("snapshot_key")
    payload["runtime_role"] = runtime_role
    return payload


def _get_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Собрать сводные метрики dashboard из snapshot и агрегатов bet_history."""

    bets = _fetch_one(
        """
        SELECT
            COUNT(*)::int AS total_bets,
            COUNT(*) FILTER (WHERE status = 'win')::int AS wins,
            COUNT(*) FILTER (WHERE status = 'loss')::int AS losses,
            COUNT(*) FILTER (WHERE status LIKE 'skipped%')::int AS skipped
        FROM bet_history
        """
    ) or {"total_bets": 0, "wins": 0, "losses": 0, "skipped": 0}

    rounds = _fetch_one("SELECT COUNT(*)::int AS total_rounds FROM game_results") or {"total_rounds": 0}
    win_rate = 0.0
    resolved = bets["wins"] + bets["losses"]
    if resolved > 0:
        win_rate = bets["wins"] / resolved * 100.0

    session_balance = float(snapshot.get("session_balance") or 0.0)
    account_balance = snapshot.get("account_balance")
    delta = None
    if isinstance(account_balance, (int, float)):
        delta = float(account_balance) - session_balance

    current_step = snapshot.get("current_step")
    max_steps = snapshot.get("max_steps")
    step_label = "-"
    if current_step is not None and max_steps:
        step_label = f"{int(current_step) + 1}/{int(max_steps)}"

    return {
        "session_balance": session_balance,
        "account_balance": account_balance,
        "balance_delta": delta,
        "step_label": step_label,
        "consecutive_losses": int(snapshot.get("consecutive_losses") or 0),
        "deposits_total": float(snapshot.get("external_deposits_total") or 0.0),
        "withdrawals_total": float(snapshot.get("external_withdrawals_total") or 0.0),
        "session_total_bets": int(snapshot.get("total_bets_placed") or 0),
        "all_time_bets": bets["total_bets"],
        "all_time_rounds": rounds["total_rounds"],
        "wins": bets["wins"],
        "losses": bets["losses"],
        "skipped": bets["skipped"],
        "win_rate": win_rate,
    }


def _get_recent_bets(limit: int = 20) -> list[dict[str, Any]]:
    """Загрузить последние ставки и подготовить их к отображению в dashboard."""

    rows = _fetch_all(
        """
        SELECT id, timestamp, outcome, specifier, amount, strategy, bet_step, status,
               result_dice_color, result_dice_value
        FROM bet_history
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )
    result = []
    for row in rows:
        result.append({
            "id": row.get("id"),
            "timestamp": _iso(row.get("timestamp")),
            "target": _format_target(row.get("outcome"), row.get("specifier")),
            "amount": row.get("amount"),
            "strategy": row.get("strategy"),
            "step": (row.get("bet_step") + 1) if isinstance(row.get("bet_step"), int) else None,
            "status": row.get("status"),
            "result": _format_target(row.get("result_dice_color"), row.get("result_dice_value")),
        })
    return result


def _get_latest_win() -> dict[str, Any] | None:
    """Вернуть самую свежую выигранную ставку для клиентской win-анимации."""

    row = _fetch_one(
        """
        SELECT bh.id, bh.timestamp, bh.outcome, bh.specifier, bh.amount, bh.strategy, 
               bh.bet_step, bh.status, bh.result_dice_color, bh.result_dice_value, 
               gr.red_value, gr.yellow_value
        FROM bet_history bh
        LEFT JOIN LATERAL (
            SELECT gr.id, gr.timestamp, 
                   (gr.dice_results->'dice')::jsonb->0->>'value' AS red_value,
                   (gr.dice_results->'dice')::jsonb->1->>'value' AS yellow_value
            FROM game_results gr
            WHERE gr.timestamp >= bh.timestamp
            ORDER BY gr.timestamp ASC
            LIMIT 1
        ) gr ON TRUE
        WHERE bh.status = 'win'
        ORDER BY bh.id DESC
        LIMIT 1
        """
    )

    if not row:
        return None

    return {
        "id": row.get("id"),
        "timestamp": _iso(row.get("timestamp")),
        "target": _format_target(row.get("outcome"), row.get("specifier")),
        "amount": row.get("amount"),
        "strategy": row.get("strategy"),
        "step": (row.get("bet_step") + 1) if isinstance(row.get("bet_step"), int) else None,
        "status": row.get("status"),
        "result": _format_target(row.get("result_dice_color"), row.get("result_dice_value")),
        "red_value": row.get("red_value"),
        "yellow_value": row.get("yellow_value"),
    }


def _get_recent_rounds(limit: int = 20) -> list[dict[str, Any]]:
    """Загрузить последние игровые раунды и преобразовать их в UI-формат."""

    rows = _fetch_all(
        """
        SELECT id, timestamp, player_name, dice_results
        FROM game_results
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [_parse_round(row) for row in rows]


def _get_balance_series(limit: int = 160, preferred_role: str | None = None) -> list[dict[str, Any]]:
    """Построить временной ряд balance по согласованному потоку runtime events."""

    rows, selected_role = _select_runtime_event_rows(limit=limit, preferred_role=preferred_role)
    result = []
    for row in rows:
        payload = row.get("payload") or {}
        session_balance = payload.get("session_balance")
        account_balance = payload.get("account_balance")
        result.append({
            "timestamp": _iso(row.get("timestamp")),
            "event_type": row.get("event_type"),
            "session_balance": float(session_balance) if session_balance not in (None, "") else None,
            "account_balance": float(account_balance) if account_balance not in (None, "") else None,
            "runtime_role": row.get("runtime_role") or selected_role,
        })
    return result


def _get_result_curve(limit: int = 160) -> list[dict[str, Any]]:
    """Построить кривую wins/losses и rolling win-rate по истории resolved ставок."""

    rows = _fetch_all(
        """
        SELECT id, timestamp, status
        FROM bet_history
        WHERE status IN ('win', 'loss')
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows.reverse()

    wins = 0
    losses = 0
    history: list[int] = []
    curve = []
    for index, row in enumerate(rows, start=1):
        status = row.get("status")
        if status == "win":
            wins += 1
            history.append(1)
        elif status == "loss":
            losses += 1
            history.append(0)

        recent20 = history[-20:]
        recent50 = history[-50:]
        rolling20 = (sum(recent20) / len(recent20) * 100.0) if recent20 else None
        rolling50 = (sum(recent50) / len(recent50) * 100.0) if recent50 else None

        curve.append({
            "index": index,
            "timestamp": _iso(row.get("timestamp")),
            "wins": wins,
            "losses": losses,
            "net": wins - losses,
            "rolling20": rolling20,
            "rolling50": rolling50,
            "status": status,
        })

    return curve


def _get_recent_events(limit: int = 20, preferred_role: str | None = None) -> list[dict[str, Any]]:
    """Вернуть последние runtime events без смешивания потоков collector и bettor."""

    rows, selected_role = _select_runtime_event_rows(limit=limit, preferred_role=preferred_role)
    events = []
    for row in rows:
        payload = row.get("payload") or {}
        events.append({
            "timestamp": _iso(row.get("timestamp")),
            "event_type": row.get("event_type"),
            "session_balance": payload.get("session_balance"),
            "account_balance": payload.get("account_balance"),
            "last_set_status": payload.get("last_set_status"),
            "last_round_result": payload.get("last_round_result"),
            "runtime_role": row.get("runtime_role") or selected_role,
        })
    return events


def _build_overview() -> dict[str, Any]:
    """Собрать полный overview payload для dashboard API."""

    snapshot = _get_snapshot()
    preferred_role = snapshot.get("runtime_role")
    latest_win = _get_latest_win()
    recent_bets = _get_recent_bets()
    recent_rounds = _get_recent_rounds()
    balance_series = _get_balance_series(preferred_role=preferred_role)
    result_curve = _get_result_curve()
    recent_events = _get_recent_events(preferred_role=preferred_role)
    latest_bet = recent_bets[0] if recent_bets else None
    latest_round = recent_rounds[0] if recent_rounds else None

    return {
        "snapshot": snapshot,
        "summary": _get_summary(snapshot),
        "latest_win": latest_win,
        "latest_bet": latest_bet,
        "latest_round": latest_round,
        "recent_bets": recent_bets,
        "recent_rounds": recent_rounds,
        "balance_series": balance_series,
        "result_curve": result_curve,
        "recent_events": recent_events,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Отрендерить основную HTML-страницу dashboard."""

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "title": "BuyBayBye Dashboard",
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Проверить доступность базы данных и вернуть простой health response."""

    _fetch_one("SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/api/overview")
def api_overview() -> dict[str, Any]:
    """Вернуть агрегированный overview payload для фронтенда dashboard."""

    return _build_overview()