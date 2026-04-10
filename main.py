"""
Patchright с одной постоянной сессией: данные профиля лежат в каталоге SESSION_DIR.
При каждом запуске используется тот же профиль; после закрытия браузера состояние остается на диске.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from patchright.async_api import async_playwright

SESSION_DIR = Path(__file__).resolve().parent / "profile"
TARGET_WS_URL = "wss://ws.betboom.ru:444/api/nards_studio_ws/v1"
TARGET_WS_LOG_FILE = SESSION_DIR / "target_ws_messages.json"
HEADLESS = os.getenv("HEADLESS", "false").lower() in {"1", "true", "yes", "on"}


def _format_ws_payload(payload: object) -> str:
    if isinstance(payload, bytes):
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload.hex()
    return str(payload)


def _load_saved_messages(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _append_target_ws_message(path: Path, payload: object) -> None:
    payload_text = _format_ws_payload(payload)
    try:
        parsed_payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if not isinstance(parsed_payload, dict):
        return
    if parsed_payload.get("status") != "rng_values":
        return

    results = parsed_payload.get("results")
    if not isinstance(results, dict):
        return

    messages = _load_saved_messages(path)
    messages.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
    )
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def _wire_ws_logging(page) -> None:
    def on_websocket(ws) -> None:
        is_target = ws.url.startswith(TARGET_WS_URL)
        tag = "TARGET-WS" if is_target else "WS"
        print(f"[{tag} OPEN] {ws.url}", flush=True)

        def on_sent(payload) -> None:
            print(f"[{tag} >>] {_format_ws_payload(payload)}", flush=True)

        def on_received(payload) -> None:
            print(f"[{tag} <<] {_format_ws_payload(payload)}", flush=True)
            if is_target:
                _append_target_ws_message(TARGET_WS_LOG_FILE, payload)

        def on_close(*_) -> None:
            print(f"[{tag} CLOSE] {ws.url}", flush=True)

        ws.on("framesent", on_sent)
        ws.on("framereceived", on_received)
        ws.on("close", on_close)

    page.on("websocket", on_websocket)


async def _wait_for_exit_signal() -> None:
    if sys.stdin.isatty():
        try:
            await asyncio.to_thread(input)
        except EOFError:
            pass
        return

    # In non-interactive environments like docker compose up, keep the process
    # alive until it is stopped from the outside.
    await asyncio.Event().wait()


async def main() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--no-first-run",
            "--no-service-autorun",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--disable-translate",
            "--mute-audio",
            "--disable-notifications",
            "--disable-logging",
            "--metrics-recording-only",
            "--disable-hang-monitor",
            "--password-store=basic",
            "--autoplay-policy=no-user-gesture-required",
        ]

    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=HEADLESS,
        args=args,
    )
    try:
        for existing_page in context.pages:
            _wire_ws_logging(existing_page)
        context.on("page", _wire_ws_logging)

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://betboom.ru/game/nardsgame")
        print(
            f"Браузер открыт. Профиль сессии: {SESSION_DIR}\n"
            "Закройте окно браузера или нажмите Enter здесь - сессия сохранится.",
            flush=True,
        )
        await _wait_for_exit_signal()
    finally:
        await context.close()
        await playwright.stop()

    print("Контекст закрыт, профиль записан. Следующий запуск продолжит ту же сессию.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
