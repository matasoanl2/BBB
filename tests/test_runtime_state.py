from buybaybye.core.runtime_state import build_runtime_betting_state


def test_runtime_state_behaves_like_mapping() -> None:
    state = build_runtime_betting_state(strategy=None, bet_mode_outcome="red", bet_mode_specifier="5")

    state["current_step"] = 3
    state["pending_expected_bet_drop"] = 25.0

    assert state["current_step"] == 3
    assert state.get("pending_expected_bet_drop") == 25.0
    assert state.reconciliation.pending_expected_bet_drop == 25.0


def test_runtime_state_tracks_processed_rounds_and_recent_bets() -> None:
    state = build_runtime_betting_state(strategy=None, bet_mode_outcome="red", bet_mode_specifier="5")

    state.mark_round_processed("game-1")
    state.remember_recent_bet(combo="R5", result=True, limit=2)
    state.remember_recent_bet(combo="Y2", result=False, limit=2)
    state.remember_recent_bet(combo="D", result=True, limit=2)

    assert state.has_processed_round("game-1") is True
    assert state.recent_bets == [{"combo": "Y2", "result": False}, {"combo": "D", "result": True}]