"""Фасад runtime-слоя для betting-домена."""

from __future__ import annotations

from buybaybye.modules.betting import calculate_bet_amount as _betting_calculate_bet_amount
from buybaybye.modules.betting import format_bet_log as _betting_format_bet_log
from buybaybye.modules.dynamic_betting import analyze_all_results_frequency as _dynamic_analyze_all_results_frequency
from buybaybye.modules.dynamic_betting import analyze_recent_bets_stats as _dynamic_analyze_recent_bets_stats
from buybaybye.modules.dynamic_betting import generate_random_bet as _dynamic_generate_random_bet
from buybaybye.modules.dynamic_betting import get_best_combination as _dynamic_get_best_combination
from buybaybye.modules.dynamic_betting import update_dynamic_bet as _dynamic_update_dynamic_bet
from buybaybye.modules.log_formatting import format_combo_pretty as _format_combo_pretty
from buybaybye.modules.log_formatting import format_outcome_plain as _format_outcome_plain
from buybaybye.modules.log_formatting import format_outcome_pretty as _format_outcome_pretty
from buybaybye.modules.log_formatting import format_result_plain as _format_result_plain
from buybaybye.modules.log_formatting import format_result_pretty as _format_result_pretty
from buybaybye.modules.log_formatting import pad_width_center as _pad_width_center
from buybaybye.modules.reporting import print_dice_stats_20 as _reporting_print_dice_stats_20
from buybaybye.modules.reporting import print_session_stats as _reporting_print_session_stats
from buybaybye.core.runtime_config import RuntimeConfig
from buybaybye.core.runtime_context import RuntimeContext


class BettingRuntimeService:
    """Предоставляет операции ставок, отчетности и динамического выбора цели."""

    def __init__(self, runtime_context: RuntimeContext, runtime_config: RuntimeConfig):
        """Инициализировать betting-service общим runtime state и конфигурацией."""

        self.runtime_context = runtime_context
        self.runtime_config = runtime_config

    def validate_base_bet(self, bet_amount: float) -> bool:
        """Проверить, что ставка сохраняет требуемую кратность десяти."""

        return bet_amount % 10 == 0

    def advance_step_after_set_error(self) -> tuple[int, int, bool]:
        """Сдвинуть шаг стратегии после ошибки SET и вернуть информацию о переходе."""

        max_steps = self.runtime_context.get_max_strategy_steps()
        current_step = self.runtime_context.betting_state.get("current_step", 0)

        restarted = False
        if current_step + 1 >= max_steps:
            self.runtime_context.betting_state["current_step"] = 0
            self.runtime_context.betting_state["consecutive_losses"] = 0
            restarted = True
        else:
            self.runtime_context.betting_state["current_step"] = current_step + 1
            self.runtime_context.betting_state["consecutive_losses"] = self.runtime_context.betting_state.get("consecutive_losses", 0) + 1

        self.runtime_context.betting_state["last_bet_amount"] = 0
        return current_step, max_steps, restarted

    def advance_step_2_after_set_error(self) -> tuple[int, int, bool]:
        """Сдвинуть шаг второго слота стратегии после ошибки SET."""

        betting_state_2 = self.runtime_context.betting_state_2
        current_strategy_2 = self.runtime_context.current_strategy_2
        if betting_state_2 is None or current_strategy_2 is None:
            return 0, 1, False

        max_steps = len(current_strategy_2.get("coefficients", [1]))
        current_step = betting_state_2.get("current_step", 0)

        restarted = False
        if current_step + 1 >= max_steps:
            betting_state_2["current_step"] = 0
            betting_state_2["consecutive_losses"] = 0
            restarted = True
        else:
            betting_state_2["current_step"] = current_step + 1
            betting_state_2["consecutive_losses"] = betting_state_2.get("consecutive_losses", 0) + 1

        betting_state_2["last_bet_amount"] = 0
        return current_step, max_steps, restarted

    def calculate_roi(self) -> float:
        """Рассчитать текущий ROI сессии по накопленному профиту и сумме ставок."""

        total_bet = self.runtime_context.betting_state.get("total_bet_amount", 0)
        total_profit = self.runtime_context.betting_state.get("total_profit", 0)
        if total_bet == 0:
            return 0.0
        return (total_profit / total_bet) * 100

    def calculate_roi_2(self) -> float:
        """Рассчитать ROI второго слота по накопленному профиту и сумме ставок."""

        betting_state_2 = self.runtime_context.betting_state_2
        if betting_state_2 is None:
            return 0.0
        total_bet = betting_state_2.get("total_bet_amount", 0)
        total_profit = betting_state_2.get("total_profit", 0)
        if total_bet == 0:
            return 0.0
        return (total_profit / total_bet) * 100

    def print_session_stats(self, checkpoint: int = 0) -> None:
        """Вывести сводную статистику сессии на указанной контрольной точке."""

        _reporting_print_session_stats(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            checkpoint=checkpoint,
            calculate_roi_func=self.calculate_roi,
        )

    def print_dice_stats_20(self) -> None:
        """Печатать накопительную статистику комбинаций каждые 20 ставок."""

        _reporting_print_dice_stats_20(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            format_combo_pretty_func=_format_combo_pretty,
        )

    def format_bet_log(
        self,
        action: str,
        status_icon: str,
        outcome: str = "-",
        amount: str = "-",
        step: str = "-",
        result: str = "-",
        profit: str = "-",
        roi: str = "-",
        balance: str = "-",
        real_balance: str = "-",
        error_msg: str = "",
        bets_count: str = "",
    ) -> str:
        """Собрать форматированную строку лога ставки с цветами и выравниванием."""

        plain_like_terminal_logs = (
            self.runtime_config.logging.terminal_plain_logs or self.runtime_config.logging.terminal_json_logs
        )

        return _betting_format_bet_log(
            action=action,
            status_icon=status_icon,
            outcome=outcome,
            amount=amount,
            step=step,
            result=result,
            profit=profit,
            roi=roi,
            balance=balance,
            real_balance=real_balance,
            error_msg=error_msg,
            bets_count=bets_count,
            color_reset=self.runtime_config.colors.reset,
            color_yellow=self.runtime_config.colors.yellow,
            color_green=self.runtime_config.colors.green,
            color_red=self.runtime_config.colors.red,
            color_magenta=self.runtime_config.colors.magenta,
            color_cyan=self.runtime_config.colors.cyan,
            plain_text_output_enabled=self.runtime_config.logging.terminal_plain_logs,
            json_one_line_output_enabled=self.runtime_config.logging.terminal_json_logs,
            pad_width_center_func=_pad_width_center,
            format_result_pretty_func=(
                _format_result_plain if plain_like_terminal_logs else _format_result_pretty
            ),
        )

    def format_outcome_pretty(self, outcome: str, specifier: str = "") -> str:
        """Преобразовать цель ставки в короткий читаемый вид для логов и UI."""

        if self.runtime_config.logging.terminal_plain_logs or self.runtime_config.logging.terminal_json_logs:
            return _format_outcome_plain(outcome, specifier)
        return _format_outcome_pretty(outcome, specifier)

    def analyze_recent_bets_stats(self) -> dict:
        """Собрать локальную статистику по recent_bets из runtime state."""

        return _dynamic_analyze_recent_bets_stats(runtime_context=self.runtime_context)

    def analyze_all_results_frequency(self) -> dict:
        """Посчитать частоты комбинаций по historical game_results из базы данных."""

        return _dynamic_analyze_all_results_frequency(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            get_db_connection_func=self._get_db_connection,
        )

    def _get_db_connection(self):
        from buybaybye.modules.db import get_db_connection

        return get_db_connection(database_config=self.runtime_config.database)

    def get_best_combination(self, stats: dict | None = None) -> tuple[str, str]:
        """Выбрать лучшую комбинацию ставки для dynamic betting режима."""

        return _dynamic_get_best_combination(
            stats=stats,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            analyze_all_results_frequency_func=self.analyze_all_results_frequency,
        )

    def _run_with_slot2_context(self, callback):
        """Временно переключить runtime_context на slot2 и вернуть результат callback."""

        ctx = self.runtime_context
        if ctx.betting_state_2 is None or ctx.current_strategy_2 is None:
            return callback()

        orig_state = ctx.betting_state
        orig_strategy = ctx.current_strategy
        orig_targets = ctx.configured_bet_targets
        orig_outcome = ctx.bet_mode_outcome
        orig_specifier = ctx.bet_mode_specifier

        ctx.betting_state = ctx.betting_state_2
        ctx.current_strategy = ctx.current_strategy_2
        ctx.configured_bet_targets = ctx.configured_bet_targets_2
        ctx.bet_mode_outcome = ctx.bet_mode_outcome_2
        ctx.bet_mode_specifier = ctx.bet_mode_specifier_2

        try:
            result = callback()
            ctx.bet_mode_outcome_2 = ctx.bet_mode_outcome
            ctx.bet_mode_specifier_2 = ctx.bet_mode_specifier
            return result
        finally:
            ctx.betting_state = orig_state
            ctx.current_strategy = orig_strategy
            ctx.configured_bet_targets = orig_targets
            ctx.bet_mode_outcome = orig_outcome
            ctx.bet_mode_specifier = orig_specifier

    def _find_non_intersecting_single_target(
        self,
        *,
        stats: dict,
        excluded_tokens: set[str],
    ) -> tuple[str, str] | None:
        """Найти лучшую single-target цель, не попадающую в excluded_tokens."""

        if not stats:
            return None

        remaining_stats = dict(stats)
        while remaining_stats:
            outcome, specifier = self.get_best_combination(remaining_stats)
            token = "D" if outcome == "double" else f"{'R' if outcome == 'red' else 'Y'}{specifier}"
            if token not in excluded_tokens:
                return outcome, specifier

            combo_key = "double" if outcome == "double" else f"{outcome}_{specifier}"
            if combo_key not in remaining_stats:
                break
            remaining_stats.pop(combo_key, None)

        return None

    def update_dynamic_bet(self, excluded_tokens: set[str] | None = None) -> tuple[str, str]:
        """Пересчитать dynamic-цель slot1 и при необходимости уйти от пересечения по top-ranked кандидатам."""

        ctx = self.runtime_context
        blocked_tokens = excluded_tokens or set()
        betting_state = ctx.betting_state
        configured_targets = ctx.get_configured_bet_targets()
        is_single_target = len(configured_targets) == 1

        _dynamic_update_dynamic_bet(
            runtime_context=ctx,
            runtime_config=self.runtime_config,
            analyze_all_results_frequency_func=self.analyze_all_results_frequency,
            get_best_combination_func=self.get_best_combination,
            format_outcome_pretty_func=_format_outcome_pretty,
            format_combo_pretty_func=_format_combo_pretty,
            excluded_tokens=blocked_tokens,
        )

        if blocked_tokens and is_single_target:
            current_outcome, current_specifier = ctx.get_current_bet_target()
            current_token = "D" if current_outcome == "double" else f"{'R' if current_outcome == 'red' else 'Y'}{current_specifier}"
            if current_token in blocked_tokens:
                stats = self.analyze_all_results_frequency()
                alternative = self._find_non_intersecting_single_target(
                    stats=stats,
                    excluded_tokens=blocked_tokens,
                )
                if alternative is not None:
                    alt_outcome, alt_specifier = alternative
                    alt_specifier = "" if alt_outcome == "double" else alt_specifier
                    ctx.set_current_bet_target(alt_outcome, alt_specifier)
                    betting_state["dynamic_outcome"] = alt_outcome
                    betting_state["dynamic_specifier"] = alt_specifier
                    betting_state["dynamic_targets"] = [
                        "D" if alt_outcome == "double" else f"{'R' if alt_outcome == 'red' else 'Y'}{alt_specifier}"
                    ]
                    betting_state["dynamic_color_counts"] = {
                        "red": 1 if alt_outcome == "red" else 0,
                        "yellow": 1 if alt_outcome == "yellow" else 0,
                        "double": 1 if alt_outcome == "double" else 0,
                    }

        return ctx.get_current_bet_target()

    def update_dynamic_bet_2(self, excluded_tokens: set[str] | None = None) -> tuple[str, str]:
        """Пересчитать dynamic-цель для slot2 и по возможности уйти от пересечения с slot1."""

        ctx = self.runtime_context
        if ctx.betting_state_2 is None or ctx.current_strategy_2 is None:
            return ctx.get_current_bet_target_2()

        if not self.runtime_config.dynamic_betting.enabled_2:
            return ctx.get_current_bet_target_2()

        blocked_tokens = excluded_tokens or set()

        def _update_slot2() -> tuple[str, str]:
            betting_state = ctx.betting_state
            configured_targets = ctx.get_configured_bet_targets()
            is_single_target = len(configured_targets) == 1

            original_dynamic_enabled = self.runtime_config.dynamic_betting.enabled
            self.runtime_config.dynamic_betting.enabled = True
            try:
                _dynamic_update_dynamic_bet(
                    runtime_context=ctx,
                    runtime_config=self.runtime_config,
                    analyze_all_results_frequency_func=self.analyze_all_results_frequency,
                    get_best_combination_func=self.get_best_combination,
                    format_outcome_pretty_func=_format_outcome_pretty,
                    format_combo_pretty_func=_format_combo_pretty,
                    excluded_tokens=blocked_tokens,
                )
            finally:
                self.runtime_config.dynamic_betting.enabled = original_dynamic_enabled

            if blocked_tokens and is_single_target:
                current_outcome, current_specifier = ctx.get_current_bet_target()
                current_token = "D" if current_outcome == "double" else f"{'R' if current_outcome == 'red' else 'Y'}{current_specifier}"
                if current_token in blocked_tokens:
                    stats = self.analyze_all_results_frequency()
                    alternative = self._find_non_intersecting_single_target(
                        stats=stats,
                        excluded_tokens=blocked_tokens,
                    )
                    if alternative is not None:
                        alt_outcome, alt_specifier = alternative
                        alt_specifier = "" if alt_outcome == "double" else alt_specifier
                        ctx.set_current_bet_target(alt_outcome, alt_specifier)
                        betting_state["dynamic_outcome"] = alt_outcome
                        betting_state["dynamic_specifier"] = alt_specifier
                        betting_state["dynamic_targets"] = [
                            "D" if alt_outcome == "double" else f"{'R' if alt_outcome == 'red' else 'Y'}{alt_specifier}"
                        ]
                        betting_state["dynamic_color_counts"] = {
                            "red": 1 if alt_outcome == "red" else 0,
                            "yellow": 1 if alt_outcome == "yellow" else 0,
                            "double": 1 if alt_outcome == "double" else 0,
                        }

            return ctx.get_current_bet_target()

        return self._run_with_slot2_context(_update_slot2)

    def generate_random_bet(self) -> tuple[str, str]:
        """Сгенерировать fallback-ставку для сброса после длинной серии проигрышей."""

        return _dynamic_generate_random_bet(
            runtime_config=self.runtime_config,
            format_outcome_pretty_func=_format_outcome_pretty,
        )

    def calculate_bet_amount(self) -> float:
        """Рассчитать размер следующей ставки по текущему шагу активной стратегии."""

        return _betting_calculate_bet_amount(
            base_bet=self.runtime_config.betting.base_bet,
            runtime_context=self.runtime_context,
        )

    def calculate_bet_amount_2(self) -> float:
        """Рассчитать размер следующей ставки по второй стратегии."""

        betting_state_2 = self.runtime_context.betting_state_2
        current_strategy_2 = self.runtime_context.current_strategy_2
        base_bet_2 = self.runtime_config.betting.base_bet_2

        if not current_strategy_2 or betting_state_2 is None:
            return base_bet_2

        current_step = betting_state_2.get("current_step", 0)
        coefficients = current_strategy_2.get("coefficients", [1])
        step_index = min(current_step, len(coefficients) - 1)
        coefficient = coefficients[step_index]
        amount = base_bet_2 * coefficient
        betting_state_2["last_bet_amount"] = amount
        return amount