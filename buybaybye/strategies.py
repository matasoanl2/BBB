"""Вспомогательные функции для загрузки стратегий, валидации и инициализации betting state."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def validate_strategy_coefficients(strategy_name: str, coefficients: list, base_bet: float) -> tuple[bool, str]:
    """Проверить, что коэффициенты стратегии сохраняют кратность ставки десяти."""
    invalid_coefficients = []

    for index, coeff in enumerate(coefficients):
        bet_amount = base_bet * coeff
        if abs(bet_amount - round(bet_amount / 10) * 10) > 0.01:
            invalid_coefficients.append(
                f"  Step {index+1}: {coeff} × {base_bet} = {bet_amount} (не делится на 10)"
            )

    if invalid_coefficients:
        error_msg = f"[ERROR] Стратегия '{strategy_name}' имеет неправильные коэффициенты:\n"
        error_msg += "\n".join(invalid_coefficients)
        error_msg += "\nВсе коэффициенты должны быть целыми числами, чтобы при умножении на BASE_BET (кратную 10) давать кратное 10"
        return False, error_msg

    return True, ""


def load_strategies(strategies_dir: Path, base_bet: float) -> dict:
    """Загрузить и провалидировать все YAML-стратегии из папки strategies."""
    try:
        if not strategies_dir.exists():
            print(f"[ERROR] Папка стратегий не найдена: {strategies_dir}", flush=True)
            sys.exit(1)

        strategies = {}
        yaml_files = sorted(strategies_dir.glob("*.yaml"))

        if not yaml_files:
            print(f"[ERROR] Не найдено файлов стратегий в {strategies_dir}", flush=True)
            sys.exit(1)

        for yaml_file in yaml_files:
            try:
                strategy_key = yaml_file.stem
                with open(yaml_file, "r", encoding="utf-8") as handle:
                    strategy_data = yaml.safe_load(handle)

                coefficients = strategy_data.get("coefficients", [1])
                is_valid, error_msg = validate_strategy_coefficients(strategy_key, coefficients, base_bet)
                if not is_valid:
                    print(error_msg, flush=True)
                    print(f"[WARNING] Пропуск стратегии {strategy_key}", flush=True)
                    continue

                strategies[strategy_key] = {
                    "name": strategy_data.get("name", strategy_key),
                    "description": strategy_data.get("description", ""),
                    "coefficients": coefficients,
                    "payout_coefficient": strategy_data.get("payout_coefficient", 5.7),
                    "reset_condition": strategy_data.get("reset_condition", "win"),
                }
                print(f"[LOAD] Загружена стратегия: {strategy_key}", flush=True)
            except Exception as exc:
                print(f"[WARNING] Ошибка загрузки {yaml_file}: {exc}", flush=True)
                continue

        if not strategies:
            print("[ERROR] Не удалось загрузить ни одну стратегию", flush=True)
            sys.exit(1)

        return strategies
    except Exception as exc:
        print(f"[ERROR] Ошибка при загрузке стратегий: {exc}", flush=True)
        sys.exit(1)


def init_betting_state(strategy: dict, bet_mode_outcome: str, bet_mode_specifier: str) -> dict:
    """Инициализировать betting state для выбранной стратегии и цели ставки."""
    return {
        "current_step": 0,
        "consecutive_losses": 0,
        "session_balance": 0.0,
        "account_balance": None,
        "account_balance_type": None,
        "account_balance_updated_at": None,
        "last_accounting_ws_message_at": None,
        "last_accounting_ws_opened_at": None,
        "last_accounting_ws_closed_at": None,
        "accounting_ws_connected": False,
        "last_accounting_rejection_reason": None,
        "last_accounting_recovery_at": None,
        "accounting_recovery_attempts": 0,
        "pending_expected_bet_drop": 0.0,
        "external_deposits_total": 0.0,
        "external_withdrawals_total": 0.0,
        "last_bet_amount": 0.0,
        "last_set_amount": 0.0,
        "last_set_status": None,
        "last_set_error": None,
        "total_bet_amount": 0.0,
        "total_profit": 0.0,
        "total_bets_placed": 0,
        "last_round_result": None,
        "last_round_game_id": None,
        "last_round_status": None,
        "last_round_timestamp": None,
        "last_round_player_name": None,
        "last_round_position": None,
        "combo_stats": {
            "red_1": 0, "red_2": 0, "red_3": 0, "red_4": 0, "red_5": 0, "red_6": 0,
            "yellow_1": 0, "yellow_2": 0, "yellow_3": 0, "yellow_4": 0, "yellow_5": 0, "yellow_6": 0,
        },
        "double_stats": {"doubles": 0, "no_doubles": 0},
        "reported_20_rounds": [],
        "recent_bets": [],
        "dynamic_outcome": bet_mode_outcome,
        "dynamic_specifier": bet_mode_specifier,
        "strategy": strategy,
    }