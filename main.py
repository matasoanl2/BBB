"""Главная точка входа в рантайм-приложение BuyBayBye."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from buybaybye.runtime_factory import RuntimeComponents, build_runtime

APP_DIR = Path(__file__).resolve().parent

async def main(runtime: RuntimeComponents | None = None) -> None:
    """Запустить собранное рантайм-приложение."""

    runtime_components = runtime or build_runtime(APP_DIR)
    await runtime_components.app.run()


if __name__ == "__main__":
    try:
        runtime = build_runtime(APP_DIR)
        if runtime.services.is_telegram_chat_id_mode(sys.argv):
            asyncio.run(runtime.services.run_telegram_chat_id_helper())
        else:
            asyncio.run(main(runtime))
    except KeyboardInterrupt:
        sys.exit(130)
