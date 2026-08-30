"""Textual application entry point.

Run with::

    python -m src.frontend.textual.app

or ``webbox-textual`` once installed. A single window hosts three tabs
(Translate / VRAM / Settings); language, theme and user live on the
Settings tab (see docs/refer-textual.md).

The TUI runs in a local terminal — there is no host/port binding.
"""

from __future__ import annotations

import logging

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, TabbedContent, TabPane

from ...core import i18n
from ...core import theme as theme_mod
from ...core.config import AppConfig
from ...core.constants import APP_NAME
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
        """Build the header, the three tab panes and the footer."""
        yield Header()
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
            await self.rebuild_all_pages()
        elif user_changed:
            await self.reload_data_pages()

    async def _rebuild(self, pane_id: str) -> None:
        """Replace one tab pane's contents with a freshly composed page.

        Args:
            pane_id: Id of the TabPane to rebuild.
        """
        page_cls = next(cls for pid, _, cls in _PAGES if pid == pane_id)
        pane = self.query_one(f"#{pane_id}", TabPane)
        pane.remove_children()
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
