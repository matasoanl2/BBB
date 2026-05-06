"""Вспомогательные функции для динамического выбора ставки по частотам."""

from __future__ import annotations

from collections import Counter
import psycopg2
import random

from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_config import BetTarget, RuntimeConfig


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
    get_db_connection_func=None,
) -> dict:
    """Посчитать частоты комбинаций по historical game_results с учетом dynamic-фильтров."""

    betting_state = runtime_context.betting_state
    database_config = runtime_config.database
    dynamic_config = runtime_config.dynamic_betting
    bet_debug_enabled = runtime_config.betting.debug_enabled
    try:
        conn = get_db_connection_func() if get_db_connection_func is not None else psycopg2.connect(
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


def _combo_to_target(combo_key: str) -> BetTarget | None:
    if combo_key == "double":
        return BetTarget(outcome="double", specifier="")

    parts = combo_key.split("_")
    if len(parts) != 2:
        return None

    outcome = parts[0]
    specifier = parts[1]
    if outcome not in {"red", "yellow"}:
        return None
    if specifier not in {"1", "2", "3", "4", "5", "6"}:
        return None
    return BetTarget(outcome=outcome, specifier=specifier)


def _combo_color_key(combo_key: str) -> str | None:
    if combo_key == "double":
        return "double"
    if combo_key.startswith("red_"):
        return "red"
    if combo_key.startswith("yellow_"):
        return "yellow"
    return None


def _stats_sort_key(item: tuple[str, dict]) -> tuple[float, int, str]:
    combo_key, combo_stats = item
    return (
        float(combo_stats.get("frequency", 0.0) or 0.0),
        int(combo_stats.get("freq", 0) or 0),
        combo_key,
    )


def _build_configured_color_counts(configured_targets: tuple[BetTarget, ...]) -> dict[str, int]:
    color_counts = Counter({"red": 0, "yellow": 0, "double": 0})
    for target in configured_targets:
        if target.outcome == "double":
            color_counts["double"] += 1
        elif target.outcome in {"red", "yellow"}:
            color_counts[target.outcome] += 1
    return {
        "red": int(color_counts["red"]),
        "yellow": int(color_counts["yellow"]),
        "double": int(color_counts["double"]),
    }


def _apply_dynamic_runtime_state(
    *,
    runtime_context: RuntimeContext,
    outcome: str,
    specifier: str,
    dynamic_targets: list[str],
    dynamic_color_counts: dict[str, int],
) -> None:
    """Синхронизировать runtime target и dynamic state в betting_state."""

    runtime_context.set_current_bet_target(outcome, specifier)
    betting_state = runtime_context.betting_state
    betting_state["dynamic_outcome"] = outcome
    betting_state["dynamic_specifier"] = specifier
    betting_state["dynamic_targets"] = dynamic_targets
    betting_state["dynamic_color_counts"] = dynamic_color_counts


def get_best_combinations(
    *,
    stats: dict | None,
    runtime_context: RuntimeContext,
    runtime_config: RuntimeConfig,
    analyze_all_results_frequency_func,
    excluded_tokens: set[str] | None = None,
) -> tuple[tuple[BetTarget, ...], dict[str, int]]:
    """Выбрать N комбинаций (N=len(BET_TARGETS)) для multi-target dynamic режима.

    Returns:
        tuple[tuple[BetTarget, ...], dict[str, int]]: Кортеж из двух элементов:
            - выбранные цели ставок (`BetTarget`) в порядке итогового отбора для
              динамического multi-target режима;
            - словарь с количеством выбранных целей по типам/цветам (`red`,
              `yellow`, `double`), который используется для контроля и анализа
              сохранения цветового соотношения в итоговом наборе.
    """
    configured_targets = runtime_context.get_configured_bet_targets()
    target_count = len(configured_targets)
    if target_count <= 0:
        return tuple(), {"red": 0, "yellow": 0, "double": 0}

    dynamic_config = runtime_config.dynamic_betting
    if stats is None:
        stats = analyze_all_results_frequency_func()
    if not stats:
        return tuple(), {"red": 0, "yellow": 0, "double": 0}

    selectable_stats = dict(stats)
    if not dynamic_config.include_double_selection:
        selectable_stats.pop("double", None)
    if not selectable_stats:
        return tuple(), {"red": 0, "yellow": 0, "double": 0}

    if dynamic_config.lock_color:
        allowed_colors = {
            target.outcome for target in configured_targets
        }
        selectable_stats = {k: v for k, v in selectable_stats.items() if _combo_color_key(k) in allowed_colors}
        if not selectable_stats:
            return tuple(), {"red": 0, "yellow": 0, "double": 0}

    blocked_tokens = {str(token).strip().upper() for token in (excluded_tokens or set()) if str(token).strip()}
    ranked_keys = [
        combo_key
        for combo_key, _ in sorted(selectable_stats.items(), key=_stats_sort_key, reverse=True)
        if _combo_to_target(combo_key) is not None
        and _combo_to_target(combo_key).token not in blocked_tokens
    ]
    if not ranked_keys:
        return tuple(), {"red": 0, "yellow": 0, "double": 0}

    selected_keys: list[str] = []
    if dynamic_config.preserve_color_ratio and target_count > 1:
        required_color_counts = _build_configured_color_counts(configured_targets)
        for color_key in ("red", "yellow", "double"):
            required_count = required_color_counts.get(color_key, 0)
            if required_count <= 0:
                continue
            color_candidates = [combo_key for combo_key in ranked_keys if _combo_color_key(combo_key) == color_key]
            for combo_key in color_candidates[:required_count]:
                if combo_key not in selected_keys:
                    selected_keys.append(combo_key)

    for combo_key in ranked_keys:
        if len(selected_keys) >= target_count:
            break
        if combo_key in selected_keys:
            continue
        selected_keys.append(combo_key)

    selected_targets: list[BetTarget] = []
    for combo_key in selected_keys[:target_count]:
        target = _combo_to_target(combo_key)
        if target is not None:
            selected_targets.append(target)

    selected_color_counts = _build_configured_color_counts(tuple(selected_targets))
    return tuple(selected_targets), selected_color_counts


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

    if dynamic_config.lock_color and default_outcome != "double":
        selectable_stats = {k: v for k, v in selectable_stats.items() if _combo_color_key(k) == default_outcome}
        if bet_debug_enabled:
            print(f"[DEBUG DYNAMIC] lock_color=True: ограничиваем выбор цветом '{default_outcome}', доступно комбинаций: {len(selectable_stats)}", flush=True)

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

    candidate_colors = ("red", "yellow")
    if dynamic_config.lock_color and default_outcome in {"red", "yellow"}:
        candidate_colors = (default_outcome,)

    candidates: list[tuple[str, dict]] = []
    for color in candidate_colors:
        weighted_sum = 0
        total_hits = 0
        for value in range(1, 7):
            combo_key = f"{color}_{value}"
            combo_stats = selectable_stats.get(combo_key)
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
        candidate_stats = selectable_stats.get(candidate_key, {"freq": 0, "frequency": 0.0})
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
    excluded_tokens: set[str] | None = None,
) -> tuple[str, str]:
    """Обновить текущую цель ставки, если настал момент dynamic-пересчета."""

    current_outcome, current_specifier = runtime_context.get_current_bet_target()
    betting_state = runtime_context.betting_state
    dynamic_config = runtime_config.dynamic_betting
    bet_debug_enabled = runtime_config.betting.debug_enabled
    color_cyan = runtime_config.colors.cyan
    color_reset = runtime_config.colors.reset
    configured_targets = runtime_context.get_configured_bet_targets()
    multi_target_mode = len(configured_targets) > 1
    dynamic_multi_effective = multi_target_mode and dynamic_config.multi_target_enabled

    if bet_debug_enabled:
        print(
            "[DEBUG UPDATE_DYN] Function entered. "
            f"DYNAMIC_BET_MODE={dynamic_config.enabled}, "
            f"MULTI_TARGET_MODE={multi_target_mode}, "
            f"DYNAMIC_MULTI_TARGET_ENABLED={dynamic_config.multi_target_enabled}",
            flush=True,
        )

    if not dynamic_config.enabled:
        if bet_debug_enabled:
            print("[DEBUG UPDATE_DYN] Early return: DYNAMIC_BET_MODE is False", flush=True)
        return current_outcome, current_specifier

    if multi_target_mode and not dynamic_multi_effective:
        if bet_debug_enabled:
            print("[DEBUG UPDATE_DYN] Multi-target active, but dynamic multi-target mode is disabled.", flush=True)
        return current_outcome, current_specifier

    total_bet_rounds = betting_state.get("total_bet_rounds", 0)
    total_bets_placed = betting_state.get("total_bets_placed", 0)
    step_counter = total_bet_rounds if total_bet_rounds > 0 else total_bets_placed
    step_counter_name = "total_bet_rounds" if total_bet_rounds > 0 else "total_bets_placed"

    next_trigger = ((step_counter // dynamic_config.recalc_interval) + 1) * dynamic_config.recalc_interval
    if bet_debug_enabled:
        modulo_result = step_counter % dynamic_config.recalc_interval if dynamic_config.recalc_interval > 0 else "ERROR"
        print(
            f"[DEBUG UPDATE_DYN] recalc_counter={step_counter_name}:{step_counter}, "
            f"DYNAMIC_RECALC_INTERVAL={dynamic_config.recalc_interval}, modulo result={modulo_result}, next trigger at {next_trigger}",
            flush=True,
        )

    if not (step_counter > 0 and step_counter % dynamic_config.recalc_interval == 0):
        return current_outcome, current_specifier

    stats = analyze_all_results_frequency_func()
    if bet_debug_enabled:
        print(f"[DEBUG DYNAMIC] Проверка на ходу {step_counter}: results_window={dynamic_config.window_size}, interval={dynamic_config.recalc_interval}, analyzed_combos={len(stats)}", flush=True)

    if not stats:
        if bet_debug_enabled:
            print("[DEBUG DYNAMIC] Нет данных game_results для анализа, пропускаем обновление", flush=True)
        return current_outcome, current_specifier

    if dynamic_multi_effective:
        selected_targets, selected_color_counts = get_best_combinations(
            stats=stats,
            runtime_context=runtime_context,
            runtime_config=runtime_config,
            analyze_all_results_frequency_func=analyze_all_results_frequency_func,
            excluded_tokens=excluded_tokens,
        )

        if not selected_targets:
            if bet_debug_enabled:
                print("[DEBUG DYNAMIC] Не удалось выбрать dynamic multi-target цели, пропускаем обновление", flush=True)
            return current_outcome, current_specifier

        selected_tokens = [target.token for target in selected_targets]
        previous_tokens = list(betting_state.get("dynamic_targets") or [])
        changed = previous_tokens != selected_tokens

        lead_target = selected_targets[0]
        lead_specifier = lead_target.specifier or "5"
        _apply_dynamic_runtime_state(
            runtime_context=runtime_context,
            outcome=lead_target.outcome,
            specifier=lead_specifier,
            dynamic_targets=selected_tokens,
            dynamic_color_counts=selected_color_counts,
        )

        if changed:
            if dynamic_config.update_output_enabled:
                print(f"\n{color_cyan}📊 ДИНАМИЧЕСКОЕ ОБНОВЛЕНИЕ MULTI-TARGET (ход {step_counter}):{color_reset}", flush=True)
                sorted_stats = sorted(stats.items(), key=lambda item: item[1]["frequency"], reverse=True)
                for index, (combo, data) in enumerate(sorted_stats[:5], 1):
                    display_combo = format_combo_pretty_func(combo)
                    print(f"  {index}. {display_combo:20} выпал {data['freq']:2d} раз ({data['frequency']:5.1f}%)", flush=True)

                selected_pretty = ", ".join(format_outcome_pretty_func(target.outcome, target.specifier) for target in selected_targets)
                print(f"  ➜ Выбраны: {selected_pretty}", flush=True)
                print(
                    "  ➜ Цветовой состав: "
                    f"red={selected_color_counts['red']}, yellow={selected_color_counts['yellow']}, double={selected_color_counts['double']}",
                    flush=True,
                )
                print("", flush=True)
        elif dynamic_config.unchanged_analysis_output_enabled:
            print(f"\n{color_cyan}📊 АНАЛИЗ DYNAMIC MULTI-TARGET (ход {step_counter}):{color_reset}", flush=True)
            print(f"  Текущие цели: {', '.join(selected_tokens)}", flush=True)
            print(
                "  Цветовой состав: "
                f"red={selected_color_counts['red']}, yellow={selected_color_counts['yellow']}, double={selected_color_counts['double']}",
                flush=True,
            )
            print("", flush=True)

        return runtime_context.get_current_bet_target()

    best_outcome, best_specifier = get_best_combination_func(stats)
    old_outcome = current_outcome
    old_specifier = current_specifier

    if best_outcome != current_outcome or best_specifier != current_specifier:
        current_outcome = best_outcome
        current_specifier = best_specifier if best_specifier else "5"
        _apply_dynamic_runtime_state(
            runtime_context=runtime_context,
            outcome=current_outcome,
            specifier=current_specifier,
            dynamic_targets=["D" if current_outcome == "double" else f"{'R' if current_outcome == 'red' else 'Y'}{current_specifier}"],
            dynamic_color_counts={
                "red": 1 if current_outcome == "red" else 0,
                "yellow": 1 if current_outcome == "yellow" else 0,
                "double": 1 if current_outcome == "double" else 0,
            },
        )

        if bet_debug_enabled:
            print(f"[DEBUG DYNAMIC] ✅ СМЕНА: {format_outcome_pretty_func(old_outcome, old_specifier)} → {format_outcome_pretty_func(current_outcome, current_specifier)}", flush=True)

        if dynamic_config.update_output_enabled:
            print(f"\n{color_cyan}📊 ДИНАМИЧЕСКОЕ ОБНОВЛЕНИЕ СТАВКИ (ход {step_counter}):{color_reset}", flush=True)
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

    _apply_dynamic_runtime_state(
        runtime_context=runtime_context,
        outcome=current_outcome,
        specifier=current_specifier,
        dynamic_targets=["D" if current_outcome == "double" else f"{'R' if current_outcome == 'red' else 'Y'}{current_specifier}"],
        dynamic_color_counts={
            "red": 1 if current_outcome == "red" else 0,
            "yellow": 1 if current_outcome == "yellow" else 0,
            "double": 1 if current_outcome == "double" else 0,
        },
    )

    if not dynamic_config.unchanged_analysis_output_enabled:
        return current_outcome, current_specifier

    print(f"\n{color_cyan}📊 АНАЛИЗ ДИНАМИЧЕСКОЙ СТАВКИ (ход {step_counter}):{color_reset}", flush=True)
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