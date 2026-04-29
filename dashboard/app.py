"""FastAPI-дашборд для текущего состояния рантайма и недавней истории ставок."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

from buybaybye.core.runtime_config import DatabaseConfig
from buybaybye.modules.db import connect_postgres_with_retry
from buybaybye.modules.db import ensure_runtime_schema


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
db_pool: SimpleConnectionPool | None = None


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    """Parse a boolean env flag with a safe false-by-default fallback."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_dashboard_template_name() -> str:
    """Choose the dashboard HTML template based on the dashboard version flag."""

    if _env_flag_enabled("DASHBOARD_V2_ENABLED", default=False):
        return "index_v2.html"
    return "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prepare dashboard schema on startup."""

    _ensure_dashboard_schema()
    _init_db_pool(use_retry=True)
    try:
        yield
    finally:
        _close_db_pool()


app = FastAPI(title="BuyBayBye Dashboard", lifespan=lifespan)


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
    "low_balance_pause_reason": None,
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
    """Получить подключение из dashboard connection pool.

    При ленивой реинициализации (после сброса пула) использует быстрый
    connect без retry — OperationalError при недоступной БД.
    """

    global db_pool
    if db_pool is None:
        _init_db_pool(use_retry=False)
    if db_pool is None:
        raise RuntimeError("Dashboard DB pool is not initialized")
    return db_pool.getconn()


def _release_db_connection(conn, *, broken: bool = False) -> None:
    """Вернуть подключение обратно в dashboard connection pool.

    Если соединение сломано (broken=True или conn.closed != 0), оно
    удаляется из пула и пул сбрасывается для переинициализации.
    """

    if conn is None:
        return

    global db_pool
    if db_pool is None:
        try:
            conn.close()
        except Exception:
            pass
        return

    is_broken = broken or bool(conn.closed)
    if is_broken:
        try:
            db_pool.putconn(conn, close=True)
        except Exception:
            pass
        # Сбросить пул — все соединения потенциально протухли
        try:
            db_pool.closeall()
        except Exception:
            pass
        db_pool = None
    else:
        db_pool.putconn(conn)


def _init_db_pool(*, use_retry: bool = False) -> None:
    """Инициализировать dashboard connection pool.

    use_retry=True — блокирующий retry (для startup lifespan).
    use_retry=False — быстрая попытка; при недоступной БД бросает OperationalError.
    """

    global db_pool
    if db_pool is not None:
        return

    connect_kwargs = {
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "database": os.getenv("DB_NAME", "buybaybye"),
        "cursor_factory": RealDictCursor,
    }

    if use_retry:
        probe_conn = connect_postgres_with_retry(fatal_context="dashboard startup", **connect_kwargs)
    else:
        probe_conn = psycopg2.connect(**connect_kwargs)
    probe_conn.close()

    min_conn = max(1, int(os.getenv("DASHBOARD_DB_POOL_MIN_CONN", "1")))
    max_conn = max(min_conn, int(os.getenv("DASHBOARD_DB_POOL_MAX_CONN", "10")))
    db_pool = SimpleConnectionPool(minconn=min_conn, maxconn=max_conn, **connect_kwargs)


def _close_db_pool() -> None:
    """Закрыть все физические подключения dashboard connection pool."""

    global db_pool
    if db_pool is None:
        return

    db_pool.closeall()
    db_pool = None


def _ensure_dashboard_schema() -> None:
    """Гарантировать наличие таблиц, которые читает и заполняет dashboard."""

    ensure_runtime_schema(
        database_config=DatabaseConfig(
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            name=os.getenv("DB_NAME", "buybaybye"),
        )
    )


def _fetch_one(query: str, params: tuple[Any, ...] = (), conn=None) -> dict[str, Any] | None:
    """Выполнить SQL-запрос и вернуть одну строку в виде словаря."""

    own_connection = conn is None
    conn = conn or _get_db_connection()
    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        row = cursor.fetchone()
    finally:
        cursor.close()
        if own_connection:
            _release_db_connection(conn)
    return dict(row) if row else None


def _fetch_all(query: str, params: tuple[Any, ...] = (), conn=None) -> list[dict[str, Any]]:
    """Выполнить SQL-запрос и вернуть все строки как список словарей."""

    own_connection = conn is None
    conn = conn or _get_db_connection()
    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        if own_connection:
            _release_db_connection(conn)
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


def _derive_safe_result_dice_values(result_dice_color: Any, result_dice_value: Any) -> tuple[int | None, int | None]:
    """Безопасно восстановить значения кубиков из сохраненного результата ставки."""

    if not isinstance(result_dice_value, int):
        return None, None

    if result_dice_color == "double":
        return result_dice_value, result_dice_value
    if result_dice_color == "red":
        return result_dice_value, None
    if result_dice_color == "yellow":
        return None, result_dice_value
    return None, None


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


def _select_runtime_event_rows(limit: int, preferred_role: str | None = None, conn=None) -> tuple[list[dict[str, Any]], str | None]:
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
        conn=conn,
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


def _select_balance_session_event_rows(preferred_role: str | None = None, conn=None) -> tuple[list[dict[str, Any]], str | None]:
    """Выбрать runtime events за всю текущую сессию (от последнего startup)."""

    selected_role = preferred_role
    if selected_role is None:
        latest_role_row = _fetch_one(
            """
            SELECT payload
            FROM runtime_events
            ORDER BY id DESC
            LIMIT 1
            """,
            conn=conn,
        )
        selected_role = _extract_runtime_role((latest_role_row or {}).get("payload") or {})

    startup_query = """
        SELECT id
        FROM runtime_events
        WHERE event_type = 'startup'
    """
    startup_params: tuple[Any, ...] = ()
    if selected_role:
        startup_query += " AND payload->>'runtime_role' = %s"
        startup_params = (selected_role,)
    startup_query += " ORDER BY id DESC LIMIT 1"

    startup_row = _fetch_one(startup_query, startup_params, conn=conn)
    startup_id = startup_row.get("id") if startup_row else None

    rows_query = """
        SELECT id, timestamp, event_type, payload
        FROM runtime_events
        WHERE 1 = 1
    """
    rows_params: list[Any] = []

    if startup_id is not None:
        rows_query += " AND id >= %s"
        rows_params.append(startup_id)
    if selected_role:
        rows_query += " AND payload->>'runtime_role' = %s"
        rows_params.append(selected_role)

    rows_query += " ORDER BY id ASC"
    rows = _fetch_all(rows_query, tuple(rows_params), conn=conn)

    annotated_rows = []
    for row in rows:
        payload = row.get("payload") or {}
        annotated = dict(row)
        annotated["payload"] = payload
        annotated["runtime_role"] = _extract_runtime_role(payload)
        annotated_rows.append(annotated)

    return annotated_rows, selected_role


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


def _get_snapshot(conn=None) -> dict[str, Any]:
    """Вернуть наиболее подходящий runtime snapshot: bettor, затем collector, затем legacy live."""

    rows = _fetch_all(
        """
        SELECT snapshot_key, updated_at, payload
        FROM runtime_snapshot
        ORDER BY updated_at DESC NULLS LAST, snapshot_key ASC
        """,
        conn=conn,
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


def _get_summary(snapshot: dict[str, Any], conn=None) -> dict[str, Any]:
    """Собрать сводные метрики dashboard из snapshot и агрегатов bet_history."""

    bets = _fetch_one(
        """
        SELECT
            COUNT(*)::int AS total_bets,
            COUNT(*) FILTER (WHERE status = 'win')::int AS wins,
            COUNT(*) FILTER (WHERE status = 'loss')::int AS losses,
            COUNT(*) FILTER (WHERE status LIKE 'skipped%')::int AS skipped
        FROM bet_history
        """,
        conn=conn,
    ) or {"total_bets": 0, "wins": 0, "losses": 0, "skipped": 0}

    rounds = _fetch_one("SELECT COUNT(*)::int AS total_rounds FROM game_results", conn=conn) or {"total_rounds": 0}
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
        "freshness_state": snapshot.get("freshness_state") or ("stale" if snapshot.get("account_balance_is_stale") else "fresh"),
        "reconciliation_phase": snapshot.get("reconciliation_phase") or "idle",
    }


def _get_recent_bets(limit: int = 20, conn=None) -> list[dict[str, Any]]:
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
        conn=conn,
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


def _get_latest_win(conn=None) -> dict[str, Any] | None:
    """Вернуть самую свежую выигранную ставку для клиентской win-анимации."""

    row = _fetch_one(
        """
        SELECT id, timestamp, outcome, specifier, amount, strategy,
               bet_step, status, result_dice_color, result_dice_value
        FROM bet_history
         WHERE status = 'win'
        ORDER BY id DESC
        LIMIT 1
        """,
        conn=conn,
    )

    if not row:
        return None

    red_value, yellow_value = _derive_safe_result_dice_values(
        row.get("result_dice_color"),
        row.get("result_dice_value"),
    )

    return {
        "id": row.get("id"),
        "timestamp": _iso(row.get("timestamp")),
        "target": _format_target(row.get("outcome"), row.get("specifier")),
        "amount": row.get("amount"),
        "strategy": row.get("strategy"),
        "step": (row.get("bet_step") + 1) if isinstance(row.get("bet_step"), int) else None,
        "status": row.get("status"),
        "result": _format_target(row.get("result_dice_color"), row.get("result_dice_value")),
        "red_value": red_value,
        "yellow_value": yellow_value,
    }


def _get_recent_rounds(limit: int = 20, conn=None) -> list[dict[str, Any]]:
    """Загрузить последние игровые раунды и преобразовать их в UI-формат."""

    rows = _fetch_all(
        """
        SELECT id, timestamp, player_name, dice_results
        FROM game_results
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
        conn=conn,
    )
    return [_parse_round(row) for row in rows]


def _get_balance_series(preferred_role: str | None = None, conn=None) -> list[dict[str, Any]]:
    """Построить временной ряд balance за всю текущую runtime-сессию."""

    rows, selected_role = _select_balance_session_event_rows(preferred_role=preferred_role, conn=conn)
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


def _get_result_curve(limit: int = 160, conn=None) -> list[dict[str, Any]]:
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
        conn=conn,
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


def _get_recent_events(limit: int = 20, preferred_role: str | None = None, conn=None) -> list[dict[str, Any]]:
    """Вернуть последние runtime events без смешивания потоков collector и bettor."""

    rows, selected_role = _select_runtime_event_rows(limit=limit, preferred_role=preferred_role, conn=conn)
    events = []
    for row in rows:
        payload = row.get("payload") or {}
        events.append({
            "timestamp": _iso(row.get("timestamp")),
            "event_type": row.get("event_type"),
            "session_balance": payload.get("session_balance"),
            "account_balance": payload.get("account_balance"),
            "last_set_status": payload.get("last_set_status"),
            "low_balance_pause_reason": payload.get("low_balance_pause_reason"),
            "last_round_result": payload.get("last_round_result"),
            "runtime_role": row.get("runtime_role") or selected_role,
        })
    return events


def _build_dashboard_payload() -> dict[str, Any]:
    """Собрать полный payload dashboard через одно подключение к БД."""

    conn = _get_db_connection()
    broken = False
    try:
        snapshot = _get_snapshot(conn=conn)
        preferred_role = snapshot.get("runtime_role")
        recent_bets = _get_recent_bets(conn=conn)
        recent_rounds = _get_recent_rounds(conn=conn)

        return {
            "snapshot": snapshot,
            "summary": _get_summary(snapshot, conn=conn),
            "latest_win": _get_latest_win(conn=conn),
            "recent_bets": recent_bets,
            "recent_rounds": recent_rounds,
            "recent_events": _get_recent_events(preferred_role=preferred_role, conn=conn),
            "latest_bet": recent_bets[0] if recent_bets else None,
            "latest_round": recent_rounds[0] if recent_rounds else None,
            "balance_series": _get_balance_series(preferred_role=preferred_role, conn=conn),
            "result_curve": _get_result_curve(conn=conn),
        }
    except psycopg2.OperationalError:
        broken = True
        raise
    finally:
        _release_db_connection(conn, broken=broken)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Отрендерить основную HTML-страницу dashboard."""

    return templates.TemplateResponse(
        request,
        _get_dashboard_template_name(),
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


@app.get("/api/dashboard")
def api_dashboard() -> dict[str, Any]:
    """Return the full dashboard payload using a single DB connection."""

    try:
        return _build_dashboard_payload()
    except (psycopg2.OperationalError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="БД временно недоступна") from exc