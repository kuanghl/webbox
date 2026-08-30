"""Settings tab: UI language, theme, user and default provider settings.

Saving persists to the active user's JSON file, switches the active
user, applies the theme live and re-translates the UI when the language
changes (mirrors ``nicegui/pages/settings_page.py`` plus the header
switchers).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Input, Select, Static

from ....core import i18n
from ....core import theme as theme_mod
from ....core.constants import THEMES, UI_LANGUAGES, USERS
from ....core.context import AppContext
from ....core.store import PROVIDER_DEFAULTS, SettingsStore


class SettingsPage(VerticalScroll):
    """Settings form persisting language, theme, user and provider defaults."""

    DEFAULT_CSS = """
    SettingsPage {
        height: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, ctx: AppContext) -> None:
        """Initialize with the shared application context.

        Args:
            ctx: Application context (settings store).
        """
        super().__init__()
        self.ctx = ctx

    def compose(self) -> ComposeResult:
        """Build the settings form from the active user's saved values."""
        s = self.ctx.settings.load()
        yield Static(i18n.tr("st.title"))
        yield Static(i18n.tr("st.language"))
        yield Select(_lang_options(), id="lang", value=s.language)
        yield Static(i18n.tr("st.theme"))
        yield Select(_theme_options(), id="theme", value=s.theme)
        yield Static(i18n.tr("st.user"))
        yield Select([(u, u) for u in USERS], id="user", value=s.user)
        yield Static(i18n.tr("st.provider"))
        yield Select(_provider_options(), id="provider", value=s.provider)
        yield Static(i18n.tr("st.model"))
        yield Input(id="model", value=s.model)
        yield Static(i18n.tr("st.base_url"))
        yield Input(id="base_url", value=s.base_url)
        yield Static(i18n.tr("st.api_key"))
        yield Input(id="api_key", value=s.api_key, password=True)
        yield Button(i18n.tr("common.save"), id="btn_save", variant="primary")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Fill model/URL defaults when the provider changes."""
        if event.select.id != "provider":
            return
        model, url = SettingsStore.provider_defaults(event.value)
        if model:
            self.query_one("#model", Input).value = model
        if url:
            self.query_one("#base_url", Input).value = url

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Persist the form on save (async: may rebuild the pages)."""
        if event.button.id != "btn_save":
            return
        s = self.ctx.settings.load()
        old_user, old_language = s.user, s.language
        s.language = self.query_one("#lang", Select).value
        s.theme = self.query_one("#theme", Select).value
        s.user = self.query_one("#user", Select).value
        s.provider = self.query_one("#provider", Select).value
        s.model = self.query_one("#model", Input).value
        s.base_url = self.query_one("#base_url", Input).value
        s.api_key = self.query_one("#api_key", Input).value
        self.ctx.settings.save(s)
        self.ctx.settings.set_active_user(s.user)
        theme_mod.apply("textual", s.theme)
        await self.app.apply_ui_state(
            s.language,
            user_changed=s.user != old_user,
            language_changed=s.language != old_language,
        )
        self.app.notify(i18n.tr("st.saved"), severity="success")


def _lang_options() -> list[tuple[str, str]]:
    """(display, code) options for the language select."""
    return [(name, code) for code, name in UI_LANGUAGES.items()]


def _theme_options() -> list[tuple[str, str]]:
    """(name, name) options for the theme select."""
    return [(t, t) for t in THEMES]


def _provider_options() -> list[tuple[str, str]]:
    """(name, name) options for the provider select."""
    return [(name, name) for name in PROVIDER_DEFAULTS]
