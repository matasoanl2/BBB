"""Вспомогательные функции для startup, status line и shutdown."""

from __future__ import annotations

import asyncio
import sys

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import RuntimeConfig


def _format_configured_target(runtime_context: RuntimeContext) -> str:
    configured_targets = runtime_context.get_configured_bet_targets()
    if not configured_targets:
        return "-"
    if len(configured_targets) == 1:
        return configured_targets[0].token
    return f"{', '.join(target.token for target in configured_targets)} (одновременно)"


def print_strategy_startup_info(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    format_outcome_pretty_func,
) -> None:
    """Вывести на старте сведения о стратегии и параметрах dynamic betting."""

    current_strategy = runtime_context.current_strategy
    dynamic_config = runtime_config.dynamic_betting
    multi_bet_enabled = len(runtime_context.get_configured_bet_targets()) > 1
    dynamic_mode_effective = dynamic_config.enabled and (not multi_bet_enabled or dynamic_config.multi_target_enabled)
    base_bet = runtime_config.betting.base_bet
    print(f"[STRATEGY] Загружена стратегия: {current_strategy['name']}", flush=True)
    print(f"[STRATEGY] Описание: {current_strategy['description']}", flush=True)
    print(f"[STRATEGY] Шагов: {len(current_strategy['coefficients'])}, базовая ставка: {base_bet}р", flush=True)
    print(f"[STRATEGY] Цель ставки: {_format_configured_target(runtime_context)}", flush=True)
    print("[STRATEGY] Примеры ставок (BASE_BET × коэффициент):", flush=True)
    for index in range(min(5, len(current_strategy["coefficients"]))):
        coeff = current_strategy["coefficients"][index]
        bet_amount = base_bet * coeff
        print(f"  Step {index+1}: {base_bet}р × {coeff} = {bet_amount}р ✓", flush=True)

    if dynamic_config.enabled and multi_bet_enabled and not dynamic_config.multi_target_enabled:
        print("[DYNAMIC] Задано несколько целей BET_TARGETS, dynamic multi-target отключен", flush=True)

    if dynamic_mode_effective:
        configured_targets = runtime_context.get_configured_bet_targets()
        if configured_targets:
            initial_bet_targets = ", ".join(
                format_outcome_pretty_func(target.outcome, target.specifier)
                for target in configured_targets
            )
        else:
            initial_outcome = runtime_context.bet_mode_outcome
            initial_specifier = runtime_context.bet_mode_specifier
            initial_bet_targets = format_outcome_pretty_func(initial_outcome, initial_specifier)

        print("\n[DYNAMIC] 🔄 ДИНАМИЧЕСКИЙ РЕЖИМ ВКЛЮЧЕН", flush=True)
        print(f"[DYNAMIC] Окно анализа: {dynamic_config.window_size} ставок", flush=True)
        print(f"[DYNAMIC] Пересчет: каждые {dynamic_config.recalc_interval} ставок", flush=True)
        print(f"[DYNAMIC] Multi-target: {'ON' if dynamic_config.multi_target_enabled else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Сохранять цветовой состав: {'ON' if dynamic_config.preserve_color_ratio else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Выбор по среднему значению: {'ON' if dynamic_config.use_average_value_selection else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Учитывать double: {'ON' if dynamic_config.include_double_selection else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Фильтр по игроку: {'ON' if dynamic_config.filter_by_player else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Фильтр по стороне: {'ON' if dynamic_config.filter_by_side else 'OFF'}", flush=True)
        print(f"[DYNAMIC] Начальная ставка: {initial_bet_targets}", flush=True)


def get_browser_launch_args() -> list[str]:
    """Вернуть набор Chromium-аргументов для запуска рабочего браузерного профиля."""

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
    """Собрать человекочитаемую status line для запущенного runtime-сеанса."""

    status_line = f"Браузер открыт. Роль рантайма: {runtime_config.role.name}\n"
    if runtime_config.role.uses_persistent_browser_profile:
        status_line += f"Профиль сессии: {runtime_config.browser.session_dir}\n"
    else:
        status_line += "Профиль сессии: не используется, контекст эфемерный\n"
    if runtime_config.betting.enabled and runtime_context.current_strategy:
        status_line += "🎲 РЕЖИМ СТАВОК ВКЛЮЧЕН\n"
        status_line += f"  - Стратегия: {runtime_context.current_strategy['name']}\n"
        status_line += f"  - Цель: {_format_configured_target(runtime_context)}\n"
        status_line += f"  - Базовая ставка: {runtime_config.betting.base_bet}р\n"
        status_line += f"  - Коэффициентов в прогрессии: {len(runtime_context.current_strategy['coefficients'])}\n"
        status_line += f"  - Задержка перед ставкой: {runtime_config.betting.bet_delay_min:.1f}-{runtime_config.betting.bet_delay_max:.1f}с\n"
    elif runtime_config.betting.requested_enabled and not runtime_config.betting.enabled:
        status_line += "🎲 РЕЖИМ СТАВОК ПРИНУДИТЕЛЬНО ОТКЛЮЧЕН ДЛЯ ТЕКУЩЕЙ РОЛИ\n"
    status_line += f"  - Accounting stale timeout: {runtime_config.accounting.balance_stale_seconds:.0f}с\n"
    status_line += f"  - Accounting initial balance timeout: {runtime_config.accounting.initial_balance_timeout_seconds:.0f}с\n"
    status_line += f"  - Accounting recovery reload: {runtime_config.accounting.recovery_reload_seconds:.0f}с\n"
    status_line += f"  - Accounting idle reconnect: {runtime_config.accounting.idle_reconnect_seconds:.0f}с\n"
    if runtime_config.role.uses_persistent_browser_profile:
        status_line += "Закройте окно браузера или нажмите Enter здесь - сессия сохранится."
    else:
        status_line += "Закройте окно браузера или нажмите Enter здесь - сессия завершится без сохранения профиля."
    return status_line


async def wait_for_exit_signal() -> None:
    """Дождаться Enter в интерактивной консоли или бесконечно ждать в headless-сценарии."""

    if sys.stdin.isatty():
        try:
            await asyncio.to_thread(input)
        except EOFError:
            pass
        return
    await asyncio.Event().wait()