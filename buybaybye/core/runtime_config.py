"""Конфигурация рантайма на dataclass и вспомогательные функции загрузки env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class BrowserConfig:
    session_dir: Path
    strategies_dir: Path
    target_ws_url: str
    accounting_ws_url: str
    bet_api_url: str
    headless: bool


@dataclass(slots=True)
class DatabaseConfig:
    user: str
    password: str
    host: str
    port: str
    name: str


@dataclass(slots=True)
class BettingConfig:
    enabled: bool
    default_outcome: str
    default_specifier: str
    base_bet: float
    strategy_name: str
    bet_delay_min: float
    bet_delay_max: float
    debug_enabled: bool


@dataclass(slots=True)
class DynamicBettingConfig:
    enabled: bool
    window_size: int
    recalc_interval: int
    use_average_value_selection: bool
    include_double_selection: bool
    filter_by_player: bool
    filter_by_side: bool
    random_fallback_enabled: bool
    random_fallback_loss_streak: int


@dataclass(slots=True)
class AccountingConfig:
    balance_stale_seconds: float
    recovery_reload_seconds: float
    recovery_cooldown_seconds: float
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

    browser: BrowserConfig
    database: DatabaseConfig
    betting: BettingConfig
    dynamic_betting: DynamicBettingConfig
    accounting: AccountingConfig
    telegram: TelegramConfig
    logging: LoggingConfig
    colors: ColorConfig


def load_runtime_config(app_dir: Path) -> RuntimeConfig:
    """Загрузить всю конфигурацию рантайма из переменных окружения."""

    color_enabled = _env_bool("COLOR_ENABLED", "true")
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

    return RuntimeConfig(
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
            enabled=_env_bool("BET_MODE"),
            default_outcome=os.getenv("BET_OUTCOME", "red"),
            default_specifier=os.getenv("BET_SPECIFIER", "5"),
            base_bet=float(os.getenv("BASE_BET", "10")),
            strategy_name=os.getenv("STRATEGY", "balanced"),
            bet_delay_min=float(os.getenv("BET_DELAY_MIN", "0.8")),
            bet_delay_max=float(os.getenv("BET_DELAY_MAX", "1.5")),
            debug_enabled=_env_bool("BET_DEBUG_ENABLED"),
        ),
        dynamic_betting=DynamicBettingConfig(
            enabled=_env_bool("DYNAMIC_BET_MODE"),
            window_size=int(os.getenv("DYNAMIC_WINDOW_SIZE", "40")),
            recalc_interval=int(os.getenv("DYNAMIC_RECALC_INTERVAL", "5")),
            use_average_value_selection=_env_bool("DYNAMIC_USE_AVERAGE_VALUE_SELECTION", "true"),
            include_double_selection=_env_bool("DYNAMIC_INCLUDE_DOUBLE_SELECTION", "true"),
            filter_by_player=_env_bool("DYNAMIC_FILTER_BY_PLAYER"),
            filter_by_side=_env_bool("DYNAMIC_FILTER_BY_SIDE"),
            random_fallback_enabled=_env_bool("DYNAMIC_RANDOM_FALLBACK_ENABLED", "true"),
            random_fallback_loss_streak=max(1, int(os.getenv("DYNAMIC_RANDOM_FALLBACK_LOSS_STREAK", "15"))),
        ),
        accounting=AccountingConfig(
            balance_stale_seconds=float(os.getenv("ACCOUNTING_BALANCE_STALE_SECONDS", "15")),
            recovery_reload_seconds=float(os.getenv("ACCOUNTING_RECOVERY_RELOAD_SECONDS", "25")),
            recovery_cooldown_seconds=float(os.getenv("ACCOUNTING_RECOVERY_COOLDOWN_SECONDS", "30")),
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
        ),
        colors=colors,
    )