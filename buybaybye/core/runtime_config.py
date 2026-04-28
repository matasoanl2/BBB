"""Конфигурация рантайма на dataclass и вспомогательные функции загрузки env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class BetTarget:
    outcome: str
    specifier: str = ""

    @property
    def token(self) -> str:
        if self.outcome == "double":
            return "D"
        prefix = "R" if self.outcome == "red" else "Y"
        return f"{prefix}{self.specifier}"

def _parse_bet_target_token(raw_token: str) -> BetTarget:
    token = raw_token.strip().upper()
    if token == "D":
        return BetTarget(outcome="double", specifier="")

    if len(token) != 2 or token[0] not in {"R", "Y"} or token[1] not in {"1", "2", "3", "4", "5", "6"}:
        raise ValueError(
            f"[ERROR] BET_TARGETS содержит недопустимую цель: {raw_token}. Допустимы только R1-R6, Y1-Y6 или D."
        )

    return BetTarget(
        outcome="red" if token[0] == "R" else "yellow",
        specifier=token[1],
    )


def _parse_bet_targets(raw_value: str | None) -> tuple[tuple[BetTarget, ...], str | None]:
    if raw_value is None:
        return tuple(), None

    stripped_value = raw_value.strip()
    if not stripped_value:
        return tuple(), "[ERROR] BET_TARGETS пустой. Используйте формат R1,R2,Y3,D."

    parsed_targets: list[BetTarget] = []
    seen_tokens: set[str] = set()
    for part in raw_value.split(","):
        if not part.strip():
            return tuple(), (
                f"[ERROR] BET_TARGETS='{raw_value}' содержит пустую цель между запятыми. "
                "Используйте формат R1,R2,Y3,D без пустых элементов."
            )

        try:
            target = _parse_bet_target_token(part)
        except ValueError as exc:
            return tuple(), str(exc)

        if target.token in seen_tokens:
            return tuple(), f"[ERROR] BET_TARGETS='{raw_value}' содержит повторяющуюся цель: {target.token}."

        seen_tokens.add(target.token)
        parsed_targets.append(target)

    return tuple(parsed_targets), None


@dataclass(slots=True)
class BrowserConfig:
    session_dir: Path
    strategies_dir: Path
    target_ws_url: str
    accounting_ws_url: str
    bet_api_url: str
    headless: bool


@dataclass(frozen=True, slots=True)
class RuntimeRoleConfig:
    name: str
    uses_persistent_browser_profile: bool
    can_place_bets: bool
    writes_round_results: bool


@dataclass(slots=True)
class DatabaseConfig:
    user: str
    password: str
    host: str
    port: str
    name: str


@dataclass(slots=True)
class BettingConfig:
    requested_enabled: bool
    enabled: bool
    configured_targets: tuple[BetTarget, ...]
    configured_targets_raw: str
    configured_targets_error: str | None
    default_outcome: str
    default_specifier: str
    base_bet: float
    stop_at_balance: float
    stop_at_balance_resume_check_seconds: float
    strategy_name: str
    bet_delay_min: float
    bet_delay_max: float
    debug_enabled: bool


@dataclass(slots=True)
class DynamicBettingConfig:
    enabled: bool
    window_size: int
    recalc_interval: int
    # Показывать ли вывод анализа, если выбранная цель ставки не изменилась.
    unchanged_analysis_output_enabled: bool
    use_average_value_selection: bool
    include_double_selection: bool
    filter_by_player: bool
    filter_by_side: bool
    random_fallback_enabled: bool
    random_fallback_loss_streak: int
    multi_target_enabled: bool = False
    preserve_color_ratio: bool = False


@dataclass(slots=True)
class AccountingConfig:
    balance_stale_seconds: float
    initial_balance_timeout_seconds: float
    recovery_reload_seconds: float
    recovery_cooldown_seconds: float
    idle_reconnect_seconds: float
    # Poll interval for accounting_ws health monitoring.
    monitor_poll_seconds: float
    debug_rejected_messages: bool


@dataclass(slots=True)
class TelegramConfig:
    notifications_enabled: bool
    bot_token: str
    chat_id: str
    request_timeout_seconds: float
    notification_cooldown_seconds: float
    notify_deposits: bool
    notify_withdrawals: bool
    notify_accounting_issues: bool
    notify_bet_errors: bool
    notify_auth_issues: bool


@dataclass(slots=True)
class LoggingConfig:
    ws_log_enabled: bool
    dice_stats_report_enabled: bool
    terminal_plain_logs: bool
    terminal_json_logs: bool


@dataclass(slots=True)
class ColorConfig:
    enabled: bool
    green: str
    red: str
    yellow: str
    cyan: str
    blue: str
    magenta: str
    reset: str


@dataclass(slots=True)
class RuntimeConfig:
    """Верхнеуровневая неизменяемая конфигурация рантайма, собранная из env."""

    role: RuntimeRoleConfig
    browser: BrowserConfig
    database: DatabaseConfig
    betting: BettingConfig
    dynamic_betting: DynamicBettingConfig
    accounting: AccountingConfig
    telegram: TelegramConfig
    logging: LoggingConfig
    colors: ColorConfig


def validate_runtime_config(config: RuntimeConfig) -> None:
    """Fail fast on invalid env-derived configuration."""

    if config.betting.base_bet <= 0:
        raise ValueError("[ERROR] BASE_BET должен быть положительным числом.")
    if config.betting.stop_at_balance < 0:
        raise ValueError("[ERROR] STOP_AT_BALANCE не может быть отрицательным.")
    if config.betting.stop_at_balance_resume_check_seconds <= 0:
        raise ValueError("[ERROR] STOP_AT_BALANCE_RESUME_CHECK_SECONDS должен быть больше 0.")
    if config.betting.bet_delay_min < 0 or config.betting.bet_delay_max < 0:
        raise ValueError("[ERROR] BET_DELAY_MIN и BET_DELAY_MAX не могут быть отрицательными.")
    if config.betting.bet_delay_min > config.betting.bet_delay_max:
        raise ValueError("[ERROR] BET_DELAY_MIN не может быть больше BET_DELAY_MAX.")
    if config.dynamic_betting.window_size <= 0:
        raise ValueError("[ERROR] DYNAMIC_WINDOW_SIZE должен быть больше 0.")
    if config.dynamic_betting.recalc_interval <= 0:
        raise ValueError("[ERROR] DYNAMIC_RECALC_INTERVAL должен быть больше 0.")
    if config.dynamic_betting.random_fallback_loss_streak <= 0:
        raise ValueError("[ERROR] DYNAMIC_RANDOM_FALLBACK_LOSS_STREAK должен быть больше 0.")
    if config.accounting.balance_stale_seconds <= 0:
        raise ValueError("[ERROR] ACCOUNTING_BALANCE_STALE_SECONDS должен быть больше 0.")
    if config.accounting.initial_balance_timeout_seconds <= 0:
        raise ValueError("[ERROR] ACCOUNTING_INITIAL_BALANCE_TIMEOUT_SECONDS должен быть больше 0.")
    if config.accounting.recovery_reload_seconds <= 0:
        raise ValueError("[ERROR] ACCOUNTING_RECOVERY_RELOAD_SECONDS должен быть больше 0.")
    if config.accounting.recovery_cooldown_seconds < 0:
        raise ValueError("[ERROR] ACCOUNTING_RECOVERY_COOLDOWN_SECONDS не может быть отрицательным.")
    if config.accounting.idle_reconnect_seconds <= 0:
        raise ValueError("[ERROR] ACCOUNTING_IDLE_RECONNECT_SECONDS должен быть больше 0.")
    if config.accounting.monitor_poll_seconds <= 0:
        raise ValueError("[ERROR] ACCOUNTING_MONITOR_POLL_SECONDS должен быть больше 0.")
    if config.telegram.request_timeout_seconds <= 0:
        raise ValueError("[ERROR] TELEGRAM_REQUEST_TIMEOUT_SECONDS должен быть больше 0.")
    if config.telegram.notification_cooldown_seconds < 0:
        raise ValueError("[ERROR] TELEGRAM_NOTIFICATION_COOLDOWN_SECONDS не может быть отрицательным.")


def _load_runtime_role(raw_value: str | None, *, requested_betting_enabled: bool) -> RuntimeRoleConfig:
    normalized_value = (raw_value or ("bettor" if requested_betting_enabled else "collector")).strip().lower()

    if normalized_value == "collector":
        return RuntimeRoleConfig(
            name="collector",
            uses_persistent_browser_profile=False,
            can_place_bets=False,
            writes_round_results=True,
        )

    if normalized_value == "bettor":
        return RuntimeRoleConfig(
            name="bettor",
            uses_persistent_browser_profile=True,
            can_place_bets=True,
            writes_round_results=False,
        )

    raise ValueError("[ERROR] RUNTIME_ROLE должен быть collector или bettor.")


def load_runtime_config(app_dir: Path) -> RuntimeConfig:
    """Загрузить всю конфигурацию рантайма из переменных окружения."""

    color_enabled = _env_bool("COLOR_ENABLED", "true")
    requested_betting_enabled = _env_bool("BET_MODE")
    runtime_role = _load_runtime_role(
        os.getenv("RUNTIME_ROLE"),
        requested_betting_enabled=requested_betting_enabled,
    )
    raw_bet_targets = (os.getenv("BET_TARGETS") or "").strip()
    configured_targets, configured_targets_error = _parse_bet_targets(raw_bet_targets or None)
    if not configured_targets:
        configured_targets_error = configured_targets_error or "[ERROR] BET_TARGETS не задан. Используйте формат R1,R2,Y3,D."
        configured_targets = (BetTarget(outcome="red", specifier="1"),)

    default_target = configured_targets[0]
    first_outcome = default_target.outcome
    first_specifier = default_target.specifier or "5"
    colors = ColorConfig(
        enabled=color_enabled,
        green="\033[92m" if color_enabled else "",
        red="\033[91m" if color_enabled else "",
        yellow="\033[93m" if color_enabled else "",
        cyan="\033[96m" if color_enabled else "",
        blue="\033[94m" if color_enabled else "",
        magenta="\033[95m" if color_enabled else "",
        reset="\033[0m" if color_enabled else "",
    )

    config = RuntimeConfig(
        role=runtime_role,
        browser=BrowserConfig(
            session_dir=app_dir / "profile",
            strategies_dir=app_dir / "strategies",
            target_ws_url="wss://ws.betboom.ru:444/api/nards_studio_ws/v1",
            accounting_ws_url="wss://ws.betboom.ru:444/api/accounting_ws/v1",
            bet_api_url="https://game.betboom.ru/api/nards_studio_client/v1/bet",
            headless=_env_bool("HEADLESS"),
        ),
        database=DatabaseConfig(
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            name=os.getenv("DB_NAME", "buybaybye"),
        ),
        betting=BettingConfig(
            requested_enabled=requested_betting_enabled,
            enabled=requested_betting_enabled and runtime_role.can_place_bets,
            configured_targets=configured_targets,
            configured_targets_raw=raw_bet_targets,
            configured_targets_error=configured_targets_error,
            default_outcome=first_outcome,
            default_specifier=first_specifier,
            base_bet=float(os.getenv("BASE_BET", "10")),
            stop_at_balance=float(os.getenv("STOP_AT_BALANCE", "0")),
            stop_at_balance_resume_check_seconds=float(os.getenv("STOP_AT_BALANCE_RESUME_CHECK_SECONDS", "300")),
            strategy_name=os.getenv("STRATEGY", "balanced"),
            bet_delay_min=float(os.getenv("BET_DELAY_MIN", "0.8")),
            bet_delay_max=float(os.getenv("BET_DELAY_MAX", "1.5")),
            debug_enabled=_env_bool("BET_DEBUG_ENABLED"),
        ),
        dynamic_betting=DynamicBettingConfig(
            enabled=_env_bool("DYNAMIC_BET_MODE"),
            window_size=int(os.getenv("DYNAMIC_WINDOW_SIZE", "40")),
            recalc_interval=int(os.getenv("DYNAMIC_RECALC_INTERVAL", "5")),
            unchanged_analysis_output_enabled=_env_bool("DYNAMIC_UNCHANGED_ANALYSIS_OUTPUT_ENABLED", "true"),
            use_average_value_selection=_env_bool("DYNAMIC_USE_AVERAGE_VALUE_SELECTION", "true"),
            include_double_selection=_env_bool("DYNAMIC_INCLUDE_DOUBLE_SELECTION", "true"),
            filter_by_player=_env_bool("DYNAMIC_FILTER_BY_PLAYER"),
            filter_by_side=_env_bool("DYNAMIC_FILTER_BY_SIDE"),
            random_fallback_enabled=_env_bool("DYNAMIC_RANDOM_FALLBACK_ENABLED", "false"),
            random_fallback_loss_streak=max(1, int(os.getenv("DYNAMIC_RANDOM_FALLBACK_LOSS_STREAK", "15"))),
            multi_target_enabled=_env_bool("DYNAMIC_MULTI_TARGET_ENABLED"),
            preserve_color_ratio=_env_bool("DYNAMIC_PRESERVE_COLOR_RATIO"),
        ),
        accounting=AccountingConfig(
            balance_stale_seconds=float(os.getenv("ACCOUNTING_BALANCE_STALE_SECONDS", "15")),
            initial_balance_timeout_seconds=float(os.getenv("ACCOUNTING_INITIAL_BALANCE_TIMEOUT_SECONDS", "20")),
            recovery_reload_seconds=float(os.getenv("ACCOUNTING_RECOVERY_RELOAD_SECONDS", "25")),
            recovery_cooldown_seconds=float(os.getenv("ACCOUNTING_RECOVERY_COOLDOWN_SECONDS", "30")),
            idle_reconnect_seconds=float(os.getenv("ACCOUNTING_IDLE_RECONNECT_SECONDS", "300")),
            monitor_poll_seconds=float(os.getenv("ACCOUNTING_MONITOR_POLL_SECONDS", "3")),
            debug_rejected_messages=_env_bool("ACCOUNTING_DEBUG_REJECTED_MESSAGES"),
        ),
        telegram=TelegramConfig(
            notifications_enabled=_env_bool("TELEGRAM_NOTIFICATIONS_ENABLED"),
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            request_timeout_seconds=float(os.getenv("TELEGRAM_REQUEST_TIMEOUT_SECONDS", "5")),
            notification_cooldown_seconds=float(os.getenv("TELEGRAM_NOTIFICATION_COOLDOWN_SECONDS", "60")),
            notify_deposits=_env_bool("TELEGRAM_NOTIFY_DEPOSITS", "true"),
            notify_withdrawals=_env_bool("TELEGRAM_NOTIFY_WITHDRAWALS", "true"),
            notify_accounting_issues=_env_bool("TELEGRAM_NOTIFY_ACCOUNTING_ISSUES", "true"),
            notify_bet_errors=_env_bool("TELEGRAM_NOTIFY_BET_ERRORS", "true"),
            notify_auth_issues=_env_bool("TELEGRAM_NOTIFY_AUTH_ISSUES", "true"),
        ),
        logging=LoggingConfig(
            ws_log_enabled=_env_bool("WS_LOG_ENABLED"),
            dice_stats_report_enabled=_env_bool("DICE_STATS_REPORT_ENABLED", "true"),
            terminal_plain_logs=_env_bool("TERMINAL_PLAIN_LOGS"),
            terminal_json_logs=_env_bool("TERMINAL_JSON_LOGS"),
        ),
        colors=colors,
    )
    validate_runtime_config(config)
    return config