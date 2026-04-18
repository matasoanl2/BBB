"""Вспомогательные функции для загрузки стратегий, валидации и инициализации betting state."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from buybaybye.core.runtime_state import build_runtime_betting_state


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
    return build_runtime_betting_state(
        strategy=strategy,
        bet_mode_outcome=bet_mode_outcome,
        bet_mode_specifier=bet_mode_specifier,
    )