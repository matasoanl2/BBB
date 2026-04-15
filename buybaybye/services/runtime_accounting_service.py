"""Фасад runtime-слоя для accounting-домена."""

from __future__ import annotations

from buybaybye.modules.accounting import get_accounting_age_seconds as _accounting_get_accounting_age_seconds
from buybaybye.modules.accounting import get_balance_for_log as _accounting_get_balance_for_log
from buybaybye.modules.accounting import is_account_balance_stale as _accounting_is_account_balance_stale
from buybaybye.modules.accounting import monitor_accounting_ws_health as _accounting_monitor_accounting_ws_health
from buybaybye.modules.accounting import record_accounting_rejection as _accounting_record_accounting_rejection
from buybaybye.modules.accounting import reload_page_for_accounting_recovery as _accounting_reload_page_for_accounting_recovery
from buybaybye.modules.accounting import update_balance_from_accounting_payload as _accounting_update_balance_from_accounting_payload
from buybaybye.core.runtime_config import RuntimeConfig
from buybaybye.core.runtime_context import RuntimeContext


class AccountingRuntimeService:
    """Предоставляет операции accounting и восстановления баланса для рантайма."""

    def __init__(self, runtime_context: RuntimeContext, runtime_config: RuntimeConfig):
        """Инициализировать accounting-service общим runtime state и конфигурацией."""

        self.runtime_context = runtime_context
        self.runtime_config = runtime_config

    def get_accounting_age_seconds(self, reference_key: str) -> float | None:
        """Вернуть возраст accounting timestamp-поля из shared state."""

        return _accounting_get_accounting_age_seconds(runtime_context=self.runtime_context, reference_key=reference_key)

    def is_account_balance_stale(self) -> bool:
        """Проверить, считается ли real balance устаревшим по правилам accounting-монитора."""

        return _accounting_is_account_balance_stale(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            get_accounting_age_seconds_func=self.get_accounting_age_seconds,
        )

    def record_accounting_rejection(self, reason: str, payload_preview: str | None = None) -> None:
        """Зафиксировать причину отклонения accounting-сообщения."""

        _accounting_record_accounting_rejection(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            reason=reason,
            payload_preview=payload_preview,
        )

    def get_balance_for_log(self) -> str:
        """Вернуть real balance в строковом виде для логов runtime-а."""

        return _accounting_get_balance_for_log(
            runtime_context=self.runtime_context,
            is_account_balance_stale_func=self.is_account_balance_stale,
        )

    def update_balance_from_accounting_payload(
        self,
        payload: object,
        *,
        format_ws_payload_func,
        update_runtime_snapshot_func,
        queue_telegram_notification_func,
    ) -> None:
        """Обработать accounting payload через нижележащий subsystem и переданные callbacks."""

        _accounting_update_balance_from_accounting_payload(
            payload,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            format_ws_payload_func=format_ws_payload_func,
            record_accounting_rejection_func=self.record_accounting_rejection,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            queue_telegram_notification_func=queue_telegram_notification_func,
        )

    async def reload_page_for_accounting_recovery(
        self,
        page,
        reason: str,
        *,
        get_balance_for_log_func,
        queue_telegram_notification_func,
        update_runtime_snapshot_func,
    ) -> bool:
        """Выполнить recovery accounting-канала через reload страницы под общим lock."""

        async with self.runtime_context.ensure_page_reload_lock():
            return await _accounting_reload_page_for_accounting_recovery(
                page,
                reason,
                runtime_context=self.runtime_context,
                runtime_config=self.runtime_config,
                get_balance_for_log_func=get_balance_for_log_func,
                queue_telegram_notification_func=queue_telegram_notification_func,
                update_runtime_snapshot_func=update_runtime_snapshot_func,
            )

    async def monitor_accounting_ws_health(self, page, *, reload_page_for_accounting_recovery_func) -> None:
        """Запустить цикл мониторинга accounting websocket и stale-balance условий."""

        await _accounting_monitor_accounting_ws_health(
            page,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            get_accounting_age_seconds_func=self.get_accounting_age_seconds,
            is_account_balance_stale_func=self.is_account_balance_stale,
            reload_page_for_accounting_recovery_func=reload_page_for_accounting_recovery_func,
        )