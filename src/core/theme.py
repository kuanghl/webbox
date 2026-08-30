"""Theme application per frontend framework.

The core layer only knows theme *names* (``light``/``dark``); each
frontend registers its own applier so the settings page stays
framework-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .constants import THEMES

#: ``theme_name -> callable(theme_name)``; frontends register at startup.
_APPLIERS: dict[str, Callable[[str], None]] = {}


def register_applier(framework: str, applier: Callable[[str], None]) -> None:
    """Register the theme applier for a frontend framework.

    Args:
        framework: Frontend name (``nicegui``/``textual``).
        applier: Callable receiving the theme name to apply.
    """
    _APPLIERS[framework] = applier


def apply(framework: str, theme: str) -> None:
    """Apply a theme through the framework's registered applier.

    Args:
        framework: Frontend name the applier was registered under.
        theme: Theme name (see :data:`src.core.constants.THEMES`).

    Raises:
        KeyError: If no applier is registered for the framework.
    """
    if theme not in THEMES:
        theme = "dark"
    _APPLIERS[framework](theme)


def theme_names() -> dict[str, str]:
    """Return available themes as ``{name: display_name}``."""
    return dict(THEMES)


def any_registered() -> bool:
    """Return whether at least one framework registered an applier."""
    return bool(_APPLIERS)
