"""Reusable NiceGUI components (header, switchers, result helpers).

Every page is built by a ``build(ctx)`` function; the shared chrome
(header + switchers) lives here so pages stay small.
"""

from __future__ import annotations

from nicegui import ui

from ...core import i18n
from ...core.constants import APP_NAME, THEMES, UI_LANGUAGES, USERS
from ...core.context import AppContext
from ...core.store import SettingsStore, UserSettings
from ...core import theme as theme_mod


def apply_theme(ctx: AppContext, theme_name: str) -> None:
    """Apply a theme to the running NiceGUI app.

    Args:
        ctx: Application context (used only for symmetry with other frontends).
        theme_name: ``light`` or ``dark``.
    """
    ui.dark_mode.value = theme_name == "dark"


def build_header(ctx: AppContext) -> None:
    """Render the top header with app name and the three switchers.

    Language and user changes persist then reload the page (all labels are
    rendered from i18n keys at build time). Theme applies live.

    Args:
        ctx: Application context.
    """
    settings: UserSettings = ctx.settings.load()
    with ui.header().classes("items-center bg-transparent px-4"):
        ui.label(APP_NAME).classes("text-lg font-bold")
        ui.label(i18n.tr("app.tagline")).classes("text-sm text-gray-400")
        ui.space()

        def switch_language(e) -> None:
            s = ctx.settings.load()
            s.language = e.value
            ctx.settings.save(s)
            i18n.set_language(s.language)
            ui.navigate.reload()

        ui.select(
            options=UI_LANGUAGES,
            value=settings.language,
            on_change=switch_language,
            with_input=False,
        ).classes("w-32")

        def switch_theme(e) -> None:
            s = ctx.settings.load()
            s.theme = e.value
            ctx.settings.save(s)
            theme_mod.apply("nicegui", e.value)
            ui.notify(i18n.tr("st.theme_applied"), type="positive")

        ui.select(
            options=THEMES,
            value=settings.theme,
            on_change=switch_theme,
            with_input=False,
        ).classes("w-28")

        def switch_user(e) -> None:
            ctx.settings.set_active_user(e.value)
            ui.notify(i18n.tr("st.user_switched", user=e.value), type="positive")
            ui.navigate.reload()

        ui.select(
            options=list(USERS),
            value=settings.user,
            on_change=switch_user,
            with_input=False,
        ).classes("w-28")


def provider_select(
    value: str, on_change=None, classes: str = "w-44", label: str | None = None
) -> ui.select:
    """Build a provider dropdown pre-filled with known providers.

    Args:
        value: Currently selected provider name.
        on_change: Optional change callback.
        classes: CSS classes for sizing.
        label: Optional field label.

    Returns:
        The configured select element.
    """
    from ...core.store import PROVIDER_DEFAULTS

    return ui.select(
        options=list(PROVIDER_DEFAULTS.keys()),
        value=value,
        label=label,
        on_change=on_change,
        with_input=False,
    ).classes(classes)


def on_provider_change(ctx: AppContext, model_input: ui.input, url_input: ui.input):
    """Return a change handler that fills model/URL defaults for a provider.

    Args:
        ctx: Application context (unused, kept for symmetry).
        model_input: Model name input to update.
        url_input: Base URL input to update.

    Returns:
        A callback suitable for ``ui.select(on_change=...)``.
    """

    def handler(e) -> None:
        model, url = SettingsStore.provider_defaults(e.value)
        if model:
            model_input.value = model
        if url:
            url_input.value = url

    return handler
