"""Вспомогательные функции для динамического выбора ставки по частотам."""

from __future__ import annotations

import psycopg2
import random

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import RuntimeConfig


def analyze_recent_bets_stats(*, runtime_context: RuntimeContext) -> dict:
    """Собрать локальную статистику win-rate по недавним ставкам из runtime state."""

    recent_bets = runtime_context.betting_state.get("recent_bets", [])
    if not recent_bets:
        return {}

    stats = {}
    for bet in recent_bets:
        combo = bet.get("combo")
        result = bet.get("result")
        if combo not in stats:
            stats[combo] = {"wins": 0, "total": 0, "win_rate": 0}
        stats[combo]["total"] += 1
        if result:
            stats[combo]["wins"] += 1
        stats[combo]["win_rate"] = (stats[combo]["wins"] / stats[combo]["total"]) * 100 if stats[combo]["total"] > 0 else 0
    return stats


def analyze_all_results_frequency(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
) -> dict:
    """Посчитать частоты комбинаций по historical game_results с учетом dynamic-фильтров."""

    betting_state = runtime_context.betting_state
    database_config = runtime_config.database
    dynamic_config = runtime_config.dynamic_betting
    bet_debug_enabled = runtime_config.betting.debug_enabled
    try:
        conn = psycopg2.connect(
            host=database_config.host,
            port=database_config.port,
            user=database_config.user,
            password=database_config.password,
            database=database_config.name,
        )
        cursor = conn.cursor()

        current_player_name = betting_state.get("last_round_player_name")
        current_position = betting_state.get("last_round_position")
        where_clauses = []
        query_params = []

        if dynamic_config.filter_by_player and current_player_name:
            where_clauses.append("player_name = %s")
            query_params.append(current_player_name)

        if dynamic_config.filter_by_side and current_position:
            where_clauses.append("dice_results->'player'->>'position' = %s")
            query_params.append(current_position)

        query = "SELECT player_name, dice_results FROM game_results"
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " ORDER BY timestamp DESC LIMIT %s"
        query_params.append(dynamic_config.window_size)

        cursor.execute(query, tuple(query_params))
        results = cursor.fetchall()
        cursor.close()
        conn.close()

        if not results:
            return {}

        stats = {}
        total_results = len(results)
        for _, dice_results_json in results:
            if not dice_results_json:
                continue
            dice_data = dice_results_json.get("dice", []) if isinstance(dice_results_json, dict) else []
            if len(dice_data) >= 2:
                dice_1 = dice_data[0]
                dice_2 = dice_data[1]
                dice_1_color = dice_1.get("color") if isinstance(dice_1, dict) else None
                dice_1_value = dice_1.get("value") if isinstance(dice_1, dict) else None
                dice_2_color = dice_2.get("color") if isinstance(dice_2, dict) else None
                dice_2_value = dice_2.get("value") if isinstance(dice_2, dict) else None

                if dice_1_color == "red" and isinstance(dice_1_value, int) and 1 <= dice_1_value <= 6:
                    combo = f"red_{dice_1_value}"
                    if combo not in stats:
                        stats[combo] = {"freq": 0}
                    stats[combo]["freq"] += 1

                if dice_2_color == "yellow" and isinstance(dice_2_value, int) and 1 <= dice_2_value <= 6:
                    combo = f"yellow_{dice_2_value}"
                    if combo not in stats:
                        stats[combo] = {"freq": 0}
                    stats[combo]["freq"] += 1

                if isinstance(dice_1_value, int) and isinstance(dice_2_value, int) and dice_1_value == dice_2_value:
                    combo = "double"
                    if combo not in stats:
                        stats[combo] = {"freq": 0}
                    stats[combo]["freq"] += 1

        for combo in stats:
            stats[combo]["frequency"] = (stats[combo]["freq"] / total_results) * 100

        if bet_debug_enabled and (dynamic_config.filter_by_player or dynamic_config.filter_by_side):
            applied_filters = []
            if dynamic_config.filter_by_player and current_player_name:
                applied_filters.append(f"player={current_player_name}")
            if dynamic_config.filter_by_side and current_position:
                applied_filters.append(f"side={current_position}")
            if applied_filters:
                print(f"[DEBUG DYNAMIC] Применены фильтры анализа: {', '.join(applied_filters)}", flush=True)

        return stats
    except Exception as exc:
        if bet_debug_enabled:
            print(f"[DEBUG] Error analyzing all results: {exc}", flush=True)
        return {}


def get_best_combination(
    *,
    stats: dict | None,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    analyze_all_results_frequency_func,
) -> tuple[str, str]:
    """Выбрать лучшую комбинацию ставки на основе рассчитанных частот."""

    default_outcome, default_specifier = runtime_context.get_current_bet_target()
    dynamic_config = runtime_config.dynamic_betting
    bet_debug_enabled = runtime_config.betting.debug_enabled
    if stats is None:
        stats = analyze_all_results_frequency_func()

    if not stats:
        return (default_outcome, default_specifier)

    selectable_stats = dict(stats)
    if not dynamic_config.include_double_selection:
        selectable_stats.pop("double", None)

    if not selectable_stats:
        return (default_outcome, default_specifier)

    if not dynamic_config.use_average_value_selection:
        best_combo = max(selectable_stats.items(), key=lambda item: (item[1]["frequency"], item[1]["freq"]))
        combo_key = best_combo[0]
        if bet_debug_enabled:
            freq = best_combo[1]["frequency"]
            freq_count = best_combo[1]["freq"]
            print(f"[DEBUG DYNAMIC] Average selection disabled; best combo by frequency: {combo_key} (freq={freq:.1f}%, count={freq_count})", flush=True)
        if combo_key == "double":
            return ("double", "")
        parts = combo_key.split("_")
        return (parts[0], parts[1])

    candidates: list[tuple[str, dict]] = []
    for color in ("red", "yellow"):
        weighted_sum = 0
        total_hits = 0
        for value in range(1, 7):
            combo_key = f"{color}_{value}"
            combo_stats = stats.get(combo_key)
            if not combo_stats:
                continue
            freq_count = int(combo_stats.get("freq", 0) or 0)
            weighted_sum += value * freq_count
            total_hits += freq_count

        if total_hits <= 0:
            continue

        avg_value = weighted_sum / total_hits
        rounded_value = max(1, min(6, int(avg_value + 0.5)))
        candidate_key = f"{color}_{rounded_value}"
        candidate_stats = stats.get(candidate_key, {"freq": 0, "frequency": 0.0})
        candidates.append((candidate_key, {
            "freq": int(candidate_stats.get("freq", 0) or 0),
            "frequency": float(candidate_stats.get("frequency", 0.0) or 0.0),
            "avg_value": avg_value,
            "rounded_value": rounded_value,
        }))

    if dynamic_config.include_double_selection and "double" in selectable_stats:
        double_stats = selectable_stats["double"]
        candidates.append(("double", {
            "freq": int(double_stats.get("freq", 0) or 0),
            "frequency": float(double_stats.get("frequency", 0.0) or 0.0),
            "avg_value": None,
            "rounded_value": None,
        }))

    if not candidates:
        return (default_outcome, default_specifier)

    best_combo = max(candidates, key=lambda item: (item[1]["frequency"], item[1]["freq"]))
    combo_key = best_combo[0]

    if bet_debug_enabled:
        for candidate_key, candidate_data in candidates:
            if candidate_key == "double":
                print(f"[DEBUG DYNAMIC] candidate={candidate_key} freq={candidate_data['frequency']:.1f}% count={candidate_data['freq']}", flush=True)
            else:
                print(
                    f"[DEBUG DYNAMIC] candidate={candidate_key} avg={candidate_data['avg_value']:.2f} rounded={candidate_data['rounded_value']} freq={candidate_data['frequency']:.1f}% count={candidate_data['freq']}",
                    flush=True,
                )

    if combo_key == "double":
        return ("double", "")
    parts = combo_key.split("_")
    return (parts[0], parts[1])


def update_dynamic_bet(
    *,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    analyze_all_results_frequency_func,
    get_best_combination_func,
    format_outcome_pretty_func,
    format_combo_pretty_func,
) -> tuple[str, str]:
    """Обновить текущую цель ставки, если настал момент dynamic-пересчета."""

    current_outcome, current_specifier = runtime_context.get_current_bet_target()
    betting_state = runtime_context.betting_state
    dynamic_config = runtime_config.dynamic_betting
    bet_debug_enabled = runtime_config.betting.debug_enabled
    color_cyan = runtime_config.colors.cyan
    color_reset = runtime_config.colors.reset

    if bet_debug_enabled:
        print(f"[DEBUG UPDATE_DYN] Function entered. DYNAMIC_BET_MODE={dynamic_config.enabled}", flush=True)

    if not dynamic_config.enabled:
        if bet_debug_enabled:
            print("[DEBUG UPDATE_DYN] Early return: DYNAMIC_BET_MODE is False", flush=True)
        return current_outcome, current_specifier

    total_bets = betting_state.get("total_bets_placed", 0)
    next_trigger = ((total_bets // dynamic_config.recalc_interval) + 1) * dynamic_config.recalc_interval
    if bet_debug_enabled:
        modulo_result = total_bets % dynamic_config.recalc_interval if dynamic_config.recalc_interval > 0 else "ERROR"
        print(f"[DEBUG UPDATE_DYN] total_bets={total_bets}, DYNAMIC_RECALC_INTERVAL={dynamic_config.recalc_interval}, modulo result={modulo_result}, next trigger at {next_trigger}", flush=True)

    if not (total_bets > 0 and total_bets % dynamic_config.recalc_interval == 0):
        return current_outcome, current_specifier

    stats = analyze_all_results_frequency_func()
    if bet_debug_enabled:
        print(f"[DEBUG DYNAMIC] Проверка на ходу {total_bets}: results_window={dynamic_config.window_size}, interval={dynamic_config.recalc_interval}, analyzed_combos={len(stats)}", flush=True)

    if not stats:
        if bet_debug_enabled:
            print("[DEBUG DYNAMIC] Нет данных game_results для анализа, пропускаем обновление", flush=True)
        return current_outcome, current_specifier

    best_outcome, best_specifier = get_best_combination_func(stats)
    old_outcome = current_outcome
    old_specifier = current_specifier

    if best_outcome != current_outcome or best_specifier != current_specifier:
        current_outcome = best_outcome
        current_specifier = best_specifier if best_specifier else "5"
        runtime_context.set_current_bet_target(current_outcome, current_specifier)
        betting_state["dynamic_outcome"] = current_outcome
        betting_state["dynamic_specifier"] = current_specifier

        if bet_debug_enabled:
            print(f"[DEBUG DYNAMIC] ✅ СМЕНА: {format_outcome_pretty_func(old_outcome, old_specifier)} → {format_outcome_pretty_func(current_outcome, current_specifier)}", flush=True)

        print(f"\n{color_cyan}📊 ДИНАМИЧЕСКОЕ ОБНОВЛЕНИЕ СТАВКИ (ход {total_bets}):{color_reset}", flush=True)
        sorted_stats = sorted(stats.items(), key=lambda item: item[1]["frequency"], reverse=True)
        for index, (combo, data) in enumerate(sorted_stats[:3], 1):
            display_combo = format_combo_pretty_func(combo)
            print(f"  {index}. {display_combo:20} выпал {data['freq']:2d} раз ({data['frequency']:5.1f}%)", flush=True)
        selected_combo = f"{current_outcome}_{current_specifier}" if current_outcome != "double" else "double"
        display_outcome = format_combo_pretty_func(selected_combo)
        print(f"  ➜ Выбрана: {display_outcome}", flush=True)
        print("", flush=True)
        return current_outcome, current_specifier

    if bet_debug_enabled:
        print(f"[DEBUG DYNAMIC] Ставка не изменилась: {current_outcome if current_outcome == 'double' else f'{current_outcome}({current_specifier})'} оптимальна", flush=True)

    print(f"\n{color_cyan}📊 АНАЛИЗ ДИНАМИЧЕСКОЙ СТАВКИ (ход {total_bets}):{color_reset}", flush=True)
    sorted_stats = sorted(stats.items(), key=lambda item: item[1]["frequency"], reverse=True)
    for index, (combo, data) in enumerate(sorted_stats[:5], 1):
        display_combo = format_combo_pretty_func(combo)
        is_current = "⭐" if combo == f"{current_outcome}_{current_specifier}" or (combo == "double" and current_outcome == "double") else "  "
        print(f"  {is_current} {index}. {display_combo:18} выпал {data['freq']:2d} раз ({data['frequency']:5.1f}%)", flush=True)
    print("", flush=True)
    return current_outcome, current_specifier


def generate_random_bet(*, runtime_config: RuntimeConfig, format_outcome_pretty_func) -> tuple[str, str]:
    """Сгенерировать случайную комбинацию ставки как fallback после длинной серии проигрышей."""

    combos = [
        ("red", "1"), ("red", "2"), ("red", "3"), ("red", "4"), ("red", "5"), ("red", "6"),
        ("yellow", "1"), ("yellow", "2"), ("yellow", "3"), ("yellow", "4"), ("yellow", "5"), ("yellow", "6"),
        ("double", ""),
    ]
    outcome, specifier = random.choice(combos)
    print(f"{runtime_config.colors.magenta}⚠️  ПОЛОСА ИЗ 15 ПРОИГРЫШЕЙ! Генерируем СЛУЧАЙНУЮ ставку: {format_outcome_pretty_func(outcome, specifier)}{runtime_config.colors.reset}", flush=True)
    return outcome, specifier