from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


dashboard_app_module = importlib.import_module("dashboard.app")


def test_dashboard_health_route(monkeypatch) -> None:
    called = []

    def fake_fetch_one(query: str, params=(), conn=None):
        called.append((query, params, conn))
        return {"ok": 1}

    monkeypatch.setattr(dashboard_app_module, "_fetch_one", fake_fetch_one)

    with TestClient(dashboard_app_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert called


def test_dashboard_split_routes_return_builder_payloads(monkeypatch) -> None:
    status_payload = {
        "snapshot": {"runtime_role": "bettor"},
        "summary": {"freshness_state": "fresh", "reconciliation_phase": "idle"},
        "latest_win": {"id": 1},
    }
    history_payload = {
        "recent_bets": [{"id": 11}],
        "recent_rounds": [{"id": 21}],
        "recent_events": [{"id": 31}],
        "latest_bet": {"id": 11},
        "latest_round": {"id": 21},
    }
    chart_payload = {
        "balance_series": [{"timestamp": "2026-04-18T14:00:00+00:00", "session_balance": 10, "account_balance": 20}],
        "result_curve": [{"wins": 1, "losses": 0, "net": 1, "rolling20": 100.0, "rolling50": 100.0}],
    }

    monkeypatch.setattr(dashboard_app_module, "_ensure_dashboard_schema", lambda: None)
    monkeypatch.setattr(dashboard_app_module, "_build_status_payload", lambda: status_payload)
    monkeypatch.setattr(dashboard_app_module, "_build_history_payload", lambda: history_payload)
    monkeypatch.setattr(dashboard_app_module, "_build_chart_payload", lambda: chart_payload)

    with TestClient(dashboard_app_module.app) as client:
        status_response = client.get("/api/status")
        history_response = client.get("/api/history")
        charts_response = client.get("/api/charts")

    assert status_response.status_code == 200
    assert status_response.json() == status_payload
    assert history_response.status_code == 200
    assert history_response.json() == history_payload
    assert charts_response.status_code == 200
    assert charts_response.json() == chart_payload


def test_dashboard_index_renders_html(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_app_module, "_ensure_dashboard_schema", lambda: None)

    with TestClient(dashboard_app_module.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "BuyBayBye Dashboard" in response.text