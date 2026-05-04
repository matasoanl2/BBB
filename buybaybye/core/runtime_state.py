"""Typed mutable runtime state shared across runtime services."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, fields
from typing import Any


@dataclass(slots=True)
class ReconciliationState:
    """State machine for expected and external accounting balance changes."""

    phase: str = "idle"
    pending_expected_bet_drop: float = 0.0
    pending_expected_settlement_credit: float = 0.0
    early_settlement_credit_buffer: float = 0.0
    early_bet_drop_debit_buffer: float = 0.0
    external_deposits_total: float = 0.0
    external_withdrawals_total: float = 0.0
    last_external_balance_change_type: str | None = None
    last_external_balance_change_amount: float = 0.0


@dataclass(slots=True)
class RuntimeBettingState:
    """Typed mutable state with dict-like compatibility for existing modules."""

    current_step: int = 0
    consecutive_losses: int = 0
    session_balance: float = 0.0
    account_balance: float | None = None
    account_balance_type: int | None = None
    account_balance_updated_at: str | None = None
    last_accounting_ws_message_at: str | None = None
    last_accounting_ws_opened_at: str | None = None
    last_accounting_ws_closed_at: str | None = None
    accounting_ws_connected: bool = False
    last_accounting_rejection_reason: str | None = None
    last_accounting_recovery_at: str | None = None
    last_accounting_recovery_attempted_at: str | None = None
    accounting_recovery_attempts: int = 0
    accounting_consecutive_page_crashes: int = 0
    pending_expected_bet_drop: float = 0.0
    pending_expected_settlement_credit: float = 0.0
    early_settlement_credit_buffer: float = 0.0
    early_bet_drop_debit_buffer: float = 0.0
    external_deposits_total: float = 0.0
    external_withdrawals_total: float = 0.0
    reconciliation_phase: str = "idle"
    last_external_balance_change_type: str | None = None
    last_external_balance_change_amount: float = 0.0
    low_balance_pause_active: bool = False
    low_balance_pause_required_balance: float = 0.0
    low_balance_pause_reason: str | None = None
    low_balance_pause_started_at: str | None = None
    low_balance_api_fail_at: str | None = None
    low_balance_pause_targets: list[str] = field(default_factory=list)
    target_balance_pause_last_check_at: str | None = None
    target_balance_pause_last_observed_balance: float | None = None
    last_bet_amount: float = 0.0
    last_set_amount: float = 0.0
    last_set_status: str | None = None
    last_set_error: str | None = None
    total_bet_amount: float = 0.0
    total_profit: float = 0.0
    total_bets_placed: int = 0
    total_bet_rounds: int = 0
    last_bet_round_number: int = 0
    last_round_result: str | None = None
    last_round_game_id: str | None = None
    last_round_status: str | None = None
    last_round_timestamp: str | None = None
    last_round_player_name: str | None = None
    last_round_position: str | None = None
    combo_stats: dict[str, int] = field(default_factory=lambda: {
        "red_1": 0,
        "red_2": 0,
        "red_3": 0,
        "red_4": 0,
        "red_5": 0,
        "red_6": 0,
        "yellow_1": 0,
        "yellow_2": 0,
        "yellow_3": 0,
        "yellow_4": 0,
        "yellow_5": 0,
        "yellow_6": 0,
    })
    double_stats: dict[str, int] = field(default_factory=lambda: {"doubles": 0, "no_doubles": 0})
    reported_20_rounds: list[int] = field(default_factory=list)
    recent_bets: list[dict[str, Any]] = field(default_factory=list)
    pending_bets: list[dict[str, Any]] = field(default_factory=list)
    dynamic_outcome: str = "red"
    dynamic_specifier: str = "5"
    dynamic_targets: list[str] = field(default_factory=list)
    dynamic_color_counts: dict[str, int] = field(default_factory=lambda: {"red": 0, "yellow": 0, "double": 0})
    strategy: dict[str, Any] | None = None
    reconciliation: ReconciliationState = field(default_factory=ReconciliationState)
    processed_round_game_ids: deque[str] = field(default_factory=lambda: deque(maxlen=512))

    def __post_init__(self) -> None:
        self._sync_reconciliation()

    def _sync_reconciliation(self) -> None:
        self.reconciliation.pending_expected_bet_drop = float(self.pending_expected_bet_drop or 0.0)
        self.reconciliation.pending_expected_settlement_credit = float(self.pending_expected_settlement_credit or 0.0)
        self.reconciliation.early_bet_drop_debit_buffer = float(self.early_bet_drop_debit_buffer or 0.0)
        self.reconciliation.external_deposits_total = float(self.external_deposits_total or 0.0)
        self.reconciliation.external_withdrawals_total = float(self.external_withdrawals_total or 0.0)
        self.reconciliation.phase = self.reconciliation_phase
        self.reconciliation.last_external_balance_change_type = self.last_external_balance_change_type
        self.reconciliation.last_external_balance_change_amount = float(self.last_external_balance_change_amount or 0.0)

    def mark_round_processed(self, game_id: str) -> None:
        if game_id and game_id not in self.processed_round_game_ids:
            self.processed_round_game_ids.append(game_id)

    def has_processed_round(self, game_id: str | None) -> bool:
        if not game_id:
            return False
        return game_id in self.processed_round_game_ids

    def remember_recent_bet(self, *, combo: str, result: bool, limit: int = 200) -> None:
        self.recent_bets.append({"combo": combo, "result": result})
        if len(self.recent_bets) > limit:
            del self.recent_bets[:-limit]

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)
        if key in {
            "pending_expected_bet_drop",
            "pending_expected_settlement_credit",
            "external_deposits_total",
            "external_withdrawals_total",
            "reconciliation_phase",
            "last_external_balance_change_type",
            "last_external_balance_change_amount",
        }:
            self._sync_reconciliation()

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self[key] = value

    def copy(self) -> dict[str, Any]:
        return {field_info.name: getattr(self, field_info.name) for field_info in fields(self)}

    def __bool__(self) -> bool:
        return True


def build_runtime_betting_state(
    *,
    strategy: dict[str, Any] | None = None,
    bet_mode_outcome: str,
    bet_mode_specifier: str,
) -> RuntimeBettingState:
    """Create the canonical runtime state shape for collector and bettor roles."""

    return RuntimeBettingState(
        dynamic_outcome=bet_mode_outcome,
        dynamic_specifier=bet_mode_specifier,
        strategy=strategy,
    )