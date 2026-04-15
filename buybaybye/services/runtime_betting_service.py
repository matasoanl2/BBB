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
from buybaybye.modules.log_formatting import format_outcome_pretty as _format_outcome_pretty
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

    def calculate_roi(self) -> float:
        """Рассчитать текущий ROI сессии по накопленному профиту и сумме ставок."""

        total_bet = self.runtime_context.betting_state.get("total_bet_amount", 0)
        total_profit = self.runtime_context.betting_state.get("total_profit", 0)
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
            pad_width_center_func=_pad_width_center,
            format_result_pretty_func=_format_result_pretty,
        )

    def format_outcome_pretty(self, outcome: str, specifier: str = "") -> str:
        """Преобразовать цель ставки в короткий читаемый вид для логов и UI."""

        return _format_outcome_pretty(outcome, specifier)

    def analyze_recent_bets_stats(self) -> dict:
        """Собрать локальную статистику по recent_bets из runtime state."""

        return _dynamic_analyze_recent_bets_stats(runtime_context=self.runtime_context)

    def analyze_all_results_frequency(self) -> dict:
        """Посчитать частоты комбинаций по historical game_results из базы данных."""

        return _dynamic_analyze_all_results_frequency(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
        )

    def get_best_combination(self, stats: dict | None = None) -> tuple[str, str]:
        """Выбрать лучшую комбинацию ставки для dynamic betting режима."""

        return _dynamic_get_best_combination(
            stats=stats,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            analyze_all_results_frequency_func=self.analyze_all_results_frequency,
        )

    def update_dynamic_bet(self) -> None:
        """Пересчитать и при необходимости обновить текущую цель dynamic ставки."""

        _dynamic_update_dynamic_bet(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            analyze_all_results_frequency_func=self.analyze_all_results_frequency,
            get_best_combination_func=self.get_best_combination,
            format_outcome_pretty_func=_format_outcome_pretty,
            format_combo_pretty_func=_format_combo_pretty,
        )

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