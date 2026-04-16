"""Изменяемое состояние рантайма, разделяемое между runtime-сервисами."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from buybaybye.core.runtime_config import BetTarget


@dataclass(slots=True)
class RuntimeContext:
    """Хранит изменяемое состояние рантайма во время активной сессии."""

    loaded_strategies: dict = field(default_factory=dict)
    current_strategy: dict | None = None
    betting_state: dict = field(default_factory=dict)
    jwt_token: str | None = None
    page_reload_lock: asyncio.Lock | None = None
    configured_bet_targets: tuple[BetTarget, ...] = field(default_factory=lambda: (BetTarget("red", "5"),))
    bet_mode_outcome: str = "red"
    bet_mode_specifier: str = "5"

    def ensure_page_reload_lock(self) -> asyncio.Lock:
        """Вернуть лениво создаваемый lock для сериализации page reload."""

        if self.page_reload_lock is None:
            self.page_reload_lock = asyncio.Lock()
        return self.page_reload_lock

    def get_current_bet_target(self) -> tuple[str, str]:
        return self.bet_mode_outcome, self.bet_mode_specifier

    def get_configured_bet_targets(self) -> tuple[BetTarget, ...]:
        return self.configured_bet_targets

    def get_configured_target_tokens(self) -> tuple[str, ...]:
        return tuple(target.token for target in self.configured_bet_targets)

    def set_current_bet_target(self, outcome: str, specifier: str) -> None:
        self.bet_mode_outcome = outcome
        self.bet_mode_specifier = specifier

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