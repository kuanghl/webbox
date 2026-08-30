"""Settings page: UI language, theme, user, and default provider settings."""

from __future__ import annotations

from nicegui import ui

from ....core import i18n
from ....core.constants import THEMES, UI_LANGUAGES, USERS
from ....core.context import AppContext
from ..components import on_provider_change, provider_select


def build(ctx: AppContext) -> None:
    """Render the settings page content.

    Args:
        ctx: Application context.
    """
    settings = ctx.settings.load()

    with ui.card().classes("w-full max-w-xl"):
        ui.label(i18n.tr("st.title")).classes("text-lg font-semibold")
        with ui.column().classes("gap-2 w-full"):
            lang = ui.select(
                options=UI_LANGUAGES,
                value=settings.language,
                label=i18n.tr("st.language"),
            )
            theme = ui.select(
                options=THEMES,
                value=settings.theme,
                label=i18n.tr("st.theme"),
            )
            user = ui.select(
                options=list(USERS),
                value=settings.user,
                label=i18n.tr("st.user"),
            )
            model_input = ui.input(label=i18n.tr("st.model"), value=settings.model)
            url_input = ui.input(label=i18n.tr("st.base_url"), value=settings.base_url)
            prov = provider_select(
                settings.provider,
                on_change=on_provider_change(ctx, model_input, url_input),
                label=i18n.tr("st.provider"),
            )
            key_input = ui.input(
                label=i18n.tr("st.api_key"),
                value=settings.api_key,
                password=True,
                password_toggle_button=True,
            )

            def save() -> None:
                """Persist edited settings to the user's JSON file."""
                s = ctx.settings.load()
                s.language = lang.value
                s.theme = theme.value
                s.user = user.value
                s.provider = prov.value
                s.model = model_input.value
                s.base_url = url_input.value
                s.api_key = key_input.value
                ctx.settings.save(s)
                i18n.set_language(s.language)
                ui.notify(i18n.tr("st.saved"), type="positive")
                ui.navigate.reload()

            ui.button(
                i18n.tr("common.save"), on_click=save, icon="save"
            ).props("color=primary")
