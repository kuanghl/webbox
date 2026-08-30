"""Home page: module dock, card grid and rotating carousel."""

from __future__ import annotations

from nicegui import ui

from ....core.context import AppContext
from ..components import MODULES, wb_home_card, wb_home_dock, wb_rotating_zone


def build(ctx: AppContext) -> None:
    """Render the home page.

    Args:
        ctx: Application context.
    """
    with ui.column().classes("wb-home w-full"):
        wb_home_dock()
        with ui.column().classes("wb-home-zone w-full"):
            with ui.row().classes("wb-home-grid w-full"):
                for m in MODULES:
                    wb_home_card(m)
        wb_rotating_zone()