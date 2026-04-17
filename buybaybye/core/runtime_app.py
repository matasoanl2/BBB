"""Оркестрация жизненного цикла runtime-приложения."""

from __future__ import annotations

import asyncio
import sys

from patchright.async_api import async_playwright, Error as PatchrightError

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

    def _build_shared_runtime_state(self) -> dict:
        """Создать базовую форму runtime state, безопасную для collector и bettor."""

        return {
            "current_step": 0,
            "consecutive_losses": 0,
            "session_balance": 0.0,
            "account_balance": None,
            "account_balance_type": None,
            "account_balance_updated_at": None,
            "last_accounting_ws_message_at": None,
            "last_accounting_ws_opened_at": None,
            "last_accounting_ws_closed_at": None,
            "accounting_ws_connected": False,
            "last_accounting_rejection_reason": None,
            "last_accounting_recovery_at": None,
            "accounting_recovery_attempts": 0,
            "pending_expected_bet_drop": 0.0,
            "pending_expected_settlement_credit": 0.0,
            "external_deposits_total": 0.0,
            "external_withdrawals_total": 0.0,
            "low_balance_pause_active": False,
            "low_balance_pause_required_balance": 0.0,
            "low_balance_pause_started_at": None,
            "low_balance_pause_targets": [],
            "last_bet_amount": 0.0,
            "last_set_amount": 0.0,
            "last_set_status": None,
            "last_set_error": None,
            "total_bet_amount": 0.0,
            "total_profit": 0.0,
            "total_bets_placed": 0,
            "total_bet_rounds": 0,
            "last_bet_round_number": 0,
            "last_round_result": None,
            "last_round_game_id": None,
            "last_round_status": None,
            "last_round_timestamp": None,
            "last_round_player_name": None,
            "last_round_position": None,
            "combo_stats": {
                "red_1": 0, "red_2": 0, "red_3": 0, "red_4": 0, "red_5": 0, "red_6": 0,
                "yellow_1": 0, "yellow_2": 0, "yellow_3": 0, "yellow_4": 0, "yellow_5": 0, "yellow_6": 0,
            },
            "double_stats": {"doubles": 0, "no_doubles": 0},
            "reported_20_rounds": [],
            "recent_bets": [],
            "pending_bets": [],
            "dynamic_outcome": self.runtime_context.bet_mode_outcome,
            "dynamic_specifier": self.runtime_context.bet_mode_specifier,
            "strategy": None,
        }

    def initialize_runtime_state(self) -> None:
        """Подготовить стратегии, betting state и startup snapshot перед запуском."""

        self.runtime_context.betting_state = self._build_shared_runtime_state()

        if self.runtime_config.role.uses_persistent_browser_profile:
            self.runtime_config.browser.session_dir.mkdir(parents=True, exist_ok=True)

        if not self.runtime_config.betting.enabled:
            if self.runtime_config.betting.requested_enabled and not self.runtime_config.role.can_place_bets:
                print(
                    "[WARNING] RUNTIME_ROLE=collector: BET_MODE принудительно отключен, ставки размещаться не будут.",
                    flush=True,
                )
            self.services.update_runtime_snapshot("startup")
            return

        self.runtime_context.loaded_strategies = load_strategies(
            self.runtime_config.browser.strategies_dir,
            self.runtime_config.betting.base_bet,
        )

        if not self.services.validate_base_bet(self.runtime_config.betting.base_bet):
            print(f"[ERROR] BASE_BET ({self.runtime_config.betting.base_bet}) должна делиться на 10 нацело", flush=True)
            sys.exit(1)

        betting_config = self.runtime_config.betting
        configured_targets = self.runtime_context.get_configured_bet_targets()
        if betting_config.configured_targets_error:
            print(betting_config.configured_targets_error, flush=True)
            sys.exit(1)

        if not configured_targets:
            print("[ERROR] Не удалось определить ни одной цели ставки.", flush=True)
            sys.exit(1)

        if self.runtime_config.dynamic_betting.enabled and len(configured_targets) > 1:
            print(
                "[WARNING] Задано несколько целей в BET_TARGETS, поэтому DYNAMIC_BET_MODE будет проигнорирован для этого запуска.",
                flush=True,
            )

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
        browser = None
        if self.runtime_config.role.uses_persistent_browser_profile:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.runtime_config.browser.session_dir),
                headless=self.runtime_config.browser.headless,
                args=get_browser_launch_args(),
            )
        else:
            browser = await playwright.chromium.launch(
                headless=self.runtime_config.browser.headless,
                args=get_browser_launch_args(),
            )
            context = await browser.new_context()
        accounting_monitor_task = None

        try:
            initial_pages = list(context.pages)
            for existing_page in initial_pages:
                self.services.wire_ws_logging(existing_page)
                self.services.subscribe_jwt_search_to_page(existing_page)

            context.on("page", self.services.wire_ws_logging)
            context.on("page", self.services.subscribe_jwt_search_to_page)

            page = context.pages[0] if context.pages else await context.new_page()
            if page not in initial_pages:
                self.services.wire_ws_logging(page)
                self.services.subscribe_jwt_search_to_page(page)

            print("[DEBUG] Поиск JWT токена в ответах...", flush=True)
            _goto_delay = 5
            while True:
                try:
                    await page.goto("https://betboom.ru/game/nardsgame")
                    break
                except PatchrightError as e:
                    if "ERR_NAME_NOT_RESOLVED" in str(e) or "ERR_INTERNET_DISCONNECTED" in str(e) or "ERR_NETWORK_CHANGED" in str(e):
                        print(f"[WARN] Нет сети, повтор через {_goto_delay}с: {e}", flush=True)
                        await asyncio.sleep(_goto_delay)
                        _goto_delay = min(_goto_delay * 2, 60)
                    else:
                        raise
            if self.runtime_config.betting.enabled:
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
            if browser is not None:
                await browser.close()
            await playwright.stop()

        if self.runtime_config.betting.enabled and self.runtime_context.betting_state:
            self.services.print_session_stats()

        if self.runtime_config.role.uses_persistent_browser_profile:
            print("Контекст закрыт, профиль записан. Следующий запуск продолжит ту же сессию.", flush=True)
        else:
            print("Контекст закрыт, collector-роль работала без сохранения браузерного профиля.", flush=True)