"""Settings page: UI language, theme, user, and default provider settings.

OpenPencil-style layout: top bar, appearance/provider panels and a
bottom action bar with the save button.
"""

from __future__ import annotations

from nicegui import ui

from ....core import i18n
from ....core.constants import THEMES, UI_LANGUAGES, USERS
from ....core.context import AppContext
from ..components import (
    on_provider_change,
    provider_select,
    wb_input_bar,
    wb_panel_head,
    wb_primary_btn,
    wb_top_bar,
)


def build(ctx: AppContext) -> None:
    """Render the settings page.

    Args:
        ctx: Application context.
    """
    settings = ctx.settings.load()

    with ui.column().classes("wb-page w-full"):
        wb_top_bar(i18n.tr("st.title_bar"))
        with ui.row().classes("wb-body"):
            with ui.column().classes("wb-main"):
                with ui.column().classes("wb-workspace gap-4"):
                    with ui.column().classes("wb-panel w-full gap-3"):
                        wb_panel_head(i18n.tr("st.appearance").upper())
                        with ui.row().classes("gap-2 w-full"):
                            lang = ui.select(
                                options=UI_LANGUAGES,
                                value=settings.language,
                                label=i18n.tr("st.language"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                            theme = ui.select(
                                options=THEMES,
                                value=settings.theme,
                                label=i18n.tr("st.theme"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                            user = ui.select(
                                options=list(USERS),
                                value=settings.user,
                                label=i18n.tr("st.user"),
                                with_input=False,
                            ).classes("flex-1").props("dense outlined")
                    with ui.column().classes("wb-panel w-full gap-3"):
                        wb_panel_head(i18n.tr("st.provider").upper())
                        model_input = ui.input(
                            label=i18n.tr("st.model"), value=settings.model
                        ).props("dense outlined").classes("w-full")
                        url_input = ui.input(
                            label=i18n.tr("st.base_url"), value=settings.base_url
                        ).props("dense outlined").classes("w-full")
                        prov = provider_select(
                            settings.provider,
                            on_change=on_provider_change(ctx, model_input, url_input),
                            label=i18n.tr("st.provider"),
                        ).props("dense outlined")
                        key_input = ui.input(
                            label=i18n.tr("st.api_key"),
                            value=settings.api_key,
                            password=True,
                            password_toggle_button=True,
                        ).props("dense outlined").classes("w-full")

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

        with wb_input_bar():
            wb_primary_btn(i18n.tr("common.save"), on_click=save, icon="save")
