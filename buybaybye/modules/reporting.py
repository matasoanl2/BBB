"""Вспомогательные функции для отчетов по сессии и статистике кубиков."""

from __future__ import annotations

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import RuntimeConfig


def print_session_stats(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    checkpoint: int,
    calculate_roi_func,
) -> None:
    """Вывести сводную статистику текущей сессии на контрольной точке."""

    betting_state = runtime_context.betting_state
    if not betting_state:
        return

    colors = runtime_config.colors

    total_bets = betting_state.get("total_bets_placed", 0)
    total_profit = betting_state.get("total_profit", 0)
    roi = calculate_roi_func()

    header = "📊 СТАТИСТИКА СЕССИИ" + (f" (ставка {checkpoint})" if checkpoint > 0 else " (ИТОГОВАЯ)")
    print("\n" + "=" * 60, flush=True)
    print(f"{colors.cyan}{header}{colors.reset}", flush=True)
    print("=" * 60, flush=True)
    print(f"  Ставок совершено: {colors.magenta}{total_bets}{colors.reset}", flush=True)
    print(f"  Общая сумма ставок: {colors.yellow}{betting_state.get('total_bet_amount', 0):.0f}р{colors.reset}", flush=True)
    profit_color = colors.green if total_profit >= 0 else colors.red
    print(f"  Общий профит: {profit_color}{total_profit:.0f}р{colors.reset}", flush=True)
    roi_color = colors.green if roi >= 0 else colors.red
    print(f"  ROI: {roi_color}{roi:.2f}%{colors.reset}", flush=True)
    print("=" * 60 + "\n", flush=True)


def print_dice_stats_20(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    format_combo_pretty_func,
) -> None:
    """Печатать накопительную статистику комбинаций и дублей каждые 20 ставок."""

    betting_state = runtime_context.betting_state
    if not betting_state:
        return

    colors = runtime_config.colors

    total_bets = betting_state.get("total_bets_placed", 0)
    if total_bets % 20 != 0 or total_bets == 0:
        return

    reported = betting_state.get("reported_20_rounds", [])
    if total_bets in reported:
        return

    combo_stats = betting_state.get("combo_stats", {})
    double_stats = betting_state.get("double_stats", {})
    max_count = max(combo_stats.values()) if combo_stats else 0
    most_common_combos = [key for key, value in combo_stats.items() if value == max_count] if max_count > 0 else []

    print("\n" + "=" * 80, flush=True)
    print(f"{colors.cyan}🎲 СТАТИСТИКА КОМБИНАЦИЙ ЦВЕТ+ЗНАЧЕНИЕ (всего ходов: {total_bets}) — НАРАСТАЮЩИЙ ИТОГ{colors.reset}", flush=True)
    print("=" * 80, flush=True)
    print(f"\n{colors.magenta}📊 КОМБИНАЦИИ (цвет_значение):{colors.reset}", flush=True)
    print("-" * 80, flush=True)

    print(f"{colors.red}🔴 RED:{colors.reset}", flush=True)
    for value in range(1, 7):
        combo_key = f"red_{value}"
        count = combo_stats.get(combo_key, 0)
        percentage = (count / total_bets) * 100 if total_bets > 0 else 0
        if combo_key in most_common_combos:
            marker = " ← НАИБОЛЕЕ ЧАСТОЕ"
            color = colors.green
        else:
            marker = ""
            color = colors.reset
        pretty_combo = format_combo_pretty_func(combo_key)
        print(f"  {color}{pretty_combo:8} {count:3d} ({percentage:5.1f}%){colors.reset}{marker}", flush=True)

    print(f"\n{colors.yellow}🟡 YELLOW:{colors.reset}", flush=True)
    for value in range(1, 7):
        combo_key = f"yellow_{value}"
        count = combo_stats.get(combo_key, 0)
        percentage = (count / total_bets) * 100 if total_bets > 0 else 0
        if combo_key in most_common_combos:
            marker = " ← НАИБОЛЕЕ ЧАСТОЕ"
            color = colors.green
        else:
            marker = ""
            color = colors.reset
        pretty_combo = format_combo_pretty_func(combo_key)
        print(f"  {color}{pretty_combo:8} {count:3d} ({percentage:5.1f}%){colors.reset}{marker}", flush=True)

    print("\n" + "-" * 80, flush=True)
    print(f"{colors.cyan}📈 ИТОГО ЗА СЕССИЮ:{colors.reset}", flush=True)

    total_doubles = double_stats.get("doubles", 0)
    total_no_doubles = double_stats.get("no_doubles", 0)
    total_rounds = total_doubles + total_no_doubles
    if total_rounds > 0:
        doubles_pct = (total_doubles / total_rounds) * 100
        no_doubles_pct = (total_no_doubles / total_rounds) * 100
        print(f"\n{colors.yellow}🔱 ДУБЛИ:{colors.reset}", flush=True)
        print(f"  ✓ Дубли:      {total_doubles:3d} раз ({doubles_pct:5.1f}%)", flush=True)
        print(f"  ✗ Не дубли:    {total_no_doubles:3d} раз ({no_doubles_pct:5.1f}%)", flush=True)

    print("=" * 80 + "\n", flush=True)
    reported.append(total_bets)
    betting_state["reported_20_rounds"] = reported