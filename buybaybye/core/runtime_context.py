"""Изменяемое состояние рантайма, разделяемое между runtime-сервисами."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from buybaybye.core.runtime_config import BetTarget
from buybaybye.core.runtime_state import RuntimeBettingState


@dataclass(slots=True)
class RuntimeContext:
    """Хранит изменяемое состояние рантайма во время активной сессии."""

    loaded_strategies: dict = field(default_factory=dict)
    current_strategy: dict | None = None
    betting_state: RuntimeBettingState | None = None
    jwt_token: str | None = None
    active_page: Any | None = None
    page_reload_lock: asyncio.Lock | None = None
    round_processing_lock: asyncio.Lock | None = None
    background_tasks: set[asyncio.Task] = field(default_factory=set)
    active_accounting_ws_token: int = 0
    accounting_ws_token_counter: int = 0
    configured_bet_targets: tuple[BetTarget, ...] = field(default_factory=lambda: (BetTarget("red", "5"),))
    bet_mode_outcome: str = "red"
    bet_mode_specifier: str = "5"
    # Второй слот ставок (STRATEGY_2 / BASE_BET_2 / BET_TARGETS_2)
    current_strategy_2: dict | None = None
    betting_state_2: RuntimeBettingState | None = None
    configured_bet_targets_2: tuple[BetTarget, ...] = field(default_factory=tuple)
    bet_mode_outcome_2: str = ""
    bet_mode_specifier_2: str = ""

    def ensure_page_reload_lock(self) -> asyncio.Lock:
        """Вернуть лениво создаваемый lock для сериализации page reload."""

        if self.page_reload_lock is None:
            self.page_reload_lock = asyncio.Lock()
        return self.page_reload_lock

    def ensure_round_processing_lock(self) -> asyncio.Lock:
        if self.round_processing_lock is None:
            self.round_processing_lock = asyncio.Lock()
        return self.round_processing_lock

    def register_background_task(self, task: asyncio.Task) -> None:
        self.background_tasks.add(task)
        task.add_done_callback(lambda completed_task: self.background_tasks.discard(completed_task))

    def issue_accounting_ws_token(self) -> int:
        self.accounting_ws_token_counter += 1
        self.active_accounting_ws_token = self.accounting_ws_token_counter
        return self.active_accounting_ws_token

    def is_active_accounting_ws_token(self, token: int) -> bool:
        return token == self.active_accounting_ws_token

    async def cancel_background_tasks(self) -> None:
        if not self.background_tasks:
            return
        tasks = list(self.background_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.background_tasks.clear()

    def get_current_bet_target(self) -> tuple[str, str]:
        return self.bet_mode_outcome, self.bet_mode_specifier

    def get_configured_bet_targets(self) -> tuple[BetTarget, ...]:
        return self.configured_bet_targets

    def get_configured_target_tokens(self) -> tuple[str, ...]:
        return tuple(target.token for target in self.configured_bet_targets)

    def get_current_bet_target_2(self) -> tuple[str, str]:
        return self.bet_mode_outcome_2, self.bet_mode_specifier_2

    def get_configured_bet_targets_2(self) -> tuple[BetTarget, ...]:
        return self.configured_bet_targets_2

    def get_configured_target_tokens_2(self) -> tuple[str, ...]:
        return tuple(target.token for target in self.configured_bet_targets_2)

    def set_current_bet_target(self, outcome: str, specifier: str) -> None:
        self.bet_mode_outcome = outcome
        self.bet_mode_specifier = specifier

    def set_current_bet_target_2(self, outcome: str, specifier: str) -> None:
        self.bet_mode_outcome_2 = outcome
        self.bet_mode_specifier_2 = specifier

    def get_max_strategy_steps(self, default: int = 15) -> int:
        if not self.current_strategy:
            return default
        return len(self.current_strategy.get("coefficients", [1]))


def create_runtime_context(
    *,
    configured_bet_targets: tuple[BetTarget, ...],
    bet_mode_outcome: str,
    bet_mode_specifier: str,
) -> RuntimeContext:
    """Создать начальный runtime context из config-derived параметров ставки."""

    return RuntimeContext(
        configured_bet_targets=configured_bet_targets,
        bet_mode_outcome=bet_mode_outcome,
        bet_mode_specifier=bet_mode_specifier,
    )