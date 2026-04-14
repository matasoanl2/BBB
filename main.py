"""
Patchright с одной постоянной сессией: данные профиля лежат в каталоге SESSION_DIR.
При каждом запуске используется тот же профиль; после закрытия браузера состояние остается на диске.
Сохранение данных в PostgreSQL вместо JSON.
Поддержка автоматического размещения ставок с различными стратегиями из YAML.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from buybaybye.runtime_factory import RuntimeComponents, build_runtime

APP_DIR = Path(__file__).resolve().parent

async def main(runtime: RuntimeComponents | None = None) -> None:
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
