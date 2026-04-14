from __future__ import annotations

import asyncio
import sys

from buybaybye.runtime_context import RuntimeContext
from buybaybye.runtime_config import RuntimeConfig


def print_strategy_startup_info(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    format_outcome_pretty_func,
) -> None:
    current_strategy = runtime_context.current_strategy
    dynamic_config = runtime_config.dynamic_betting
    base_bet = runtime_config.betting.base_bet
    print(f"[STRATEGY] Загружена стратегия: {current_strategy['name']}", flush=True)
    print(f"[STRATEGY] Описание: {current_strategy['description']}", flush=True)
    print(f"[STRATEGY] Шагов: {len(current_strategy['coefficients'])}, базовая ставка: {base_bet}р", flush=True)
    print("[STRATEGY] Примеры ставок (BASE_BET × коэффициент):", flush=True)
    for index in range(min(5, len(current_strategy["coefficients"]))):
        coeff = current_strategy["coefficients"][index]
        bet_amount = base_bet * coeff
        print(f"  Step {index+1}: {base_bet}р × {coeff} = {bet_amount}р ✓", flush=True)

    if dynamic_config.enabled:
        print("\n[DYNAMIC] 🔄 ДИНАМИЧЕСКИЙ РЕЖИМ ВКЛЮЧЕН", flush=True)
        print(f"[DYNAMIC] Окно анализа: {dynamic_config.window_size} ставок", flush=True)
        print(f"[DYNAMIC] Пересчет: каждые {dynamic_config.recalc_interval} ставок", flush=True)
        print(f"[DYNAMIC] Выбор по среднему значению: {'ON' if dynamic_config.use_average_value_selection else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Учитывать double: {'ON' if dynamic_config.include_double_selection else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Фильтр по игроку: {'ON' if dynamic_config.filter_by_player else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Фильтр по стороне: {'ON' if dynamic_config.filter_by_side else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Начальная ставка: {format_outcome_pretty_func(runtime_context.bet_mode_outcome, runtime_context.bet_mode_specifier)}", flush=True)


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
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
) -> str:
    status_line = f"Браузер открыт. Профиль сессии: {runtime_config.browser.session_dir}\n"
    if runtime_config.betting.enabled and runtime_context.current_strategy:
        status_line += "🎲 РЕЖИМ СТАВОК ВКЛЮЧЕН\n"
        status_line += f"  - Стратегия: {runtime_context.current_strategy['name']}\n"
        status_line += f"  - Цель: {runtime_context.bet_mode_outcome} = {runtime_context.bet_mode_specifier}\n"
        status_line += f"  - Базовая ставка: {runtime_config.betting.base_bet}р\n"
        status_line += f"  - Коэффициентов в прогрессии: {len(runtime_context.current_strategy['coefficients'])}\n"
        status_line += f"  - Задержка перед ставкой: {runtime_config.betting.bet_delay_min:.1f}-{runtime_config.betting.bet_delay_max:.1f}с\n"
    status_line += f"  - Accounting stale timeout: {runtime_config.accounting.balance_stale_seconds:.0f}с\n"
    status_line += f"  - Accounting recovery reload: {runtime_config.accounting.recovery_reload_seconds:.0f}с\n"
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