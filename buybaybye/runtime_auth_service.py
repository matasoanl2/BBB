from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from buybaybye.jwt_capture import handle_request as _jwt_handle_request
from buybaybye.jwt_capture import handle_response as _jwt_handle_response
from buybaybye.jwt_capture import handle_response_async as _jwt_handle_response_async
from buybaybye.jwt_capture import subscribe_jwt_search_to_page as _jwt_subscribe_jwt_search_to_page
from buybaybye.notifications import is_telegram_chat_id_mode as _notifications_is_telegram_chat_id_mode
from buybaybye.notifications import run_telegram_chat_id_helper as _notifications_run_telegram_chat_id_helper
from buybaybye.runtime_config import RuntimeConfig
from buybaybye.runtime_context import RuntimeContext


class AuthRuntimeService:
    def __init__(self, runtime_context: RuntimeContext, runtime_config: RuntimeConfig):
        self.runtime_context = runtime_context
        self.runtime_config = runtime_config

    def set_jwt_token(self, token: str) -> None:
        self.runtime_context.jwt_token = token

    def get_jwt_token(self) -> str | None:
        return self.runtime_context.jwt_token

    def is_telegram_chat_id_mode(self, argv: Sequence[str]) -> bool:
        return _notifications_is_telegram_chat_id_mode(argv)

    async def run_telegram_chat_id_helper(self) -> None:
        await _notifications_run_telegram_chat_id_helper(self.runtime_config.telegram)

    def handle_response(self, response) -> None:
        _jwt_handle_response(response, handle_response_async_func=self.handle_response_async)

    async def handle_response_async(self, response) -> None:
        await _jwt_handle_response_async(
            response,
            set_jwt_token_func=self.set_jwt_token,
            color_cyan=self.runtime_config.colors.cyan,
            color_reset=self.runtime_config.colors.reset,
        )

    def handle_request(self, request) -> None:
        _jwt_handle_request(
            request,
            set_jwt_token_func=self.set_jwt_token,
            color_cyan=self.runtime_config.colors.cyan,
            color_reset=self.runtime_config.colors.reset,
        )

    def subscribe_jwt_search_to_page(self, page) -> None:
        _jwt_subscribe_jwt_search_to_page(page, response_handler=self.handle_response, request_handler=self.handle_request)

    def is_forbidden_access_error(self, status_code: int, response_text: str) -> bool:
        if status_code != 403:
            return False

        try:
            payload = json.loads(response_text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return False

        if not isinstance(payload, dict):
            return False

        error = payload.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        return payload.get("code") == 403 and payload.get("status") == "FORBIDDEN" and message == "Доступ запрещён"

    async def reload_page_and_refresh_token(self, page) -> bool:
        async with self.runtime_context.ensure_page_reload_lock():
            old_token = self.runtime_context.jwt_token
            self.runtime_context.jwt_token = None
            print("[AUTH] Получен 403 FORBIDDEN, перезагружаем страницу и обновляем JWT токен...", flush=True)

            try:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                print(f"[AUTH] Ошибка перезагрузки страницы при обновлении токена: {exc}", flush=True)
                return False

            deadline = asyncio.get_running_loop().time() + 20.0
            while asyncio.get_running_loop().time() < deadline:
                if self.runtime_context.jwt_token:
                    token_changed = old_token is None or self.runtime_context.jwt_token != old_token
                    change_note = "новый" if token_changed else "повторно получен"
                    print(f"[AUTH] JWT токен {change_note} после перезагрузки страницы.", flush=True)
                    return True
                await asyncio.sleep(0.25)

            print("[AUTH] JWT токен не был получен после перезагрузки страницы.", flush=True)
            return False