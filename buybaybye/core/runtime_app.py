"""Оркестрация жизненного цикла runtime-приложения."""

from __future__ import annotations

import asyncio
import sys

from patchright.async_api import async_playwright

from buybaybye.core.runtime_bootstrap import build_runtime_status_line, get_browser_launch_args, print_strategy_startup_info, wait_for_exit_signal
from buybaybye.core.runtime_config import RuntimeConfig
from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.services.runtime_services import RuntimeServices
from buybaybye.modules.strategies import init_betting_state, load_strategies


class RuntimeApp:
    """Управляет startup-валидацией, жизненным циклом браузера и корректным shutdown."""

    def __init__(self, runtime_config: RuntimeConfig, runtime_context: RuntimeContext, services: RuntimeServices):
        self.runtime_config = runtime_config
        self.runtime_context = runtime_context
        self.services = services

    def initialize_runtime_state(self) -> None:
        """Подготовить стратегии, betting state и startup snapshot перед запуском."""

        self.runtime_config.browser.session_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_context.loaded_strategies = load_strategies(
            self.runtime_config.browser.strategies_dir,
            self.runtime_config.betting.base_bet,
        )

        if not self.services.validate_base_bet(self.runtime_config.betting.base_bet):
            print(f"[ERROR] BASE_BET ({self.runtime_config.betting.base_bet}) должна делиться на 10 нацело", flush=True)
            sys.exit(1)

        if not self.runtime_config.betting.enabled:
            return

        strategy_name = self.runtime_config.betting.strategy_name
        if strategy_name not in self.runtime_context.loaded_strategies:
            print(f"[ERROR] Стратегия '{strategy_name}' не найдена. Доступные:", flush=True)
            for name, strategy in self.runtime_context.loaded_strategies.items():
                print(f"  - {name}: {strategy['description']}", flush=True)
            sys.exit(1)

        self.runtime_context.current_strategy = self.runtime_context.loaded_strategies[strategy_name]
        self.runtime_context.betting_state = init_betting_state(
            self.runtime_context.current_strategy,
            self.runtime_context.bet_mode_outcome,
            self.runtime_context.bet_mode_specifier,
        )
        self.services.update_runtime_snapshot("startup")
        print_strategy_startup_info(
            runtime_context=self.runtime_context,
            runtime_config=self.runtime_config,
            format_outcome_pretty_func=self.services.format_outcome_pretty,
        )

    async def run(self) -> None:
        """Запустить полный browser-backed runtime до выхода пользователя."""

        self.initialize_runtime_state()

        playwright = await async_playwright().start()
        self.runtime_context.page_reload_lock = asyncio.Lock()
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.runtime_config.browser.session_dir),
            headless=self.runtime_config.browser.headless,
            args=get_browser_launch_args(),
        )
        accounting_monitor_task = None

        try:
            for existing_page in context.pages:
                self.services.wire_ws_logging(existing_page)
                self.services.subscribe_jwt_search_to_page(existing_page)

            context.on("page", self.services.wire_ws_logging)
            context.on("page", self.services.subscribe_jwt_search_to_page)

            page = context.pages[0] if context.pages else await context.new_page()

            print("[DEBUG] Поиск JWT токена в ответах...", flush=True)
            await page.goto("https://betboom.ru/game/nardsgame")
            accounting_monitor_task = asyncio.create_task(self.services.monitor_accounting_ws_health(page))

            print(
                build_runtime_status_line(
                    runtime_context=self.runtime_context,
                    runtime_config=self.runtime_config,
                ),
                flush=True,
            )
            await wait_for_exit_signal()
        finally:
            if accounting_monitor_task is not None:
                accounting_monitor_task.cancel()
                try:
                    await accounting_monitor_task
                except asyncio.CancelledError:
                    pass
            await context.close()
            await playwright.stop()

        if self.runtime_config.betting.enabled and self.runtime_context.betting_state:
            self.services.print_session_stats()

        print("Контекст закрыт, профиль записан. Следующий запуск продолжит ту же сессию.", flush=True)