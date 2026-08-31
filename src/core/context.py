"""Dependency-injection context shared by all frontends.

A single frozen-ish dataclass bundles the app config, settings store and
business services. Each frontend's ``main()`` builds one instance and
passes it to page builders, keeping UI code decoupled from construction
details (AGENTS.md 3.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import AppConfig
from .store import SettingsStore
from ..modules.translate.service import TranslateService
from ..modules.vram.service import VramService


class FeatureState:
    """Session-only record of which features the user has entered.

    In-memory only: it resets on restart and is never persisted, so the
    rotating home dock stays hidden until the user has opened at least one
    feature during the current session.
    """

    def __init__(self) -> None:
        """Initialize with no features entered."""
        self._entered: set[str] = set()

    def mark_entered(self, feature_id: str) -> None:
        """Record that the user entered a feature.

        Args:
            feature_id: Feature identifier (e.g. a module key such as ``vram``).
        """
        self._entered.add(feature_id)

    def has_entered(self, feature_id: str) -> bool:
        """Return whether the user has entered a feature this session.

        Args:
            feature_id: Feature identifier.

        Returns:
            True if the feature was entered during this session.
        """
        return feature_id in self._entered

    def any_entered(self) -> bool:
        """Return whether the user has entered any feature this session."""
        return bool(self._entered)


@dataclass
class AppContext:
    """Container of shared application dependencies.

    Attributes:
        config: Environment-driven app configuration.
        settings: Per-user settings store.
        translate: PDF translation service (babeldoc-backed).
        vram: VRAM estimation service.
        features: Session-only record of entered features.
    """

    config: AppConfig
    settings: SettingsStore
    translate: TranslateService
    vram: VramService
    features: FeatureState = field(default_factory=FeatureState)

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
