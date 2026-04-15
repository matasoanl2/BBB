"""Сборка runtime-объектов для главной точки входа приложения."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from buybaybye.core.runtime_app import RuntimeApp
from buybaybye.core.runtime_config import RuntimeConfig, load_runtime_config
from buybaybye.core.runtime_context import RuntimeContext, create_runtime_context
from buybaybye.services.runtime_services import RuntimeServices


@dataclass(slots=True)
class RuntimeComponents:
    """Контейнер с собранными runtime config, state, services и app."""

    config: RuntimeConfig
    context: RuntimeContext
    services: RuntimeServices
    app: RuntimeApp


def build_runtime(app_dir: Path) -> RuntimeComponents:
    """Собрать полностью связанный runtime graph приложения."""

    runtime_config = load_runtime_config(app_dir)
    runtime_context = create_runtime_context(
        bet_mode_outcome=runtime_config.betting.default_outcome,
        bet_mode_specifier=runtime_config.betting.default_specifier,
    )
    services = RuntimeServices(runtime_context, runtime_config)
    app = RuntimeApp(runtime_config, runtime_context, services)
    return RuntimeComponents(
        config=runtime_config,
        context=runtime_context,
        services=services,
        app=app,
    )