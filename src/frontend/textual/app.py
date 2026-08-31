"""Textual application entry point.

Run with::

    python -m src.frontend.textual.app

or ``webbox-textual`` once installed. A single window hosts three tabs
(Translate / VRAM / Settings); language, theme and user are switchable
from the always-visible header bar and the Settings tab (see
docs/refer-textual.md).

The TUI runs in a local terminal — there is no host/port binding.
"""

from __future__ import annotations

import logging

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Select, Static, TabbedContent, TabPane

from ...core import i18n
from ...core import theme as theme_mod
from ...core.config import AppConfig
from ...core.constants import APP_NAME, THEMES, UI_LANGUAGES, USERS
from ...core.context import AppContext
from ...core.logging_setup import setup_logging
from .pages.settings import SettingsPage
from .pages.translate import TranslatePage
from .pages.vram import VramPage

logger = logging.getLogger(__name__)

#: (pane id, nav i18n key, page class) for the three tabs, in order.
_PAGES: tuple[tuple[str, str, type], ...] = (
    ("pane_translate", "nav.translate", TranslatePage),
    ("pane_vram", "nav.vram", VramPage),
    ("pane_settings", "nav.settings", SettingsPage),
)

# Header switchers: (settings field, select id, label key), in display order.
_SWITCHERS = (
    ("language", "sw_lang", "st.language"),
    ("theme", "sw_theme", "st.theme"),
    ("user", "sw_user", "st.user"),
)
# Reverse lookup: select id -> settings field, for the change handler.
_SWITCH_FIELD_BY_ID = {select_id: field for field, select_id, _ in _SWITCHERS}


class SwitcherBar(Horizontal):
    """Always-visible language / theme / user switcher bar.

    Mirrors the NiceGUI home switchers: each control applies its change
    immediately (no Save button). The bar sits between the ``Header`` and
    the tabbed content so the controls are reachable from every tab.

    Args:
        ctx: Shared application context (settings + i18n).
    """

    def __init__(self, ctx: AppContext) -> None:
        """Initialise the bar with the shared context.

        Args:
            ctx: Shared application context.
        """
        super().__init__()
        self.ctx = ctx

    def compose(self) -> ComposeResult:
        """Build the three labelled selects from the current settings.

        Yields:
            A labelled Select for each of language, theme and user.
        """
        s = self.ctx.settings.load()
        for field, select_id, label_key in _SWITCHERS:
            yield Static(i18n.tr(label_key), id=f"lbl_{select_id}")
            if field == "language":
                yield Select(
                    [(name, code) for code, name in UI_LANGUAGES.items()],
                    id=select_id,
                    value=s.language,
                )
            elif field == "theme":
                yield Select([(t, t) for t in THEMES], id=select_id, value=s.theme)
            else:  # user
                yield Select([(u, u) for u in USERS], id=select_id, value=s.user)

    def relabel(self) -> None:
        """Re-translate the three labels after a language change."""
        for _field, select_id, label_key in _SWITCHERS:
            self.query_one(f"#lbl_{select_id}", Static).update(i18n.tr(label_key))

    def sync(self) -> None:
        """Re-point the selects at the current settings after a user switch.

        Assigning a new ``value`` posts ``Select.Changed``; the per-field
        guards in :meth:`WebboxApp.apply_switcher` make those re-fired
        events no-ops (the value already matches the saved settings).
        """
        s = self.ctx.settings.load()
        for field, select_id, _label in _SWITCHERS:
            self.query_one(f"#{select_id}", Select).value = getattr(s, field)


class WebboxApp(App):
    """WebBox TUI: translate, VRAM and settings in three tabs."""

    TITLE = APP_NAME
    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    TabbedContent {
        height: 1fr;
    }

    TabPane {
        height: 1fr;
    }
    """

    def __init__(self, ctx: AppContext) -> None:
        """Initialize with the shared application context.

        Args:
            ctx: Application context providing services and settings.
        """
        super().__init__()
        self.ctx = ctx
        theme_mod.register_applier("textual", self._apply_theme)

    def compose(self) -> ComposeResult:
        """Build the header, switcher bar, the three tab panes and the footer."""
        yield Header()
        yield SwitcherBar(self.ctx)
        with TabbedContent(*(i18n.tr(nav) for _, nav, _ in _PAGES)):
            for pane_id, nav, page_cls in _PAGES:
                with TabPane(i18n.tr(nav), id=pane_id):
                    yield page_cls(self.ctx)
        yield Footer()

    def on_mount(self) -> None:
        """Apply the persisted theme once the DOM exists."""
        self._apply_theme(self.ctx.settings.load().theme)

    def relabel_tabs(self) -> None:
        """Re-translate the tab labels (after a language switch)."""
        tabs = self.query_one(TabbedContent)
        for pane_id, nav, _ in _PAGES:
            tabs.get_tab(pane_id).label = i18n.tr(nav)

    async def rebuild_all_pages(self) -> None:
        """Rebuild every tab pane (fresh language and settings)."""
        for pane_id, _, _ in _PAGES:
            await self._rebuild(pane_id)

    async def reload_data_pages(self) -> None:
        """Rebuild the translate/vram panes with fresh user settings.

        Called after a user switch; the settings pane is rebuilt by
        :meth:`rebuild_all_pages` when the language changes too.
        """
        for pane_id, _, _ in _PAGES[:2]:
            await self._rebuild(pane_id)

    async def apply_ui_state(
        self, language: str, *, user_changed: bool, language_changed: bool
    ) -> None:
        """Apply a settings save: switch language and/or refresh pages.

        Args:
            language: New UI language code (applied when changed).
            user_changed: Active user changed (refresh data pages).
            language_changed: Language changed (refresh all pages).
        """
        if language_changed:
            i18n.set_language(language)
            self.relabel_tabs()
            self._relabel_switchers()
            await self.rebuild_all_pages()
        elif user_changed:
            await self.reload_data_pages()

    def _relabel_switchers(self) -> None:
        """Re-translate the header switcher labels (after a language change)."""
        self.query_one(SwitcherBar).relabel()

    async def apply_switcher(self, field: str, value: str) -> None:
        """Apply one header switcher change immediately (no Save button).

        Mirrors the NiceGUI home switchers: the value is persisted and
        applied live. Language re-translates and rebuilds the pages; theme
        applies live; a user switch loads that user's own settings.

        Args:
            field: ``language``, ``theme`` or ``user``.
            value: New value for the field.
        """
        if field == "user":
            await self._switch_user(value)
            return
        if field not in ("language", "theme"):
            return
        s = self.ctx.settings.load()
        changed = getattr(s, field) != value
        setattr(s, field, value)
        self.ctx.settings.save(s)
        if not changed:
            return
        if field == "language":
            await self.apply_ui_state(
                s.language, user_changed=False, language_changed=True
            )
        else:  # theme
            theme_mod.apply("textual", s.theme)
            self.notify(i18n.tr("st.theme_applied"), severity="success")

    async def _switch_user(self, user: str) -> None:
        """Switch the active user and reload the UI with that user's settings.

        Mirrors the NiceGUI user switcher (set_active_user + page reload):
        the new user's language, theme and data defaults all take effect.

        Args:
            user: Account name to activate.
        """
        old = self.ctx.settings.load()
        if old.user == user:
            return
        self.ctx.settings.set_active_user(user)
        new = self.ctx.settings.load()
        self.notify(i18n.tr("st.user_switched", user=user), severity="success")
        if new.theme != old.theme:
            theme_mod.apply("textual", new.theme)
        if new.language != old.language:
            i18n.set_language(new.language)
            self.relabel_tabs()
            self._relabel_switchers()
        await self.rebuild_all_pages()
        self.query_one(SwitcherBar).sync()

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Route a header switcher change to :meth:`apply_switcher`.

        Selects on the Settings tab keep their own ids (``#lang`` etc.), so
        only the switcher-bar ids are handled here. The selects also emit a
        ``Changed`` carrying their initial value on mount; the per-field
        guards in :meth:`apply_switcher` make those no-ops.

        Args:
            event: The Select.Changed event.
        """
        field = _SWITCH_FIELD_BY_ID.get(event.select.id, "")
        if not field:
            return
        await self.apply_switcher(field, event.value)

    async def _rebuild(self, pane_id: str) -> None:
        """Replace one tab pane's contents with a freshly composed page.

        No-op when the pane is already gone: the app can be shutting down
        while a rebuild is in flight (e.g. quit pressed mid language
        switch), in which case there is nothing left to rebuild.

        Args:
            pane_id: Id of the TabPane to rebuild.
        """
        page_cls = next(cls for pid, _, cls in _PAGES if pid == pane_id)
        panes = self.query(f"#{pane_id}")
        if not panes:
            return
        pane = panes.first()
        await pane.remove_children()
        await pane.mount(page_cls(self.ctx))

    def _apply_theme(self, theme_name: str) -> None:
        """Map a WebBox theme name to the Textual theme.

        Args:
            theme_name: ``light`` or ``dark``.
        """
        self.theme = "textual-dark" if theme_name == "dark" else "textual-light"


def main() -> None:
    """Configure logging, build the context and run the TUI."""
    config = AppConfig()
    setup_logging(config.log_level, config.log_dir)
    ctx = AppContext.create(config)
    i18n.set_language(ctx.settings.load().language)
    logger.info("Starting Textual frontend (terminal mode)")
    WebboxApp(ctx).run()


if __name__ in {"__main__", "__mp_main__"}:
    main()
