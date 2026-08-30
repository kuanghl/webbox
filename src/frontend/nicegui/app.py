"""NiceGUI application entry point.

Run with::

    python -m src.frontend.nicegui.app --port 8081

or ``webbox-nicegui`` once packaged. Routes: ``/`` (home), ``/chat``,
``/agent`` and ``/hosts`` (visual stubs), ``/translate``, ``/vram`` and
``/settings``.

Bind address/port resolution: CLI flag > ``WEBBOX_HOST``/``WEBBOX_PORT``
env vars > built-in defaults (see :class:`~src.core.config.AppConfig`).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from nicegui import ui

from ...core import i18n
from ...core import theme as theme_mod
from ...core.config import AppConfig
from ...core.constants import APP_NAME
from ...core.context import AppContext
from ...core.logging_setup import setup_logging
from ...core.utils import check_port_available
from .pages import (
    agent_page,
    chat_page,
    home_page,
    hosts_page,
    settings_page,
    translate_page,
    vram_page,
)

logger = logging.getLogger(__name__)

#: OpenPencil design tokens + component classes.
_THEME_CSS = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI overrides for the bind address and port.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Parsed arguments; ``None`` values mean "use env/config default".
    """
    parser = argparse.ArgumentParser(
        prog="webbox-nicegui",
        description="BabelDOC WebBox (NiceGUI web frontend)",
    )
    parser.add_argument(
        "--host", default=None, help="Bind address (default: $WEBBOX_HOST or 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Bind port (default: $WEBBOX_PORT or 8080)"
    )
    return parser.parse_args(argv)


def main() -> None:
    """Configure logging, build the context, register routes and run."""
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

    theme_mod.register_applier("nicegui", lambda t: _set_dark(t == "dark"))
    _set_dark(settings.theme == "dark")
    ui.add_css(_THEME_CSS, shared=True)

    @ui.page("/")
    def home() -> None:
        """Home: module dock, card grid and rotating zone."""
        home_page.build(ctx)

    @ui.page("/chat")
    def chat() -> None:
        """Chat module (visual stub)."""
        chat_page.build(ctx)

    @ui.page("/agent")
    def agent() -> None:
        """Agent/ACP module (visual stub)."""
        agent_page.build(ctx)

    @ui.page("/hosts")
    def hosts() -> None:
        """Host/SSH module (visual stub)."""
        hosts_page.build(ctx)

    @ui.page("/translate")
    def translate() -> None:
        """PDF translation module (BabelDOC)."""
        translate_page.build(ctx)

    @ui.page("/vram")
    def vram() -> None:
        """VRAM calculator module."""
        vram_page.build(ctx)

    @ui.page("/settings")
    def settings_route() -> None:
        """Settings module."""
        settings_page.build(ctx)

    if not check_port_available(config.host, config.port):
        logger.error(
            "Port %s:%s is already in use; free it or start with "
            "--port <n> (or WEBBOX_PORT=<n>).",
            config.host,
            config.port,
        )
        raise SystemExit(1)
    logger.info("Starting NiceGUI frontend on %s:%s", config.host, config.port)
    ui.run(
        host=config.host,
        port=config.port,
        title=APP_NAME,
        reload=False,
        show=False,
        uvicorn_logging_level="warning",
    )


def _set_dark(dark: bool) -> None:
    """Set NiceGUI dark mode (global element, safe at startup).

    Args:
        dark: Whether dark mode is active.
    """
    ui.dark_mode.value = dark


if __name__ in {"__main__", "__mp_main__"}:
    main()
