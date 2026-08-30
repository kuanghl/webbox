"""Dependency-injection context shared by all frontends.

A single frozen-ish dataclass bundles the app config, settings store and
business services. Each frontend's ``main()`` builds one instance and
passes it to page builders, keeping UI code decoupled from construction
details (AGENTS.md 3.4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .store import SettingsStore
from ..modules.translate.service import TranslateService
from ..modules.vram.service import VramService


@dataclass
class AppContext:
    """Container of shared application dependencies.

    Attributes:
        config: Environment-driven app configuration.
        settings: Per-user settings store.
        translate: PDF translation service (babeldoc-backed).
        vram: VRAM estimation service.
    """

    config: AppConfig
    settings: SettingsStore
    translate: TranslateService
    vram: VramService

    @classmethod
    def create(cls, config: AppConfig | None = None) -> "AppContext":
        """Build a fully wired context.

        Args:
            config: Optional pre-built config; one is created when omitted.

        Returns:
            A new :class:`AppContext` with all services instantiated.
        """
        config = config or AppConfig()
        store = SettingsStore(config.resolved_data_dir())
        active = store.active_user()
        return cls(
            config=config,
            settings=store,
            translate=TranslateService(store.load(active)),
            vram=VramService(),
        )
