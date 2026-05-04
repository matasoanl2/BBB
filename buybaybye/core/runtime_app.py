"""Оркестрация жизненного цикла runtime-приложения."""

from __future__ import annotations

import asyncio
import sys

from patchright.async_api import async_playwright, Error as PatchrightError

from buybaybye.core.runtime_bootstrap import build_runtime_status_line, get_browser_launch_args, print_strategy_startup_info, wait_for_exit_signal
from buybaybye.core.runtime_config import RuntimeConfig
from buybaybye.core.runtime_context import RuntimeContext
from buybaybye.core.runtime_state import build_runtime_betting_state
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

        self.runtime_context.betting_state = build_runtime_betting_state(
            strategy=None,
            bet_mode_outcome=self.runtime_context.bet_mode_outcome,
            bet_mode_specifier=self.runtime_context.bet_mode_specifier,
        )
        self.services.ensure_runtime_schema()

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

        if (
            self.runtime_config.dynamic_betting.enabled
            and len(configured_targets) > 1
            and not self.runtime_config.dynamic_betting.multi_target_enabled
        ):
            print(
                "[WARNING] Задано несколько целей в BET_TARGETS: dynamic-пересчет multi-target отключен (DYNAMIC_MULTI_TARGET_ENABLED=0).",
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

        # Инициализация второго слота ставок (если STRATEGY_2 задан)
        if betting_config.secondary_enabled:
            if betting_config.configured_targets_error_2:
                print(betting_config.configured_targets_error_2, flush=True)
                sys.exit(1)
            strategy_name_2 = betting_config.strategy_name_2
            if strategy_name_2 not in self.runtime_context.loaded_strategies:
                print(f"[ERROR] Стратегия STRATEGY_2='{strategy_name_2}' не найдена. Доступные:", flush=True)
                for name, strategy in self.runtime_context.loaded_strategies.items():
                    print(f"  - {name}: {strategy['description']}", flush=True)
                sys.exit(1)
            self.runtime_context.current_strategy_2 = self.runtime_context.loaded_strategies[strategy_name_2]
            default_target_2 = betting_config.configured_targets_2[0]
            self.runtime_context.configured_bet_targets_2 = betting_config.configured_targets_2
            self.runtime_context.bet_mode_outcome_2 = default_target_2.outcome
            self.runtime_context.bet_mode_specifier_2 = default_target_2.specifier or "5"
            self.runtime_context.betting_state_2 = init_betting_state(
                self.runtime_context.current_strategy_2,
                self.runtime_context.bet_mode_outcome_2,
                self.runtime_context.bet_mode_specifier_2,
            )
            print(
                f"[STRATEGY-2] Второй слот: {self.runtime_context.current_strategy_2['name']} | "
                f"цели: {betting_config.configured_targets_raw_2} | базовая ставка: {betting_config.base_bet_2}р",
                flush=True,
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
                args=get_browser_launch_args(runtime_config=self.runtime_config),
            )
        else:
            browser = await playwright.chromium.launch(
                headless=self.runtime_config.browser.headless,
                args=get_browser_launch_args(runtime_config=self.runtime_config),
            )
            context = await browser.new_context()

        if (
            self.runtime_config.browser.block_video_stream
            or self.runtime_config.browser.block_images
            or self.runtime_config.browser.block_fonts
        ):
            blocked_video_url_parts = (".m3u8", ".mp4", ".webm", ".m4s", ".ts")
            blocked_image_url_parts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
            blocked_font_url_parts = (".woff", ".woff2", ".ttf", ".otf")

            async def _block_video_stream(route) -> None:
                request = route.request
                request_url = request.url.lower()
                resource_type = request.resource_type

                if self.runtime_config.browser.block_video_stream and (
                    resource_type == "media" or any(part in request_url for part in blocked_video_url_parts)
                ):
                    await route.abort()
                    return

                if self.runtime_config.browser.block_images and (
                    resource_type == "image" or any(part in request_url for part in blocked_image_url_parts)
                ):
                    await route.abort()
                    return

                if self.runtime_config.browser.block_fonts and (
                    resource_type == "font" or any(part in request_url for part in blocked_font_url_parts)
                ):
                    await route.abort()
                    return

                await route.continue_()

            await context.route("**/*", _block_video_stream)
            print(
                "[INFO] Browser resource blocking: "
                f"video={'on' if self.runtime_config.browser.block_video_stream else 'off'}, "
                f"images={'on' if self.runtime_config.browser.block_images else 'off'}, "
                f"fonts={'on' if self.runtime_config.browser.block_fonts else 'off'}.",
                flush=True,
            )

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
            self.runtime_context.active_page = page

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
                accounting_monitor_task = self.services.schedule_background_task(
                    self.services.monitor_accounting_ws_health(page),
                    description="accounting monitor",
                )

            print(
                build_runtime_status_line(
                    runtime_context=self.runtime_context,
                    runtime_config=self.runtime_config,
                ),
                flush=True,
            )
            if accounting_monitor_task is None:
                await wait_for_exit_signal()
            else:
                exit_signal_task = asyncio.create_task(wait_for_exit_signal())
                done, pending = await asyncio.wait(
                    {accounting_monitor_task, exit_signal_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for pending_task in pending:
                    pending_task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                if accounting_monitor_task in done:
                    monitor_error = accounting_monitor_task.exception()
                    if monitor_error is not None:
                        raise monitor_error
                    active_page = self.runtime_context.active_page
                    if active_page is not None and active_page.is_closed():
                        pass
                    else:
                        raise RuntimeError("[ACCOUNTING] monitor_accounting_ws_health завершился неожиданно.")
        finally:
            if accounting_monitor_task is not None:
                accounting_monitor_task.cancel()
                try:
                    await accounting_monitor_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            await self.runtime_context.cancel_background_tasks()
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