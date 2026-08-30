"""Flet web application entry point.

Run with::

    python -m src.frontend.flet.app --port 8081

or ``webbox-flet`` once packaged. Like the NiceGUI frontend it is a single
page with three tabs (Translate / VRAM / Settings); all business logic
comes from the shared ``core`` / ``modules`` layers (AGENTS.md 3.4).

Bind address/port resolution: CLI flag > ``WEBBOX_HOST``/``WEBBOX_PORT``
env vars > built-in defaults.

Flet 0.86 notes: ``ft.run`` replaces the deprecated ``ft.app``; ``Tabs``
composes ``TabBar`` + ``TabBarView``; in web mode picked files arrive as
bytes (``file_picker.pick_files(with_data=True)``) and downloads go
through ``file_picker.save_file(src_bytes=...)``.
"""

from __future__ import annotations

import argparse
import logging

import flet as ft

from ...core import i18n
from ...core.config import AppConfig
from ...core.constants import APP_NAME, THEMES, UI_LANGUAGES, USERS
from ...core.context import AppContext
from ...core.logging_setup import setup_logging
from ...core.utils import check_port_available
from .pages import build_translate_tab, build_settings_tab, build_vram_tab

logger = logging.getLogger(__name__)


def _opts(mapping: dict[str, str]) -> list[ft.dropdown.Option]:
    """Build dropdown options from a ``{key: label}`` mapping."""
    return [ft.dropdown.Option(key=k, text=v) for k, v in mapping.items()]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI overrides for the bind address and port.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Parsed arguments; ``None`` values mean "use env/config default".
    """
    parser = argparse.ArgumentParser(
        prog="webbox-flet", description="BabelDOC WebBox (Flet web frontend)"
    )
    parser.add_argument(
        "--host", default=None, help="Bind address (default: $WEBBOX_HOST or 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Bind port (default: $WEBBOX_PORT or 8080)"
    )
    return parser.parse_args(argv)


def main() -> None:
    """Configure logging, build the context and run the Flet web server."""
    config = AppConfig()
    args = _parse_args()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    setup_logging(config.log_level, config.log_dir)
    ctx = AppContext.create(config)
    settings = ctx.settings.load()
    i18n.set_language(settings.language)

    if not check_port_available(config.host, config.port):
        logger.error(
            "Port %s:%s is already in use; free it or start with "
            "--port <n> (or WEBBOX_PORT=<n>).",
            config.host,
            config.port,
        )
        raise SystemExit(1)
    logger.info("Starting Flet frontend on %s:%s", config.host, config.port)

    def page_main(page: ft.Page) -> None:
        """Flet entry callback: title, theme and the app tree."""
        page.title = APP_NAME
        s = ctx.settings.load()
        page.theme_mode = ft.ThemeMode.DARK if s.theme == "dark" else ft.ThemeMode.LIGHT
        page.padding = 16
        page.add(build_app(page, ctx))

    ft.run(page_main, host=config.host, port=config.port, view=ft.AppView.WEB_BROWSER)


def build_app(page: ft.Page, ctx: AppContext) -> ft.Column:
    """Build the whole single-page app (header + three tabs).

    Args:
        page: Flet page (file picker / theme access).
        ctx: Application context.

    Returns:
        Root column with the header and the tab control.
    """
    settings = ctx.settings.load()

    def _rebuild() -> None:
        """Re-render the page (after language/user switch)."""
        page.controls.clear()
        page.add(build_app(page, ctx))
        page.update()

    def switch_language(e: ft.ControlEvent) -> None:
        s = ctx.settings.load()
        s.language = e.control.value
        ctx.settings.save(s)
        i18n.set_language(s.language)
        _rebuild()

    def switch_theme(e: ft.ControlEvent) -> None:
        s = ctx.settings.load()
        s.theme = e.control.value
        ctx.settings.save(s)
        page.theme_mode = ft.ThemeMode.DARK if s.theme == "dark" else ft.ThemeMode.LIGHT
        page.update()

    def switch_user(e: ft.ControlEvent) -> None:
        ctx.settings.set_active_user(e.control.value)
        _rebuild()

    lang_dd = ft.Dropdown(options=_opts(UI_LANGUAGES), value=settings.language, width=140)
    theme_dd = ft.Dropdown(options=_opts(THEMES), value=settings.theme, width=110)
    user_dd = ft.Dropdown(
        options=[ft.dropdown.Option(key=u, text=u) for u in USERS],
        value=settings.user,
        width=110,
    )
    # Flet 0.86: dropdowns expose on_select (attribute), not on_change
    lang_dd.on_select = switch_language
    theme_dd.on_select = switch_theme
    user_dd.on_select = switch_user

    header = ft.Row(
        [
            ft.Column(
                [
                    ft.Text(APP_NAME, size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(i18n.tr("app.tagline"), size=12, color=ft.Colors.GREY),
                ],
                expand=True,
            ),
            lang_dd,
            theme_dd,
            user_dd,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    return ft.Column(
        [
            header,
            ft.Tabs(
                length=3,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        ft.TabBar(
                            tabs=[
                                ft.Tab(label=i18n.tr("nav.translate"), icon=ft.Icons.TRANSLATE),
                                ft.Tab(label=i18n.tr("nav.vram"), icon=ft.Icons.MEMORY),
                                ft.Tab(label=i18n.tr("nav.settings"), icon=ft.Icons.SETTINGS),
                            ]
                        ),
                        ft.TabBarView(
                            expand=True,
                            controls=[
                                build_translate_tab(page, ctx),
                                build_vram_tab(page, ctx),
                                build_settings_tab(page, ctx),
                            ],
                        ),
                    ],
                ),
            ),
        ],
        spacing=12,
        expand=True,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
