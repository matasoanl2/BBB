from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "dashboard_templates"))

app = FastAPI(title="BuyBayBye Dashboard")


def _get_db_connection():
    return psycopg2.connect(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "buybaybye"),
        cursor_factory=RealDictCursor,
    )


def _ensure_dashboard_schema() -> None:
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
    _ensure_dashboard_schema()


def _fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
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
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _format_target(outcome: str | None, specifier: str | None) -> str:
    if not outcome:
        return "-"
    if outcome == "double":
        return "DOUBLE"
    if specifier:
        return f"{outcome.upper()} {specifier}"
    return outcome.upper()


def _parse_round(row: dict[str, Any]) -> dict[str, Any]:
    dice_results = row.get("dice_results") or {}
    dice = dice_results.get("dice", []) if isinstance(dice_results, dict) else []
    player = dice_results.get("player", {}) if isinstance(dice_results, dict) else {}
    position = player.get("position") if isinstance(player, dict) else None
    red_value = None
    yellow_value = None

    for die in dice:
        if not isinstance(die, dict):
            continue
        if die.get("color") == "red":
            red_value = die.get("value")
        if die.get("color") == "yellow":
            yellow_value = die.get("value")

    is_double = red_value is not None and red_value == yellow_value
    if red_value is None and yellow_value is None:
        display = "-"
    elif is_double:
        display = f"DOUBLE {red_value}"
    else:
        display = f"RED {red_value or '-'} / YELLOW {yellow_value or '-'}"

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
    row = _fetch_one(
        "SELECT updated_at, payload FROM runtime_snapshot WHERE snapshot_key = %s",
        ("live",),
    )
    if not row:
        return {
            "event_type": "boot",
            "updated_at": None,
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
            "external_withdrawals_total": 0.0,
            "current_outcome": None,
            "current_specifier": None,
            "last_round_result": None,
            "last_set_status": None,
            "last_set_error": None,
        }

    payload = row.get("payload") or {}
    payload["updated_at"] = _iso(row.get("updated_at"))
    return payload


def _get_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
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


def _get_recent_rounds(limit: int = 20) -> list[dict[str, Any]]:
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


def _get_balance_series(limit: int = 160) -> list[dict[str, Any]]:
    rows = _fetch_all(
        """
        SELECT timestamp, event_type,
               payload->>'session_balance' AS session_balance,
               payload->>'account_balance' AS account_balance
        FROM runtime_events
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows.reverse()
    result = []
    for row in rows:
        session_balance = row.get("session_balance")
        account_balance = row.get("account_balance")
        result.append({
            "timestamp": _iso(row.get("timestamp")),
            "event_type": row.get("event_type"),
            "session_balance": float(session_balance) if session_balance not in (None, "") else None,
            "account_balance": float(account_balance) if account_balance not in (None, "") else None,
        })
    return result


def _get_result_curve(limit: int = 160) -> list[dict[str, Any]]:
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


def _get_recent_events(limit: int = 20) -> list[dict[str, Any]]:
    rows = _fetch_all(
        """
        SELECT timestamp, event_type, payload
        FROM runtime_events
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )
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
        })
    return events


def _build_overview() -> dict[str, Any]:
    snapshot = _get_snapshot()
    recent_bets = _get_recent_bets()
    recent_rounds = _get_recent_rounds()
    balance_series = _get_balance_series()
    result_curve = _get_result_curve()
    recent_events = _get_recent_events()
    latest_bet = recent_bets[0] if recent_bets else None
    latest_round = recent_rounds[0] if recent_rounds else None

    return {
        "snapshot": snapshot,
        "summary": _get_summary(snapshot),
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
    _fetch_one("SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/api/overview")
def api_overview() -> dict[str, Any]:
    return _build_overview()