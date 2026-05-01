"""Верхнеуровневый runtime-facade, координирующий узкие доменные сервисы."""

from __future__ import annotations

import asyncio

from buybaybye.modules.betting import place_bet as _betting_place_bet
from buybaybye.modules.betting import place_bets as _betting_place_bets
from buybaybye.modules.betting import process_betting_round as _betting_process_betting_round
from buybaybye.modules.log_formatting import format_round_result_plain as _format_round_result_plain
from buybaybye.modules.log_formatting import format_round_result_pretty as _format_round_result_pretty
from buybaybye.modules.notifications import queue_telegram_notification as _notifications_queue_telegram_notification
from buybaybye.modules.notifications import send_telegram_notification_sync as _notifications_send_telegram_notification_sync
from buybaybye.services.runtime_accounting_service import AccountingRuntimeService
from buybaybye.services.runtime_auth_service import AuthRuntimeService
from buybaybye.services.runtime_betting_service import BettingRuntimeService
from buybaybye.services.runtime_infrastructure_service import InfrastructureRuntimeService
from buybaybye.core.runtime_config import RuntimeConfig
from buybaybye.core.runtime_context import RuntimeContext


class RuntimeServices:
    """Совместимый facade, открывающий runtime-surface для app-слоя."""

    def __init__(self, runtime_context: RuntimeContext, runtime_config: RuntimeConfig):
        """Собрать фасад верхнего уровня из runtime context, config и доменных сервисов."""

        self.runtime_context = runtime_context
        self.runtime_config = runtime_config
        self.auth = AuthRuntimeService(runtime_context, runtime_config)
        self.accounting = AccountingRuntimeService(runtime_context, runtime_config)
        self.betting = BettingRuntimeService(runtime_context, runtime_config)
        self.infrastructure = InfrastructureRuntimeService(runtime_context, runtime_config)

    def set_jwt_token(self, token: str) -> None:
        """Сохранить JWT токен через auth-service."""

        self.auth.set_jwt_token(token)

    def get_jwt_token(self) -> str | None:
        """Вернуть текущий JWT токен из auth-service."""

        return self.auth.get_jwt_token()

    def is_telegram_chat_id_mode(self, argv) -> bool:
        """Проверить, запущен ли процесс в режиме определения TELEGRAM_CHAT_ID."""

        return self.auth.is_telegram_chat_id_mode(argv)

    async def run_telegram_chat_id_helper(self) -> None:
        """Запустить Telegram helper для получения chat id."""

        await self.auth.run_telegram_chat_id_helper()

    def handle_response(self, response) -> None:
        """Передать browser response в auth-service для поиска JWT."""

        self.auth.handle_response(response)

    async def handle_response_async(self, response) -> None:
        """Асинхронно обработать browser response в auth-service."""

        await self.auth.handle_response_async(response)

    def handle_request(self, request) -> None:
        """Передать browser request в auth-service для поиска JWT."""

        self.auth.handle_request(request)

    def subscribe_jwt_search_to_page(self, page) -> None:
        """Подписать страницу на поиск JWT в сетевых событиях браузера."""

        self.auth.subscribe_jwt_search_to_page(page)

    def is_forbidden_access_error(self, status_code: int, response_text: str) -> bool:
        """Проверить, является ли ответ типичным признаком истекшего доступа к API."""

        return self.auth.is_forbidden_access_error(status_code, response_text)

    async def reload_page_and_refresh_token(self, page) -> bool:
        """Перезагрузить страницу и обновить JWT токен через auth-service."""

        return await self.auth.reload_page_and_refresh_token(page)

    async def reload_page_for_accounting_recovery(self, page, reason: str) -> bool:
        """Перезагрузить страницу для recovery accounting websocket по указанной причине."""

        return await self.accounting.reload_page_for_accounting_recovery(
            page,
            reason,
            get_balance_for_log_func=self.get_balance_for_log,
            queue_telegram_notification_func=self.queue_telegram_notification,
            update_runtime_snapshot_func=self.update_runtime_snapshot,
        )

    def validate_base_bet(self, bet_amount: float) -> bool:
        """Проверить корректность размера ставки относительно project invariants."""

        return self.betting.validate_base_bet(bet_amount)

    def advance_step_after_set_error(self) -> tuple[int, int, bool]:
        """Сдвинуть шаг прогрессии после SET-ошибки и вернуть детали перехода."""

        return self.betting.advance_step_after_set_error()

    def advance_step_2_after_set_error(self) -> tuple[int, int, bool]:
        """Сдвинуть шаг прогрессии второго слота после SET-ошибки."""

        return self.betting.advance_step_2_after_set_error()

    def get_db_connection(self):
        """Создать подключение к базе данных через infrastructure-service."""

        return self.infrastructure.get_db_connection()

    def ensure_runtime_schema(self) -> None:
        """Initialize runtime schema before live processing starts."""

        self.infrastructure.ensure_runtime_schema()

    def format_ws_payload(self, payload: object) -> str:
        """Преобразовать websocket payload в строку для логов и сохранения."""

        return self.infrastructure.format_ws_payload(payload)

    def save_target_ws_message(self, payload: object) -> None:
        """Сохранить target websocket payload в базе данных."""

        self.infrastructure.save_target_ws_message(payload)

    def build_runtime_snapshot(self, event_type: str = "heartbeat", extra: dict | None = None) -> dict:
        """Собрать snapshot текущего runtime state для dashboard и событий."""

        return self.infrastructure.build_runtime_snapshot(
            event_type=event_type,
            extra=extra,
            is_account_balance_stale_func=self.is_account_balance_stale,
        )

    def update_runtime_snapshot(self, event_type: str = "heartbeat", extra: dict | None = None) -> None:
        """Сохранить snapshot и соответствующее событие в runtime tables."""

        snapshot = self.build_runtime_snapshot(event_type=event_type, extra=extra)
        self.infrastructure.update_runtime_snapshot(
            snapshot=snapshot,
            event_type=event_type,
        )

    async def place_bet(self, page, outcome: str, specifier: str, amount: float, allow_refresh_retry: bool = True) -> bool:
        """Разместить ставку, пробросив зависимости из runtime facade в subsystem betting."""

        return await _betting_place_bet(
            page,
            outcome,
            specifier,
            amount,
            allow_refresh_retry=allow_refresh_retry,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            get_jwt_token_func=self.get_jwt_token,
            validate_base_bet_func=self.validate_base_bet,
            calculate_roi_func=self.betting.calculate_roi,
            format_outcome_pretty_func=self.betting.format_outcome_pretty,
            format_bet_log_func=self.betting.format_bet_log,
            get_balance_for_log_func=self.get_balance_for_log,
            get_db_connection_func=self.get_db_connection,
            is_forbidden_access_error_func=self.is_forbidden_access_error,
            reload_page_and_refresh_token_func=self.reload_page_and_refresh_token,
            advance_step_after_set_error_func=self.advance_step_after_set_error,
            update_runtime_snapshot_func=self.update_runtime_snapshot,
            queue_telegram_notification_func=self.queue_telegram_notification,
        )

    async def place_bets(self, page, bet_targets, amount: float, allow_refresh_retry: bool = True) -> bool:
        """Разместить несколько ставок в одном HTTP-запросе на один игровой раунд."""

        return await _betting_place_bets(
            page,
            bet_targets,
            amount,
            allow_refresh_retry=allow_refresh_retry,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            get_jwt_token_func=self.get_jwt_token,
            validate_base_bet_func=self.validate_base_bet,
            calculate_roi_func=self.betting.calculate_roi,
            format_outcome_pretty_func=self.betting.format_outcome_pretty,
            format_bet_log_func=self.betting.format_bet_log,
            get_balance_for_log_func=self.get_balance_for_log,
            get_db_connection_func=self.get_db_connection,
            is_forbidden_access_error_func=self.is_forbidden_access_error,
            reload_page_and_refresh_token_func=self.reload_page_and_refresh_token,
            advance_step_after_set_error_func=self.advance_step_after_set_error,
            update_runtime_snapshot_func=self.update_runtime_snapshot,
            queue_telegram_notification_func=self.queue_telegram_notification,
        )

    async def place_bets_2(self, page, bet_targets, amount: float, allow_refresh_retry: bool = True) -> bool:
        """Разместить ставки для второго слота, используя betting_state_2 и current_strategy_2."""

        ctx = self.runtime_context
        if ctx.betting_state_2 is None or ctx.current_strategy_2 is None:
            return False

        orig_state = ctx.betting_state
        orig_strategy = ctx.current_strategy

        def _balance_for_log_2() -> str:
            """Вернуть real balance для логов слота 2, читая account_balance из главного состояния."""
            ab = orig_state.get("account_balance")
            if ab is not None:
                suffix = " !" if self.accounting.is_account_balance_stale() else ""
                return f"{ab:.0f}р{suffix}"
            return f"{(ctx.betting_state_2 or {}).get('session_balance', 0):.0f}р"

        # Синхронизировать account_balance из слота 1 в слот 2, чтобы проверки баланса
        # и логика возобновления паузы внутри _betting_place_bets работали корректно.
        ab = orig_state.get("account_balance")
        if ab is not None:
            ctx.betting_state_2["account_balance"] = ab

        ctx.betting_state = ctx.betting_state_2
        ctx.current_strategy = ctx.current_strategy_2

        def _update_runtime_snapshot_slot1_context(
            event_type: str = "heartbeat",
            extra: dict | None = None,
        ) -> None:
            """Обновить top-level snapshot под slot1-контекстом во время работы slot2."""

            slot2_state = ctx.betting_state
            slot2_strategy = ctx.current_strategy
            ctx.betting_state = orig_state
            ctx.current_strategy = orig_strategy
            try:
                self.update_runtime_snapshot(event_type=event_type, extra=extra)
            finally:
                ctx.betting_state = slot2_state
                ctx.current_strategy = slot2_strategy

        result = False
        try:
            result = await _betting_place_bets(
                page,
                bet_targets,
                amount,
                allow_refresh_retry=allow_refresh_retry,
                runtime_context=ctx,
                runtime_config=self.runtime_config,
                get_jwt_token_func=self.get_jwt_token,
                validate_base_bet_func=self.validate_base_bet,
                calculate_roi_func=self.calculate_roi_2,
                format_outcome_pretty_func=self.betting.format_outcome_pretty,
                format_bet_log_func=self.betting.format_bet_log,
                get_balance_for_log_func=_balance_for_log_2,
                get_db_connection_func=self.get_db_connection,
                is_forbidden_access_error_func=self.is_forbidden_access_error,
                reload_page_and_refresh_token_func=self.reload_page_and_refresh_token,
                advance_step_after_set_error_func=self.advance_step_2_after_set_error,
                update_runtime_snapshot_func=_update_runtime_snapshot_slot1_context,
                queue_telegram_notification_func=self.queue_telegram_notification,
            )
        finally:
            ctx.betting_state = orig_state
            ctx.current_strategy = orig_strategy
        # Зарегистрировать падение баланса от слота 2 в главном betting_state,
        # чтобы accounting не трактовал его как внешний вывод.
        if result:
            orig_state["pending_expected_bet_drop"] = (
                float(orig_state.get("pending_expected_bet_drop", 0.0) or 0.0) + amount
            )
        return result

    def wire_ws_logging(self, page) -> None:
        """Подключить websocket события страницы к accounting и betting обработчикам."""

        self.infrastructure.wire_ws_logging(
            page,
            update_runtime_snapshot_func=self.update_runtime_snapshot,
            update_balance_from_accounting_payload_func=self.update_balance_from_accounting_payload,
            process_betting_round_func=self.process_betting_round,
            schedule_background_task_func=self.schedule_background_task,
        )

    def schedule_background_task(self, coroutine, *, description: str):
        """Create a supervised background task and surface failures in runtime events."""

        task = asyncio.create_task(coroutine)
        self.runtime_context.register_background_task(task)

        def _handle_completion(completed_task) -> None:
            if completed_task.cancelled():
                return
            exc = completed_task.exception()
            if exc is None:
                return
            print(f"[ASYNC ERROR] {description}: {exc}", flush=True)
            self.update_runtime_snapshot(
                "background_task_error",
                {
                    "background_task": description,
                    "background_task_error": str(exc)[:300],
                },
            )

        task.add_done_callback(_handle_completion)
        return task

    async def monitor_accounting_ws_health(self, page) -> None:
        """Запустить мониторинг accounting websocket и stale-balance условий."""

        await self.accounting.monitor_accounting_ws_health(
            page,
            reload_page_for_accounting_recovery_func=self.reload_page_for_accounting_recovery,
        )

    def calculate_roi(self) -> float:
        """Вернуть текущий ROI сессии через betting-service."""

        return self.betting.calculate_roi()

    def calculate_roi_2(self) -> float:
        """Вернуть текущий ROI второго слота."""

        return self.betting.calculate_roi_2()

    def calculate_bet_amount_2(self) -> float:
        """Рассчитать размер следующей ставки по второй стратегии."""

        return self.betting.calculate_bet_amount_2()

    def get_accounting_age_seconds(self, reference_key: str) -> float | None:
        """Вернуть возраст accounting timestamp-поля по его ключу."""

        return self.accounting.get_accounting_age_seconds(reference_key)

    def is_account_balance_stale(self) -> bool:
        """Проверить, считается ли real balance устаревшим."""

        return self.accounting.is_account_balance_stale()

    def record_accounting_rejection(self, reason: str, payload_preview: str | None = None) -> None:
        """Зафиксировать причину отклонения accounting-сообщения."""

        self.accounting.record_accounting_rejection(reason, payload_preview)

    def send_telegram_notification_sync(self, title: str, message: str) -> None:
        """Немедленно отправить Telegram-уведомление с текущей runtime-конфигурацией."""

        _notifications_send_telegram_notification_sync(self.runtime_config.telegram, title, message)

    def queue_telegram_notification(self, title: str, message: str, dedup_key: str, enabled: bool = True) -> None:
        """Поставить Telegram-уведомление в очередь с дедупликацией по ключу."""

        _notifications_queue_telegram_notification(
            title=title,
            message=message,
            dedup_key=dedup_key,
            enabled=enabled,
            telegram_config=self.runtime_config.telegram,
        )

    def get_balance_for_log(self) -> str:
        """Вернуть real balance в строковом виде для пользовательских логов."""

        return self.accounting.get_balance_for_log()

    def update_balance_from_accounting_payload(self, payload: object) -> None:
        """Обработать accounting payload и обновить runtime snapshot при изменениях."""

        self.accounting.update_balance_from_accounting_payload(
            payload,
            format_ws_payload_func=self.format_ws_payload,
            update_runtime_snapshot_func=self.update_runtime_snapshot,
            queue_telegram_notification_func=self.queue_telegram_notification,
        )

    def print_session_stats(self, checkpoint: int = 0) -> None:
        """Вывести сводную статистику текущей betting-сессии."""

        self.betting.print_session_stats(checkpoint)

    def print_dice_stats_20(self) -> None:
        """Вывести накопительную статистику комбинаций на очередной 20-й ставке."""

        self.betting.print_dice_stats_20()

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
        """Собрать форматированную строку лога ставки через betting-service."""

        return self.betting.format_bet_log(
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
        )

    def format_outcome_pretty(self, outcome: str, specifier: str = "") -> str:
        """Преобразовать цель ставки в короткий читаемый формат."""

        return self.betting.format_outcome_pretty(outcome, specifier)

    async def process_betting_round(self, page, payload: object) -> None:
        """Обработать target websocket payload как завершенный betting round."""

        plain_like_terminal_logs = (
            self.runtime_config.logging.terminal_plain_logs or self.runtime_config.logging.terminal_json_logs
        )

        await _betting_process_betting_round(
            page,
            payload,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            format_ws_payload_func=self.format_ws_payload,
            get_db_connection_func=self.get_db_connection,
            format_round_result_pretty_func=(
                _format_round_result_plain if plain_like_terminal_logs else _format_round_result_pretty
            ),
            format_outcome_pretty_func=self.betting.format_outcome_pretty,
            format_bet_log_func=self.betting.format_bet_log,
            get_balance_for_log_func=self.get_balance_for_log,
            calculate_roi_func=self.betting.calculate_roi,
            update_runtime_snapshot_func=self.update_runtime_snapshot,
            print_session_stats_func=self.betting.print_session_stats,
            print_dice_stats_20_func=self.betting.print_dice_stats_20,
            update_dynamic_bet_func=self.betting.update_dynamic_bet,
            generate_random_bet_func=self.betting.generate_random_bet,
            calculate_bet_amount_func=self.betting.calculate_bet_amount,
            place_bet_func=self.place_bet,
            place_bets_func=self.place_bets,
            calculate_bet_amount_2_func=self.betting.calculate_bet_amount_2 if self.runtime_config.betting.secondary_enabled else None,
            place_bets_2_func=self.place_bets_2 if self.runtime_config.betting.secondary_enabled else None,
        )

    def analyze_recent_bets_stats(self) -> dict:
        """Собрать статистику recent_bets через betting-service."""

        return self.betting.analyze_recent_bets_stats()

    def analyze_all_results_frequency(self) -> dict:
        """Посчитать частоты комбинаций по historical game_results."""

        return self.betting.analyze_all_results_frequency()

    def get_best_combination(self, stats: dict | None = None) -> tuple[str, str]:
        """Выбрать оптимальную комбинацию для dynamic betting режима."""

        return self.betting.get_best_combination(stats)

    def update_dynamic_bet(self) -> None:
        """Обновить текущую цель ставки по правилам dynamic betting."""

        self.betting.update_dynamic_bet()

    def generate_random_bet(self) -> tuple[str, str]:
        """Сгенерировать fallback-ставку после затяжной серии проигрышей."""

        return self.betting.generate_random_bet()

    def calculate_bet_amount(self) -> float:
        """Рассчитать размер следующей ставки по активной стратегии."""

        return self.betting.calculate_bet_amount()