from __future__ import annotations

from pathlib import Path

from buybaybye.core.runtime_config import (
    AccountingConfig,
    BetTarget,
    BettingConfig,
    BrowserConfig,
    ColorConfig,
    DatabaseConfig,
    DynamicBettingConfig,
    LoggingConfig,
    RuntimeConfig,
    RuntimeRoleConfig,
    TelegramConfig,
)
from buybaybye.core.runtime_context import create_runtime_context
from buybaybye.core.runtime_state import build_runtime_betting_state
from buybaybye.modules.dynamic_betting import get_best_combinations, update_dynamic_bet


def _make_runtime_config(
    *,
    configured_targets: tuple[BetTarget, ...],
    recalc_interval: int = 5,
    multi_target_enabled: bool = True,
    preserve_color_ratio: bool = False,
) -> RuntimeConfig:
    default_target = configured_targets[0]
    return RuntimeConfig(
        role=RuntimeRoleConfig("bettor", True, True, False),
        browser=BrowserConfig(Path("profile"), Path("strategies"), "target", "accounting", "bet", False),
        database=DatabaseConfig("postgres", "postgres", "localhost", "5432", "buybaybye"),
        betting=BettingConfig(
            True,
            True,
            configured_targets,
            ",".join(target.token for target in configured_targets),
            None,
            default_target.outcome,
            default_target.specifier or "5",
            10.0,
            "balanced",
            0.8,
            1.5,
            False,
        ),
        dynamic_betting=DynamicBettingConfig(
            True,
            40,
            recalc_interval,
            True,
            True,
            True,
            False,
            False,
            True,
            15,
            multi_target_enabled,
            preserve_color_ratio,
        ),
        accounting=AccountingConfig(15.0, 25.0, 30.0, 300.0, 3.0, False),
        telegram=TelegramConfig(False, "", "", 5.0, 60.0, True, True, True, True, True),
        logging=LoggingConfig(False, False),
        colors=ColorConfig(False, "", "", "", "", "", "", ""),
    )


def _make_runtime_context(configured_targets: tuple[BetTarget, ...]):
    context = create_runtime_context(
        configured_bet_targets=configured_targets,
        bet_mode_outcome=configured_targets[0].outcome,
        bet_mode_specifier=configured_targets[0].specifier or "5",
    )
    context.betting_state = build_runtime_betting_state(
        strategy=None,
        bet_mode_outcome=configured_targets[0].outcome,
        bet_mode_specifier=configured_targets[0].specifier or "5",
    )
    return context


def test_get_best_combinations_returns_configured_target_count() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("yellow", "2"),
        BetTarget("double", ""),
    )
    runtime_config = _make_runtime_config(configured_targets=configured_targets)
    runtime_context = _make_runtime_context(configured_targets)
    stats = {
        "red_6": {"freq": 40, "frequency": 40.0},
        "yellow_5": {"freq": 35, "frequency": 35.0},
        "double": {"freq": 20, "frequency": 20.0},
        "yellow_1": {"freq": 10, "frequency": 10.0},
    }

    selected_targets, _ = get_best_combinations(
        stats=stats,
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=lambda: stats,
    )

    assert len(selected_targets) == len(configured_targets)


def test_get_best_combinations_preserves_color_ratio_when_enabled() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("red", "2"),
        BetTarget("yellow", "3"),
        BetTarget("double", ""),
    )
    runtime_config = _make_runtime_config(
        configured_targets=configured_targets,
        preserve_color_ratio=True,
    )
    runtime_context = _make_runtime_context(configured_targets)
    stats = {
        "yellow_6": {"freq": 60, "frequency": 60.0},
        "yellow_5": {"freq": 50, "frequency": 50.0},
        "red_6": {"freq": 40, "frequency": 40.0},
        "red_5": {"freq": 30, "frequency": 30.0},
        "double": {"freq": 20, "frequency": 20.0},
    }

    _, selected_color_counts = get_best_combinations(
        stats=stats,
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=lambda: stats,
    )

    assert selected_color_counts == {"red": 2, "yellow": 1, "double": 1}


def test_update_dynamic_bet_skips_when_recalc_interval_not_reached() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("yellow", "2"),
    )
    runtime_config = _make_runtime_config(configured_targets=configured_targets, recalc_interval=5)
    runtime_context = _make_runtime_context(configured_targets)
    runtime_context.betting_state["total_bets_placed"] = 3

    analyze_calls = {"count": 0}

    def _analyze_stats() -> dict:
        analyze_calls["count"] += 1
        return {
            "red_1": {"freq": 1, "frequency": 10.0},
            "yellow_2": {"freq": 1, "frequency": 10.0},
        }

    update_dynamic_bet(
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=_analyze_stats,
        get_best_combination_func=lambda stats: ("red", "1"),
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_combo_pretty_func=lambda combo: combo,
    )

    assert analyze_calls["count"] == 0


def test_update_dynamic_bet_updates_multi_targets_and_state() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("yellow", "2"),
        BetTarget("double", ""),
    )
    runtime_config = _make_runtime_config(configured_targets=configured_targets)
    runtime_context = _make_runtime_context(configured_targets)
    runtime_context.betting_state["total_bets_placed"] = 10

    stats = {
        "red_6": {"freq": 50, "frequency": 50.0},
        "yellow_4": {"freq": 40, "frequency": 40.0},
        "double": {"freq": 30, "frequency": 30.0},
        "red_1": {"freq": 10, "frequency": 10.0},
    }

    update_dynamic_bet(
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=lambda: stats,
        get_best_combination_func=lambda stats: ("red", "6"),
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_combo_pretty_func=lambda combo: combo,
    )

    assert runtime_context.betting_state["dynamic_targets"] == ["R6", "Y4", "D"]
    assert runtime_context.betting_state["dynamic_color_counts"] == {"red": 1, "yellow": 1, "double": 1}


def test_update_dynamic_bet_multi_target_uses_rounds_for_recalc_skip() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("yellow", "2"),
    )
    runtime_config = _make_runtime_config(configured_targets=configured_targets, recalc_interval=5)
    runtime_context = _make_runtime_context(configured_targets)
    runtime_context.betting_state["total_bets_placed"] = 10
    runtime_context.betting_state["total_bet_rounds"] = 4

    analyze_calls = {"count": 0}

    def _analyze_stats() -> dict:
        analyze_calls["count"] += 1
        return {
            "red_6": {"freq": 12, "frequency": 30.0},
            "yellow_4": {"freq": 10, "frequency": 25.0},
        }

    update_dynamic_bet(
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=_analyze_stats,
        get_best_combination_func=lambda stats: ("red", "6"),
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_combo_pretty_func=lambda combo: combo,
    )

    assert analyze_calls["count"] == 0
    assert runtime_context.betting_state.get("dynamic_targets") == []


def test_update_dynamic_bet_multi_target_uses_rounds_for_recalc_update() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("yellow", "2"),
    )
    runtime_config = _make_runtime_config(configured_targets=configured_targets, recalc_interval=5)
    runtime_context = _make_runtime_context(configured_targets)
    runtime_context.betting_state["total_bets_placed"] = 11
    runtime_context.betting_state["total_bet_rounds"] = 5

    analyze_calls = {"count": 0}
    stats = {
        "red_6": {"freq": 12, "frequency": 30.0},
        "yellow_4": {"freq": 10, "frequency": 25.0},
        "double": {"freq": 4, "frequency": 10.0},
    }

    def _analyze_stats() -> dict:
        analyze_calls["count"] += 1
        return stats

    update_dynamic_bet(
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=_analyze_stats,
        get_best_combination_func=lambda stats: ("red", "6"),
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_combo_pretty_func=lambda combo: combo,
    )

    assert analyze_calls["count"] == 1
    assert runtime_context.betting_state["dynamic_targets"] == ["R6", "Y4"]


def test_update_dynamic_bet_rounds_fallbacks_to_total_bets_when_rounds_not_positive() -> None:
    configured_targets = (
        BetTarget("red", "1"),
        BetTarget("yellow", "2"),
    )
    runtime_config = _make_runtime_config(configured_targets=configured_targets, recalc_interval=5)
    runtime_context = _make_runtime_context(configured_targets)
    runtime_context.betting_state["total_bets_placed"] = 10
    runtime_context.betting_state["total_bet_rounds"] = 0

    analyze_calls = {"count": 0}
    stats = {
        "red_6": {"freq": 12, "frequency": 30.0},
        "yellow_4": {"freq": 10, "frequency": 25.0},
    }

    def _analyze_stats() -> dict:
        analyze_calls["count"] += 1
        return stats

    update_dynamic_bet(
        runtime_context=runtime_context,
        runtime_config=runtime_config,
        analyze_all_results_frequency_func=_analyze_stats,
        get_best_combination_func=lambda stats: ("red", "6"),
        format_outcome_pretty_func=lambda outcome, specifier: f"{outcome}:{specifier}",
        format_combo_pretty_func=lambda combo: combo,
    )

    assert analyze_calls["count"] == 1
    assert runtime_context.betting_state["dynamic_targets"] == ["R6", "Y4"]
