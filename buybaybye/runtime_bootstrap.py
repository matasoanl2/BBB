from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def print_strategy_startup_info(
    *,
    current_strategy: dict,
    strategy_name: str,
    base_bet: float,
    dynamic_bet_mode: bool,
    dynamic_window_size: int,
    dynamic_recalc_interval: int,
    dynamic_use_average_value_selection: bool,
    dynamic_include_double_selection: bool,
    dynamic_filter_by_player: bool,
    dynamic_filter_by_side: bool,
    bet_mode_outcome: str,
    bet_mode_specifier: str,
    format_outcome_pretty_func,
) -> None:
    print(f"[STRATEGY] Загружена стратегия: {current_strategy['name']}", flush=True)
    print(f"[STRATEGY] Описание: {current_strategy['description']}", flush=True)
    print(f"[STRATEGY] Шагов: {len(current_strategy['coefficients'])}, базовая ставка: {base_bet}р", flush=True)
    print("[STRATEGY] Примеры ставок (BASE_BET × коэффициент):", flush=True)
    for index in range(min(5, len(current_strategy["coefficients"]))):
        coeff = current_strategy["coefficients"][index]
        bet_amount = base_bet * coeff
        print(f"  Step {index+1}: {base_bet}р × {coeff} = {bet_amount}р ✓", flush=True)

    if dynamic_bet_mode:
        print("\n[DYNAMIC] 🔄 ДИНАМИЧЕСКИЙ РЕЖИМ ВКЛЮЧЕН", flush=True)
        print(f"[DYNAMIC] Окно анализа: {dynamic_window_size} ставок", flush=True)
        print(f"[DYNAMIC] Пересчет: каждые {dynamic_recalc_interval} ставок", flush=True)
        print(f"[DYNAMIC] Выбор по среднему значению: {'ON' if dynamic_use_average_value_selection else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Учитывать double: {'ON' if dynamic_include_double_selection else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Фильтр по игроку: {'ON' if dynamic_filter_by_player else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Фильтр по стороне: {'ON' if dynamic_filter_by_side else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Начальная ставка: {format_outcome_pretty_func(bet_mode_outcome, bet_mode_specifier)}", flush=True)


def get_browser_launch_args() -> list[str]:
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--no-first-run",
        "--no-service-autorun",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-translate",
        "--mute-audio",
        "--disable-notifications",
        "--disable-logging",
        "--metrics-recording-only",
        "--disable-hang-monitor",
        "--password-store=basic",
        "--autoplay-policy=no-user-gesture-required",
    ]


def build_runtime_status_line(
    *,
    session_dir: Path,
    bet_mode_enabled: bool,
    current_strategy: dict | None,
    bet_mode_outcome: str,
    bet_mode_specifier: str,
    base_bet: float,
    bet_delay_min: float,
    bet_delay_max: float,
    accounting_balance_stale_seconds: float,
    accounting_recovery_reload_seconds: float,
) -> str:
    status_line = f"Браузер открыт. Профиль сессии: {session_dir}\n"
    if bet_mode_enabled and current_strategy:
        status_line += "🎲 РЕЖИМ СТАВОК ВКЛЮЧЕН\n"
        status_line += f"  - Стратегия: {current_strategy['name']}\n"
        status_line += f"  - Цель: {bet_mode_outcome} = {bet_mode_specifier}\n"
        status_line += f"  - Базовая ставка: {base_bet}р\n"
        status_line += f"  - Коэффициентов в прогрессии: {len(current_strategy['coefficients'])}\n"
        status_line += f"  - Задержка перед ставкой: {bet_delay_min:.1f}-{bet_delay_max:.1f}с\n"
    status_line += f"  - Accounting stale timeout: {accounting_balance_stale_seconds:.0f}с\n"
    status_line += f"  - Accounting recovery reload: {accounting_recovery_reload_seconds:.0f}с\n"
    status_line += "Закройте окно браузера или нажмите Enter здесь - сессия сохранится."
    return status_line


async def wait_for_exit_signal() -> None:
    if sys.stdin.isatty():
        try:
            await asyncio.to_thread(input)
        except EOFError:
            pass
        return
    await asyncio.Event().wait()