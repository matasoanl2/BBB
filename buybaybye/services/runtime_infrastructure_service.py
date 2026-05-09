"""Фасад runtime-слоя для infrastructure-домена."""

from __future__ import annotations

from buybaybye.modules.browser_ws import wire_ws_logging as _browser_wire_ws_logging
from buybaybye.modules.db import ensure_runtime_schema as _db_ensure_runtime_schema
from buybaybye.modules.db import get_db_connection as _db_get_db_connection
from buybaybye.modules.db import save_target_ws_message as _db_save_target_ws_message
from buybaybye.core.runtime_config import RuntimeConfig
from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_snapshot import build_runtime_snapshot as _runtime_build_snapshot
from buybaybye.core.runtime_snapshot import update_runtime_snapshot as _runtime_update_snapshot


class InfrastructureRuntimeService:
    """Предоставляет операции базы данных, snapshot, форматирования payload и привязки websocket."""

    def __init__(self, runtime_context: RuntimeContext, runtime_config: RuntimeConfig):
        """Инициализировать infrastructure-service общим runtime state и конфигурацией."""

        self.runtime_context = runtime_context
        self.runtime_config = runtime_config

    def get_db_connection(self):
        """Создать подключение к рабочей PostgreSQL-базе рантайма."""

        return _db_get_db_connection(database_config=self.runtime_config.database)

    def ensure_runtime_schema(self) -> None:
        """Initialize runtime schema once before hot-path DB usage."""

        _db_ensure_runtime_schema(database_config=self.runtime_config.database)

    def format_ws_payload(self, payload: object) -> str:
        """Преобразовать websocket payload в строку для логов и хранения."""

        if isinstance(payload, bytes):
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                return payload.hex()
        return str(payload)

    def save_target_ws_message(self, payload: object) -> None:
        """Сохранить raw target websocket payload в базе данных."""

        _db_save_target_ws_message(
            payload_text=self.format_ws_payload(payload),
            get_db_connection_func=self.get_db_connection,
            debug_enabled=self.runtime_config.betting.debug_enabled,
        )

    def build_runtime_snapshot(self, *, event_type: str = "heartbeat", extra: dict | None = None, is_account_balance_stale_func) -> dict:
        """Собрать snapshot текущего runtime state для live dashboard и events."""

        return _runtime_build_snapshot(
            event_type=event_type,
            extra=extra,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            is_account_balance_stale_func=is_account_balance_stale_func,
        )

    def update_runtime_snapshot(self, *, snapshot: dict, event_type: str) -> None:
        """Сохранить runtime snapshot и отдельное runtime event в PostgreSQL."""

        _runtime_update_snapshot(
            get_db_connection_func=self.get_db_connection,
            snapshot=snapshot,
            event_type=event_type,
        )

    def wire_ws_logging(
        self,
        page,
        *,
        update_runtime_snapshot_func,
        update_balance_from_accounting_payload_func,
        process_betting_round_func,
        schedule_background_task_func,
    ) -> None:
        """Подключить websocket wiring страницы к accounting и betting обработчикам."""

        _browser_wire_ws_logging(
            page,
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            update_runtime_snapshot_func=update_runtime_snapshot_func,
            format_ws_payload_func=self.format_ws_payload,
            update_balance_from_accounting_payload_func=update_balance_from_accounting_payload_func,
            save_target_ws_message_func=self.save_target_ws_message,
            process_betting_round_func=process_betting_round_func,
            schedule_background_task_func=schedule_background_task_func,
        )