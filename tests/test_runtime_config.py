from pathlib import Path

import pytest

from buybaybye.core.runtime_config import (
    AccountingConfig,
    BettingConfig,
    BrowserConfig,
    ColorConfig,
    DynamicBettingConfig,
    LoggingConfig,
    RuntimeConfig,
    RuntimeRoleConfig,
    TelegramConfig,
    load_runtime_config,
    validate_runtime_config,
)
from buybaybye.core.runtime_config import DatabaseConfig


def make_config() -> RuntimeConfig:
    return RuntimeConfig(
        role=RuntimeRoleConfig("bettor", True, True, False),
        browser=BrowserConfig(Path("profile"), Path("strategies"), "target", "accounting", "bet", False),
        database=DatabaseConfig("postgres", "postgres", "localhost", "5432", "buybaybye"),
        betting=BettingConfig(True, True, tuple(), "", None, "red", "5", 10.0, 0.0, "balanced", 0.8, 1.5, False),
        dynamic_betting=DynamicBettingConfig(True, 40, 5, True, True, True, False, False, True, 15),
        accounting=AccountingConfig(15.0, 25.0, 30.0, 300.0, 300.0, 3.0, False),
        telegram=TelegramConfig(False, "", "", 5.0, 60.0, True, True, True, True, True),
        logging=LoggingConfig(False, True, False, False),
        colors=ColorConfig(True, "", "", "", "", "", "", ""),
    )


def test_validate_runtime_config_accepts_valid_values() -> None:
    validate_runtime_config(make_config())


def test_validate_runtime_config_rejects_negative_delay() -> None:
    config = make_config()
    config.betting.bet_delay_min = -1.0
    with pytest.raises(ValueError):
        validate_runtime_config(config)


def test_validate_runtime_config_rejects_zero_recalc_interval() -> None:
    config = make_config()
    config.dynamic_betting.recalc_interval = 0
    with pytest.raises(ValueError):
        validate_runtime_config(config)


def test_load_runtime_config_random_fallback_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DYNAMIC_RANDOM_FALLBACK_ENABLED", raising=False)

    config = load_runtime_config(Path("."))

    assert config.dynamic_betting.random_fallback_enabled is False